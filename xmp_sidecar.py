"""XMP sidecar files for Adobe Lightroom Classic (1.11): stars and keywords without the plug-in.

For a RAW photo `DSC_1234.NEF`, Lightroom reads `DSC_1234.xmp` next to it when it imports the photo
(Add or Copy) and takes its star rating (xmp:Rating) and keywords (lr:hierarchicalSubject, e.g.
"PhotoSelect|Keep"). PhotoSelect writes only these sidecars; the photo files are never changed.

* An existing sidecar (from Lightroom, Bridge, Capture One ...) is merged: only the PhotoSelect
  keywords are replaced, and the rating is set only when it is empty or still the one PhotoSelect
  wrote last time (stars you gave elsewhere are kept).
* Every sidecar written is recorded in a ledger (sidecars.json, in PhotoSelect's support folder), so
  they can be removed again and so star changes Lightroom writes back into them can be read.
* JPEG, PNG, TIFF, HEIC and DNG keep their metadata inside the file, which PhotoSelect never
  changes, so they get no sidecar.
"""
import io
import json
import os
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import raw_io

NS = {
    'x': 'adobe:ns:meta/',
    'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
    'xmp': 'http://ns.adobe.com/xap/1.0/',
    'dc': 'http://purl.org/dc/elements/1.1/',
    'lr': 'http://ns.adobe.com/lightroom/1.0/',
}
TOOLKIT = 'PhotoSelect'          # x:xmptk of sidecars PhotoSelect created (Lightroom replaces it when it rewrites one)
PARENT = 'PhotoSelect'           # keywords go under PhotoSelect › ...
FROM = 'From PhotoSelect'        # on every photo PhotoSelect rated (used by the Smart Collections)
FORMATS = raw_io.RAW - {'.dng'}  # Lightroom reads sidecars for these; DNG keeps XMP inside the file
TRACK_DAYS = 90                  # star changes are read back for sidecars written in the last 90 days

_lock = threading.Lock()


def _q(prefix, name):
    return f'{{{NS[prefix]}}}{name}'


def supported(path):
    return Path(path).suffix.lower() in FORMATS


def sidecar_for(photo):
    p = Path(photo)
    for candidate in (p.with_suffix('.xmp'), p.with_suffix('.XMP')):
        if candidate.exists():
            return candidate
    return p.with_suffix('.xmp')


# ---------------------------------------------------------------------------------- XMP documents
def _register(text):
    """Keep the prefixes the file already uses when it is written back."""
    for prefix, uri in NS.items():
        ET.register_namespace(prefix, uri)
    try:
        for _, (prefix, uri) in ET.iterparse(io.StringIO(text), events=('start-ns',)):
            if prefix and not prefix.startswith('ns'):
                ET.register_namespace(prefix, uri)
    except ET.ParseError:
        pass


def new_document():
    _register('')
    root = ET.Element(_q('x', 'xmpmeta'), {_q('x', 'xmptk'): TOOLKIT})
    rdf = ET.SubElement(root, _q('rdf', 'RDF'))
    ET.SubElement(rdf, _q('rdf', 'Description'), {_q('rdf', 'about'): ''})
    return root


def _descriptions(root):
    rdf = root if root.tag == _q('rdf', 'RDF') else root.find(_q('rdf', 'RDF'))
    if rdf is None:
        rdf = ET.SubElement(root, _q('rdf', 'RDF'))
    found = rdf.findall(_q('rdf', 'Description'))
    if not found:
        found = [ET.SubElement(rdf, _q('rdf', 'Description'), {_q('rdf', 'about'): ''})]
    return found


def rating_of(root):
    """The star rating in an XMP document (attribute or element form), or None."""
    for d in _descriptions(root):
        value = d.get(_q('xmp', 'Rating'))
        if value is None:
            el = d.find(_q('xmp', 'Rating'))
            value = el.text if el is not None else None
        if value is not None:
            try:
                return int(float(value))
            except ValueError:
                return None
    return None


def _set_rating(root, rating):
    descs = _descriptions(root)
    for d in descs:
        if d.get(_q('xmp', 'Rating')) is not None:
            d.set(_q('xmp', 'Rating'), str(rating))
            return
        el = d.find(_q('xmp', 'Rating'))
        if el is not None:
            el.text = str(rating)
            return
    descs[0].set(_q('xmp', 'Rating'), str(rating))


def _bag(root, prefix, name):
    for d in _descriptions(root):
        prop = d.find(_q(prefix, name))
        if prop is not None:
            bag = prop.find(_q('rdf', 'Bag'))
            if bag is None:
                bag = ET.SubElement(prop, _q('rdf', 'Bag'))
            return bag
    prop = ET.SubElement(_descriptions(root)[0], _q(prefix, name))
    return ET.SubElement(prop, _q('rdf', 'Bag'))


def keywords_of(root):
    """The PhotoSelect keywords (leaf names) in an XMP document."""
    out = []
    for d in _descriptions(root):
        prop = d.find(_q('lr', 'hierarchicalSubject'))
        if prop is not None:
            for li in prop.iter(_q('rdf', 'li')):
                if (li.text or '').startswith(PARENT + '|'):
                    out.append(li.text.split('|', 1)[1])
    return out


def _set_keywords(root, keywords):
    """Replace the PhotoSelect keywords, keeping every other keyword."""
    hier, flat = _bag(root, 'lr', 'hierarchicalSubject'), _bag(root, 'dc', 'subject')
    old = {li.text.split('|', 1)[1] for li in list(hier) if (li.text or '').startswith(PARENT + '|')}
    for li in list(hier):
        if (li.text or '').startswith(PARENT + '|') or li.text == PARENT:
            hier.remove(li)
    for li in list(flat):
        if li.text in old or li.text == PARENT:
            flat.remove(li)
    for k in keywords:
        ET.SubElement(hier, _q('rdf', 'li')).text = f'{PARENT}|{k}'
    present = {li.text for li in flat}
    for k in ([PARENT] + list(keywords)) if keywords else []:
        if k not in present:
            ET.SubElement(flat, _q('rdf', 'li')).text = k
            present.add(k)
    # drop properties left empty (e.g. after removing PhotoSelect's keywords)
    for d in _descriptions(root):
        for prefix, name in (('lr', 'hierarchicalSubject'), ('dc', 'subject')):
            prop = d.find(_q(prefix, name))
            if prop is not None and not list(prop.iter(_q('rdf', 'li'))):
                d.remove(prop)


def serialise(root):
    return ET.tostring(root, encoding='unicode') + '\n'


def parse(text):
    _register(text)
    return ET.fromstring(text)


def _write(path, text):
    tmp = path.with_name(path.name + '.photoselect-tmp')
    tmp.write_text(text, encoding='utf-8')
    os.replace(tmp, path)


# ---------------------------------------------------------------------------------- ledger
def _ledger_path(folder):
    return Path(folder) / 'sidecars.json'


def load_ledger(folder):
    try:
        return json.loads(_ledger_path(folder).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def save_ledger(folder, ledger):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    oldest = time.time() - TRACK_DAYS * 86400
    ledger = {k: v for k, v in ledger.items() if v.get('at', 0) >= oldest or v.get('created')}
    tmp = _ledger_path(folder).with_suffix('.tmp')
    tmp.write_text(json.dumps(ledger, indent=0), encoding='utf-8')
    os.replace(tmp, _ledger_path(folder))


# ---------------------------------------------------------------------------------- operations
def write_one(photo, rating, keywords, ledger):
    """Write or merge the sidecar of one RAW photo. Returns 'created', 'updated' or 'unchanged',
    and whether the rating was kept because stars were already set elsewhere."""
    photo = Path(photo)
    side = sidecar_for(photo)
    entry = ledger.get(str(photo), {})
    keywords = list(dict.fromkeys(list(keywords) + [FROM]))
    if side.exists():
        before = side.read_text(encoding='utf-8', errors='replace')
        root = parse(before)
        created = bool(entry.get('created')) and (root.get(_q('x', 'xmptk')) or '').startswith(TOOLKIT)
    else:
        before, root, created = None, new_document(), True
    current = rating_of(root)
    # stars set elsewhere (not the rating PhotoSelect wrote last time) are kept
    kept = bool(current) and current != entry.get('ours') and current != rating
    if not kept:
        _set_rating(root, rating)
    _set_keywords(root, keywords)
    text = serialise(root)
    status = 'unchanged'
    if text != before:
        _write(side, text)
        status = 'created' if before is None else 'updated'
    ledger[str(photo)] = {'sidecar': str(side), 'created': created, 'rating': rating_of(root) or 0,
                          'ours': entry.get('ours') if kept else rating, 'mtime': side.stat().st_mtime, 'at': time.time()}
    return status, kept


def write_all(folder, rows):
    """Sidecars for rows [{path, name, rating, keywords}]. Returns a summary for the Lightroom window."""
    out = {'created': 0, 'updated': 0, 'unchanged': 0, 'kept': 0, 'skipped': [], 'failed': []}
    with _lock:
        ledger = load_ledger(folder)
        try:
            for r in rows:
                if not supported(r['path']):
                    out['skipped'].append(r['name'])
                    continue
                if not os.path.isfile(r['path']):
                    out['failed'].append([r['name'], 'the photo was not found (is the card or drive connected?)'])
                    continue
                try:
                    status, kept = write_one(r['path'], int(r['rating']), r.get('keywords') or [], ledger)
                    out[status] += 1
                    out['kept'] += kept
                except PermissionError:
                    out['failed'].append([r['name'], 'the folder is read-only (a locked card?)'])
                except OSError as error:
                    out['failed'].append([r['name'], error.strerror or str(error)])
                except ET.ParseError:
                    out['failed'].append([r['name'], 'its existing sidecar could not be read, so it was left alone'])
        finally:
            save_ledger(folder, ledger)
    out['written'] = out['created'] + out['updated'] + out['unchanged']
    return out


def remove_all(folder):
    """Delete the sidecars PhotoSelect created that nothing else has changed since; from other
    sidecars remove only the PhotoSelect keywords. Returns counts."""
    out = {'deleted': 0, 'cleaned': 0, 'missing': 0, 'failed': 0}
    with _lock:
        ledger = load_ledger(folder)
        for photo, entry in list(ledger.items()):
            side = Path(entry['sidecar'])
            try:
                if not side.exists():
                    out['missing'] += 1
                else:
                    root = parse(side.read_text(encoding='utf-8', errors='replace'))
                    ours = (root.get(_q('x', 'xmptk')) or '').startswith(TOOLKIT)
                    if entry.get('created') and ours:
                        side.unlink()
                        out['deleted'] += 1
                    else:
                        _set_keywords(root, [])
                        _write(side, serialise(root))
                        out['cleaned'] += 1
                del ledger[photo]
            except (OSError, ET.ParseError):
                out['failed'] += 1
        save_ledger(folder, ledger)
    return out


def star_changes(folder):
    """Star changes written into PhotoSelect's sidecars since they were written (by Lightroom when
    its catalog setting "Automatically write changes into XMP" is on): [(stars before, now, photo)]."""
    changes = []
    with _lock:
        ledger = load_ledger(folder)
        dirty = False
        for photo, entry in ledger.items():
            side = Path(entry['sidecar'])
            try:
                mtime = side.stat().st_mtime
            except OSError:
                continue
            if mtime == entry.get('mtime'):
                continue
            try:
                rating = rating_of(parse(side.read_text(encoding='utf-8', errors='replace'))) or 0
            except (OSError, ET.ParseError):
                continue
            if rating != entry.get('rating'):
                changes.append((int(entry.get('rating') or 0), rating, photo))
            entry['rating'], entry['mtime'], dirty = rating, mtime, True
        if dirty:
            save_ledger(folder, ledger)
    return changes


# ---------------------------------------------------------------------------------- Smart Collections
COLLECTIONS = [
    ('1 Rescue', {'criteria': 'rating', 'operation': '==', 'value': 1}),
    ('2 Confirm', {'criteria': 'rating', 'operation': '==', 'value': 3}),
    ('3 Decide', {'criteria': 'rating', 'operation': '==', 'value': 2}),
    ('Liked', {'criteria': 'rating', 'operation': '==', 'value': 5}),
    ('Borderline', {'criteria': 'keywords', 'operation': 'words', 'value': 'Borderline'}),
]


def _lua(value):
    return f'"{value}"' if isinstance(value, str) else str(value)


def smart_collection_files(folder):
    """Lightroom Smart Collection settings (.lrsmcol), one per review pass, to import once in Lightroom
    (right-click a collection set → Import Smart Collection Settings…). Returns the folder."""
    folder = Path(folder) / 'Smart Collections'
    folder.mkdir(parents=True, exist_ok=True)
    for title, rule in COLLECTIONS:
        second = {'criteria': 'keywords', 'operation': 'all', 'value': FROM}
        rules = ''.join('\t\t{\n' + ''.join(f'\t\t\t{k} = {_lua(v)},\n' for k, v in r.items())
                        + f'\t\t\tvalue2 = {"0" if isinstance(r["value"], int) else chr(34) * 2},\n\t\t}},\n'
                        for r in (rule, second))
        text = (f's = {{\n\tid = "PhotoSelect-{title.replace(" ", "-")}",\n\tinternalName = "{title}",\n'
                f'\ttitle = "{title}",\n\ttype = "LibrarySmartCollection",\n\tvalue = {{\n{rules}'
                f'\t\tcombine = "intersect",\n\t}},\n\tversion = 0,\n}}\n')
        (folder / f'PhotoSelect {title}.lrsmcol').write_text(text, encoding='utf-8')
    return folder
