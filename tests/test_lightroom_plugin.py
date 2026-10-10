"""Tests of the Lightroom Classic plug-in's Lua code under Lua 5.1 (Lightroom's Lua version).

SelectionsCore.lua is tested directly. ApplySelections.lua is run against a simulated Lightroom SDK
and catalog. Lightroom itself cannot run here, so the SDK calls are checked against these mocks
only; the field test sheet covers a real Lightroom Classic run. Needs the `lupa` package.
"""
import os
import time
import unittest
from pathlib import Path

import helpers  # noqa: F401  (adds the project folder to sys.path)
import app as app_module

try:
    from lupa import lua51
except ImportError:
    lua51 = None

PLUGIN = Path(__file__).resolve().parent.parent / 'lightroom' / 'PhotoSelect.lrplugin'


def selections(rows, exported=None, auto=False):
    text = app_module.lightroom_selections('/Photos', rows, auto)
    if exported is not None:
        head, rest = text.split('\n', 1)
        parts = head.split('\t')
        parts[2] = str(exported)
        text = '\t'.join(parts) + '\n' + rest
    return text


def row(name, rating, capture='2026-05-01 10:00:00', keywords=('Keep',), folder='/Volumes/Card/DCIM'):
    return {'path': f'{folder}/{name}', 'name': name, 'capture': capture, 'rating': rating,
            'keywords': list(keywords), 'decision': '', 'suggestion': 'Keep'}


@unittest.skipIf(lua51 is None, 'lupa (Lua 5.1) not installed')
class SelectionsCoreTests(unittest.TestCase):
    def setUp(self):
        self.lua = lua51.LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(f"package.path = [[{PLUGIN}/?.lua;]] .. package.path")
        self.core = self.lua.eval("require 'SelectionsCore'")
        # always two results, so Python can unpack them the same way whatever Lua returned
        self.parse = self.lua.eval("function(t) local a, b = require('SelectionsCore').parse(t) return a, b end")
        self.match = self.lua.eval("function(i, p) local a, b = require('SelectionsCore').match(i, p) return a, b end")

    def files(self, *texts):
        t = self.lua.table()
        for i, text in enumerate(texts, 1):
            parsed, err = self.parse(text)
            self.assertIsNone(err)
            t[i] = parsed
        return t

    def photo(self, **kw):
        return self.lua.table_from(kw)

    def test_parse_reads_what_photoselect_writes(self):
        parsed, err = self.parse(selections([row('DSC_0001.NEF', 5, keywords=['Keep', 'Liked', 'Burst 007'])]))
        self.assertIsNone(err)
        e = parsed.entries[1]
        self.assertEqual((e.name, e.capture, e.rating, e.path), ('DSC_0001.NEF', '2026-05-01 10:00:00', 5, '/Volumes/Card/DCIM/DSC_0001.NEF'))
        self.assertEqual(list(e.keywords.values()), ['Keep', 'Liked', 'Burst 007'])
        parsed, err = self.parse('something else')
        self.assertIsNone(parsed)
        self.assertIn('not a PhotoSelect', err)

    def test_matching_strategies(self):
        idx = self.core.index(self.files(selections([
            row('DSC_0001.NEF', 3), row('DSC_0002.NEF', 1, capture='2026-05-01 10:00:01'),
            row('DSC_0003.NEF', 2, capture='2026-05-01 10:00:02'), row('DSC_0004.NEF', 2, capture='2026-05-01 10:00:02')])))
        m = lambda **kw: self.match(idx, self.photo(**kw))
        e, how = m(path='/volumes/card/dcim/DSC_0001.NEF')                     # same file (case-insensitive)
        self.assertEqual((e.rating, how), (3, 'path'))
        e, how = m(path='/Pictures/2026/DSC_0002.NEF', fileName='DSC_0002.NEF', capture='2026-05-01 10:00:01')
        self.assertEqual((e.name, how), ('DSC_0002.NEF', 'name'))             # copied on import
        e, how = m(path='/P/Sail-17.NEF', fileName='Sail-17.NEF', preservedFileName='DSC_0001.NEF', capture='2026-05-01 10:00:00')
        self.assertEqual((e.name, how), ('DSC_0001.NEF', 'name'))             # renamed, original name kept
        e, how = m(path='/P/Sail-18.NEF', fileName='Sail-18.NEF', capture='2026-05-01 10:00:01')
        self.assertEqual((e.name, how), ('DSC_0002.NEF', 'time'))             # renamed: unique capture time
        e, how = m(path='/P/Sail-19.NEF', fileName='Sail-19.NEF', capture='2026-05-01 10:00:02')
        self.assertEqual((e, how), (None, 'ambiguous'))                         # two frames in that second
        e, how = m(path='/P/Sail-20.JPG', fileName='Sail-20.JPG', capture='2026-05-01 10:00:01')
        self.assertIsNone(e)                                                    # different file type
        e, how = m(path='/P/x.NEF', fileName='x.NEF', capture='2027-01-01 00:00:00')
        self.assertIsNone(e)

    def test_dng_copies_time_zones_and_unmatched_names(self):
        idx = self.core.index(self.files(selections([
            row('DSC_0001.NEF', 3), row('DSC_0002.NEF', 1, capture='2026-05-01 10:00:01'),
            row('DSC_0002.NEF', 2, capture='2026-05-02 08:00:00', folder='/Volumes/Card/DAY2')])))
        m = lambda **kw: self.match(idx, self.photo(**kw))
        e, how = m(path='/P/DSC_0002.dng', fileName='DSC_0002.dng', capture='2026-05-01 10:00:01')
        self.assertEqual((e.rating, how), (1, 'name'))                          # Copy as DNG
        e, how = m(path='/P/DSC_0001.dng', fileName='DSC_0001.dng', capture='')
        self.assertEqual((e.rating, how), (3, 'name'))                          # unique name without extension
        e, how = m(path='/P/DSC_0001.NEF', fileName='DSC_0001.NEF', capture='2026-05-01 12:00:00')
        self.assertEqual(e.rating, 3)                                           # unique name wins anyway
        e, how = m(path='/P/DSC_0002.NEF', fileName='DSC_0002.NEF', capture='2026-05-02 10:00:00')
        self.assertEqual((e.rating, how), (2, 'time zone'))                     # two DSC_0002: 2 h offset picks one
        e, how = m(path='/P/DSC_0002.NEF', fileName='DSC_0002.NEF', capture='2026-05-02 10:30:00')
        self.assertIsNone(e)                                                    # not whole hours
        self.assertEqual(self.lua.eval("require('SelectionsCore').seconds")('2026-03-01 00:00:00')
                         - self.lua.eval("require('SelectionsCore').seconds")('2026-02-28 00:00:00'), 86400)
        photos = self.lua.table(self.photo(path='/P/IMG_9.NEF', fileName='IMG_9.NEF', capture='2026-01-01 00:00:00'))
        plan = self.core.plan(idx, photos, False)
        text = self.core.summary(plan, 1, 3, 'all 1 photos shown', idx)
        self.assertIn('Not matched: IMG_9.NEF', text)
        self.assertIn('PhotoSelect has 3 photos named DSC_0001.NEF … DSC_0002.NEF', text)

    def test_newer_export_wins(self):
        old = selections([row('DSC_0001.NEF', 1, keywords=['Drop'])], exported=100)
        new = selections([row('DSC_0001.NEF', 3, keywords=['Keep'])], exported=200)
        idx = self.core.index(self.files(new, old))
        e, _ = self.match(idx, self.photo(path='/Volumes/Card/DCIM/DSC_0001.NEF', fileName='DSC_0001.NEF'))
        self.assertEqual(e.rating, 3)
        e, _ = self.match(idx, self.photo(path='/elsewhere/DSC_0001.NEF', fileName='DSC_0001.NEF'))
        self.assertEqual(e.rating, 3)                                           # name only: replaced entry ignored

    def test_plan_keeps_existing_ratings_unless_asked(self):
        idx = self.core.index(self.files(selections([row('a.NEF', 3), row('b.NEF', 1), row('c.NEF', 5)])))
        photos = self.lua.table(self.photo(path='/Volumes/Card/DCIM/a.NEF', rating=0),
                                self.photo(path='/Volumes/Card/DCIM/b.NEF', rating=4),
                                self.photo(path='/Volumes/Card/DCIM/c.NEF', rating=5),
                                self.photo(path='/Volumes/Card/DCIM/z.NEF', fileName='z.NEF', rating=2))
        plan = self.core.plan(idx, photos, False)
        self.assertEqual((plan.matched, plan.notFound, plan.conflicts, plan.unchanged, plan.rated), (3, 1, 1, 1, 1))
        self.assertEqual([plan['items'][i].setRating for i in (1, 2, 3)], [3, None, None])
        plan = self.core.plan(idx, photos, True)
        self.assertEqual([plan['items'][i].setRating for i in (1, 2, 3)], [3, 1, None])
        text = self.core.summary(plan, 4, 3)
        self.assertIn('Checked 4 photos: 3 of 4 match', text)
        self.assertIn('1 already have a different star rating', text)


@unittest.skipIf(lua51 is None, 'lupa (Lua 5.1) not installed')
class ApplySelectionsTests(unittest.TestCase):
    """Runs Library > Plug-in Extras > Apply PhotoSelect Selections against a simulated catalog."""

    def run_plugin(self, folder, photos, answer='ok', overwrite=False, selected=None, script='ApplySelections.lua'):
        lua = lua51.LuaRuntime(unpack_returned_tuples=True)
        lua.execute(f"package.path = [[{PLUGIN}/?.lua;]] .. package.path")
        lua.execute(f"package.loaded['Config'] = {{ selectionsFolder = [==[{folder}]==] }}")
        lua.globals().LIST_DIR = lambda f: lua.table(*[str(p) for p in sorted(Path(f).iterdir())])
        lua.globals().NOW_UNIX = time.time()
        lua.globals().EXISTS = lambda p: 'directory' if Path(p).is_dir() else 'file' if Path(p).is_file() else False
        lua.globals().PLUGIN_DIR = str(PLUGIN)
        lua.execute(SDK_MOCK)
        lua.globals().ANSWER, lua.globals().OVERWRITE = answer, overwrite
        for p in photos:
            lua.eval('addPhoto')(lua.table_from(p))
        if selected is not None:
            lua.eval('selectPhotos')(lua.table(*selected))
        if script:
            lua.execute((PLUGIN / script).read_text())
        return lua

    @staticmethod
    def ops(lua):
        """LightroomOps, each call run as a Lightroom background task (catalog calls pause it, as in Lightroom)."""
        class Ops:
            def __getattr__(self, name):
                return lambda *args: lua.globals().runTask(lua.eval("require 'LightroomOps'")[name], *args)
        return Ops()

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        (self.folder / 'one.tsv').write_text(selections([
            row('DSC_0001.NEF', 5, keywords=['Keep', 'Liked', 'Burst 001']),
            row('DSC_0002.NEF', 1, capture='2026-05-01 10:00:01', keywords=['Drop', 'Burst 001']),
            row('DSC_0003.NEF', 2, capture='2026-05-01 10:00:05', keywords=['Consider'])]))

    def tearDown(self):
        self.tmp.cleanup()

    def photos(self):
        # imported with Copy into the Lightroom folder structure; the third was already rated 4 stars
        # and carries a PhotoSelect keyword from an earlier run
        return [{'path': '/Pictures/2026/DSC_0001.NEF', 'fileName': 'DSC_0001.NEF', 'time': '2026-05-01 10:00:00', 'rating': 0},
                {'path': '/Pictures/2026/DSC_0002.NEF', 'fileName': 'DSC_0002.NEF', 'time': '2026-05-01 10:00:01'},
                {'path': '/Pictures/2026/DSC_0003.NEF', 'fileName': 'DSC_0003.NEF', 'time': '2026-05-01 10:00:05', 'rating': 4,
                 'oldKeyword': 'Drop'},
                {'path': '/Pictures/2026/OTHER.NEF', 'fileName': 'OTHER.NEF', 'time': '2026-05-02 09:00:00', 'rating': 2}]

    def state(self, lua):
        # every photo PhotoSelect rated also gets "From PhotoSelect" (checked in test_smart_collections...)
        return {p.fileName: (p.rating, sorted(k for k in lua.eval('keywordNames')(p).values() if k != 'PhotoSelect/From PhotoSelect'))
                for p in lua.globals().PHOTOS.values()}

    def test_apply_sets_stars_and_keywords(self):
        lua = self.run_plugin(self.folder, self.photos())
        g = lua.globals()
        self.assertIn('Checked 4 photos: 3 of 4 match', g.DIALOG_TEXT)
        self.assertIn('1 photos were not found', g.DIALOG_TEXT)
        self.assertEqual(self.state(lua), {
            'DSC_0001.NEF': (5, ['PhotoSelect/Burst 001', 'PhotoSelect/Keep', 'PhotoSelect/Liked']),
            'DSC_0002.NEF': (1, ['PhotoSelect/Burst 001', 'PhotoSelect/Drop']),
            'DSC_0003.NEF': (4, ['PhotoSelect/Consider']),        # existing 4 stars kept; old keyword replaced
            'OTHER.NEF': (2, []),
        })
        self.assertEqual(g.WRITES, 2)                                   # selections, then the Smart Collections
        self.assertIn('2 star ratings set', g.MESSAGE)

    def test_overwrite_existing_ratings_when_ticked(self):
        lua = self.run_plugin(self.folder, self.photos(), overwrite=True)
        self.assertEqual(self.state(lua)['DSC_0003.NEF'][0], 2)

    def test_cancel_changes_nothing(self):
        lua = self.run_plugin(self.folder, self.photos(), answer='cancel')
        self.assertEqual(lua.globals().WRITES, 0)
        self.assertEqual(self.state(lua)['DSC_0001.NEF'], (0, []))

    def test_one_selected_photo_checks_the_whole_view(self):
        # The owner's first real run: one photo was selected, so only it was checked and nothing matched.
        lua = self.run_plugin(self.folder, self.photos(), selected=[4])
        self.assertIn('Checked all 4 photos shown: 3 of 4 match', lua.globals().DIALOG_TEXT)
        lua = self.run_plugin(self.folder, self.photos(), selected=[1, 4])
        self.assertIn('Checked 2 photos: 1 of 2 match', lua.globals().DIALOG_TEXT)
        self.assertIn('Not matched: OTHER.NEF', lua.globals().DIALOG_TEXT)

    def test_photos_not_imported_yet_explained(self):
        lua = self.run_plugin(self.folder, [self.photos()[3]])
        self.assertIn('Not matched: OTHER.NEF', lua.globals().MESSAGE)
        self.assertIn('import that folder first', lua.globals().MESSAGE)

    def pending(self, rows, age=0, name='pending.import', auto=True):
        text = selections(rows, auto=auto)
        head, rest = text.split('\n', 1)
        parts = head.split('\t')
        parts[2] = str(float(parts[2]) - age)
        (self.folder / name).write_text('\t'.join(parts) + '\n' + rest)

    def test_auto_apply_after_open_in_lightroom_import(self):
        # PhotoSelect handed two Keep photos to Lightroom's Import window; one was added in place, one copied.
        self.pending([row('DSC_0001.NEF', 3, keywords=['Keep']),
                      row('DSC_0009.NEF', 3, capture='2026-05-01 10:00:09', keywords=['Keep'])])
        photos = [{'path': '/Volumes/Card/DCIM/DSC_0001.NEF', 'fileName': 'DSC_0001.NEF', 'time': '2026-05-01 10:00:00'},
                  {'path': '/Pictures/DSC_0009.NEF', 'fileName': 'DSC_0009.NEF', 'time': '2026-05-01 10:00:09', 'rating': 4}]
        lua = self.run_plugin(self.folder / 'none', [], script=None)
        lua.execute(f"package.loaded['Config'] = {{ selectionsFolder = [==[{self.folder}]==] }}")
        ops = self.ops(lua)
        self.assertEqual(ops.autoApply(1, 8), 0)                      # nothing imported yet
        self.assertEqual(lua.globals().WRITES, 0)
        lua.eval('addPhoto')(lua.table_from(photos[0]))               # the import runs
        self.assertEqual(ops.autoApply(1, 8), 1)                      # found by path in the next pass
        self.assertEqual(ops.autoApply(2, 8), 0)                      # never applied twice
        lua.eval('addPhoto')(lua.table_from(photos[1]))
        self.assertEqual(ops.autoApply(3, 8), 0)                      # copied: found by the capture-date lookup
        self.assertEqual(ops.autoApply(8, 8), 1)
        self.assertEqual(self.state(lua), {'DSC_0001.NEF': (3, ['PhotoSelect/Keep']),
                                           'DSC_0009.NEF': (4, ['PhotoSelect/Keep'])})   # existing 4 stars kept
        self.assertFalse((self.folder / 'pending.import').exists())  # all done
        self.assertIn('stars applied to 1 imported photos', lua.globals().BEZEL)
        status = dict(l.split('\t') for l in (self.folder / 'plugin-status.txt').read_text().splitlines())
        self.assertEqual((status['version'], status['applied_count']), ('1.8.0', '1'))

    def test_auto_apply_after_any_import_of_sent_selections(self):
        # "Send to Lightroom" with automatic rating, then an ordinary import started in Lightroom (renamed files).
        (self.folder / 'one.tsv').unlink()
        self.pending([row('DSC_0001.NEF', 3, keywords=['Keep']), row('DSC_0002.NEF', 1, capture='2026-05-01 10:00:01',
                      keywords=['Drop'])], name='sent.tsv')
        self.pending([row('DSC_0003.NEF', 2, capture='2026-05-01 10:00:02', keywords=['Consider'])],
                     name='manual.tsv', auto=False)
        photos = [{'path': '/P/Sail-1.NEF', 'fileName': 'Sail-1.NEF', 'preserved': 'DSC_0001.NEF', 'time': '2026-05-01 10:00:00'},
                  {'path': '/P/DSC_0002.dng', 'fileName': 'DSC_0002.dng', 'time': '2026-05-01 10:00:01'},
                  {'path': '/P/DSC_0003.NEF', 'fileName': 'DSC_0003.NEF', 'time': '2026-05-01 10:00:02'},
                  {'path': '/P/Other.NEF', 'fileName': 'Other.NEF', 'time': '2026-04-01 10:00:00'}]
        lua = self.run_plugin(self.folder, photos, script=None)
        ops = self.ops(lua)
        self.assertEqual(ops.autoApply(1, 8), 0)                      # selections are looked up on slow passes only
        self.assertEqual(ops.autoApply(8, 8), 2)
        self.assertEqual({k: v[0] or 0 for k, v in self.state(lua).items()},
                         {'Sail-1.NEF': 3, 'DSC_0002.dng': 1, 'DSC_0003.NEF': 0, 'Other.NEF': 0})   # auto off: untouched
        # after a Lightroom restart, photos already rated are not rated again even if their stars were removed
        for p in lua.globals().PHOTOS.values():
            p.rating = 0
        ops.reset()
        self.assertEqual(ops.autoApply(16, 8), 0)
        self.assertEqual(lua.globals().WRITES, 2)

    def test_file_name_search_when_the_date_search_fails(self):
        # If Lightroom rejects the capture-date search, photos are found by file name instead, and the
        # error is reported to PhotoSelect rather than swallowed.
        (self.folder / 'one.tsv').unlink()
        self.pending([row('DSC_0001.NEF', 3, keywords=['Keep']), row('DSC_0002.NEF', 1, capture='2026-05-01 10:00:01',
                      keywords=['Drop'])], name='sent.tsv')
        photos = [{'path': '/P/DSC_0001.NEF', 'fileName': 'DSC_0001.NEF', 'time': '2026-05-01 10:00:00'},
                  {'path': '/P/DSC_0002.dng', 'fileName': 'DSC_0002.dng', 'time': '2026-05-01 10:00:01'},
                  {'path': '/P/DSC_0003.NEF', 'fileName': 'DSC_0003.NEF', 'time': '2026-05-01 10:00:02'}]
        lua = self.run_plugin(self.folder, photos, script=None)
        lua.globals().DATE_SEARCH_FAILS = True
        ops = self.ops(lua)
        self.assertEqual(ops.autoApply(8, 8), 2)
        self.assertEqual({k: v[0] or 0 for k, v in self.state(lua).items()},
                         {'DSC_0001.NEF': 3, 'DSC_0002.dng': 1, 'DSC_0003.NEF': 0})
        status = dict(l.split('\t', 1) for l in (self.folder / 'plugin-status.txt').read_text().splitlines())
        self.assertIn('capture date', status['last_error'])
        self.assertIn('unsupported search criteria', status['last_error'])
        self.assertEqual(status['last_search'], 'file names (2): 2 photos')

    def test_date_search_works_inside_a_lightroom_task(self):
        # 1.5-1.7 wrapped the search in plain pcall, which fails as soon as Lightroom pauses the task.
        (self.folder / 'one.tsv').unlink()
        self.pending([row('DSC_0001.NEF', 3, keywords=['Keep'])], name='sent.tsv')
        lua = self.run_plugin(self.folder, [{'path': '/P/Sail-1.NEF', 'fileName': 'Sail-1.NEF', 'time': '2026-05-01 10:00:00'}],
                              script=None)
        self.assertEqual(self.ops(lua).autoApply(8, 8), 1)                      # renamed on import: date search only
        status = dict(l.split('\t', 1) for l in (self.folder / 'plugin-status.txt').read_text().splitlines())
        self.assertEqual((status['last_error'], status['last_search']), ('', 'capture date 2026-05-01 to 2026-05-01: 1 photos'))
        self.assertEqual(lua.globals().SEARCHES, 1)

    def test_auto_apply_requests_expire(self):
        self.pending([row('DSC_0001.NEF', 3)], age=4 * 3600)                       # Open in Lightroom: 3 hours
        self.pending([row('DSC_0002.NEF', 3, capture='2026-05-01 10:00:01')], age=15 * 86400, name='old.tsv')
        (self.folder / 'one.tsv').unlink()
        lua = self.run_plugin(self.folder, self.photos(), script=None)
        self.assertEqual(self.ops(lua).autoApply(8, 8), 0)
        self.assertFalse((self.folder / 'pending.import').exists())
        self.assertEqual(lua.globals().WRITES, 0)

    def test_init_runs_background_task_until_shutdown(self):
        self.pending([row('DSC_0001.NEF', 3, folder='/Pictures/2026')])     # imported with Add
        lua = self.run_plugin(self.folder, self.photos(), script='Init.lua')   # mock sleep runs Shutdown.lua
        self.assertEqual(lua.globals().SLEEPS, 1)
        self.assertEqual(self.state(lua)['DSC_0001.NEF'][0], 3)
        self.assertIn('version\t1.8.0', (self.folder / 'plugin-status.txt').read_text())

    def test_smart_collections_and_from_photoselect_keyword(self):
        lua = self.run_plugin(self.folder, self.photos())
        named = {p.fileName: 'PhotoSelect/From PhotoSelect' in lua.eval('keywordNames')(p).values()
                 for p in lua.globals().PHOTOS.values()}
        self.assertEqual(named, {'DSC_0001.NEF': True, 'DSC_0002.NEF': True, 'DSC_0003.NEF': True, 'OTHER.NEF': False})
        rules = {k: (v.criteria, v.operation, v.value) for k, v in lua.globals().COLLECTIONS.items()}
        self.assertEqual(rules, {'PhotoSelect/1 Rescue': ('rating', '==', 1), 'PhotoSelect/2 Confirm': ('rating', '==', 3),
                                 'PhotoSelect/3 Decide': ('rating', '==', 2), 'PhotoSelect/Liked': ('rating', '==', 5),
                                 'PhotoSelect/Borderline': ('keywords', 'words', 'Borderline')})

    def test_star_changes_in_lightroom_are_reported(self):
        lua = self.run_plugin(self.folder, self.photos())
        ops = self.ops(lua)
        tracked = (self.folder / 'tracked.txt').read_text().splitlines()
        self.assertEqual(sorted(l.split('\t')[1] + ' ' + l.split('\t')[3] for l in tracked),
                         ['1 /Volumes/Card/DCIM/DSC_0002.NEF', '4 /Volumes/Card/DCIM/DSC_0003.NEF',
                          '5 /Volumes/Card/DCIM/DSC_0001.NEF'])                 # stars after applying (4 was kept)
        self.assertEqual(ops.syncBack(), 0)
        photos = list(lua.globals().PHOTOS.values())
        photos[1].rating = 3                                                     # Drop rescued to Keep
        photos[0].rating = 2                                                     # Liked demoted to Consider
        photos[3].rating = 5                                                     # not from PhotoSelect: ignored
        self.assertEqual(ops.syncBack(), 2)
        self.assertEqual(ops.syncBack(), 0)                                      # reported once
        ops.reset()                                                              # Lightroom restarted
        self.assertEqual(ops.syncBack(), 0)
        photos[2].removed = True                                                 # removed from the catalog
        self.assertEqual(ops.syncBack(), 0)
        self.assertEqual(len((self.folder / 'tracked.txt').read_text().splitlines()), 2)
        changes = [l.split('\t')[1:] for l in (self.folder / 'lightroom-changes.tsv').read_text().splitlines()]
        self.assertEqual(sorted(changes), [['1', '3', '/Volumes/Card/DCIM/DSC_0002.NEF'],
                                           ['5', '2', '/Volumes/Card/DCIM/DSC_0001.NEF']])

    def test_no_selections_explains_what_to_do(self):
        lua = self.run_plugin(self.folder / 'missing', self.photos())
        self.assertIn('Send to Lightroom', lua.globals().MESSAGE)
        self.assertEqual(lua.globals().WRITES, 0)


SDK_MOCK = r'''
PHOTOS, SELECTED, WRITES, MESSAGE, DIALOG_TEXT, BEZEL, SLEEPS = {}, nil, 0, nil, nil, nil, 0
-- Lightroom pauses (yields) the running task during catalog calls. Lua 5.1's plain pcall cannot pass a
-- pause through, so code must use LrTasks.pcall there; these mocks pause the same way.
local function pause()
  if coroutine.running() then coroutine.yield() end
end
-- LrTasks.pcall: like pcall, but the protected function may pause
local function taskPcall(f, ...)
  local co = coroutine.create(f)
  local res = { coroutine.resume(co, ...) }
  while true do
    if not res[1] then return false, res[2] end
    if coroutine.status(co) == 'dead' then return true, unpack(res, 2) end
    coroutine.yield()
    res = { coroutine.resume(co) }
  end
end
-- run f as a background task until it finishes; returns its results or raises its error
function runTask(f, ...)
  local co = coroutine.create(f)
  local res = { coroutine.resume(co, ...) }
  while res[1] and coroutine.status(co) ~= 'dead' do res = { coroutine.resume(co) } end
  if not res[1] then error(res[2], 0) end
  return unpack(res, 2)
end
local writing = false
local Keyword = {}
Keyword.__index = Keyword
function Keyword:getName() return self.name end
function Keyword:getParent() return self.parent end
local keywords = {}
local function makeKeyword(name, parent)
  local key = (parent and parent.name .. '/' or '') .. name
  if not keywords[key] then keywords[key] = setmetatable({ name = name, parent = parent }, Keyword) end
  return keywords[key]
end
local Photo = {}
Photo.__index = Photo
function Photo:getRawMetadata(key)
  if key == 'keywords' then return self.keywords end
  error('unexpected getRawMetadata ' .. key)
end
function Photo:setRawMetadata(key, value)
  assert(writing, 'setRawMetadata outside withWriteAccessDo')
  assert(key == 'rating', key)
  self.rating = value
end
function Photo:addKeyword(k)
  assert(writing and getmetatable(k) == Keyword)
  for _, x in ipairs(self.keywords) do if x == k then return end end
  table.insert(self.keywords, k)
end
function Photo:removeKeyword(k)
  assert(writing)
  for i, x in ipairs(self.keywords) do if x == k then table.remove(self.keywords, i) return end end
end
function addPhoto(t)
  local p = setmetatable({ path = t.path, fileName = t.fileName, preserved = t.preserved, time = t.time, rating = t.rating,
                          keywords = {}, localIdentifier = #PHOTOS + 101 }, Photo)
  if t.oldKeyword then table.insert(p.keywords, makeKeyword(t.oldKeyword, makeKeyword('PhotoSelect'))) end
  table.insert(PHOTOS, p)
end
function selectPhotos(indices)
  SELECTED = {}
  for _, i in ipairs(indices) do table.insert(SELECTED, PHOTOS[i]) end
end
function keywordNames(p)
  local out = {}
  for _, k in ipairs(p.keywords) do table.insert(out, (k.parent and k.parent.name .. '/' or '') .. k.name) end
  return out
end
local catalog = {}
function catalog:getTargetPhotos() return (SELECTED and #SELECTED > 0) and SELECTED or PHOTOS end
function catalog:getMultipleSelectedOrAllPhotos() return (SELECTED and #SELECTED > 1) and SELECTED or PHOTOS end
function catalog:findPhotoByPath(path)
  for _, p in ipairs(PHOTOS) do if p.path == path then return p end end
  return nil
end
function catalog:findPhotos(args)
  pause()
  local d = args.searchDesc
  SEARCHES = (SEARCHES or 0) + 1
  local out = {}
  if d.criteria == 'filename' then
    assert(d.operation == 'any' and d.value ~= '')
    for _, p in ipairs(PHOTOS) do
      for word in string.gmatch(d.value, '%S+') do
        if string.find(string.lower(p.fileName or ''), string.lower(word), 1, true) then table.insert(out, p) break end
      end
    end
    return out
  end
  assert(d.criteria == 'captureTime' and d.operation == 'in' and d.value and d.value2)
  if DATE_SEARCH_FAILS then error('unsupported search criteria') end
  for _, p in ipairs(PHOTOS) do
    local day = string.sub(p.time or '', 1, 10)
    if day >= d.value and day <= d.value2 then table.insert(out, p) end
  end
  return out
end
function catalog:getPhotoByLocalId(id)
  for _, p in ipairs(PHOTOS) do if p.localIdentifier == id and not p.removed then return p end end
  return nil
end
COLLECTIONS = {}
function catalog:createCollectionSet(name, parent, returnExisting)
  assert(writing, 'createCollectionSet outside withWriteAccessDo')
  assert(parent == nil and returnExisting == true)
  return { name = name }
end
function catalog:createSmartCollection(name, desc, parent, returnExisting)
  assert(writing, 'createSmartCollection outside withWriteAccessDo')
  assert(parent and parent.name == 'PhotoSelect' and returnExisting == true)
  assert(desc.combine == 'intersect' and #desc == 2 and desc[2].criteria == 'keywords' and desc[2].value == 'From PhotoSelect')
  COLLECTIONS[parent.name .. '/' .. name] = desc[1]
end
function catalog:batchGetRawMetadata(photos, keys)
  pause()
  local out = {}
  for _, p in ipairs(photos) do
    out[p] = { path = p.path, dateTimeOriginal = p.time, rating = p.rating }
  end
  return out
end
function catalog:batchGetFormattedMetadata(photos, keys)
  local out = {}
  for _, p in ipairs(photos) do out[p] = { fileName = p.fileName, preservedFileName = p.preserved } end
  return out
end
function catalog:createKeyword(name, synonyms, includeOnExport, parent, returnExisting)
  assert(writing, 'createKeyword outside withWriteAccessDo')
  assert(returnExisting == true and includeOnExport == false)
  return makeKeyword(name, parent)
end
function catalog:withWriteAccessDo(name, fn, opts)
  assert(type(name) == 'string' and opts.timeout)
  pause()
  WRITES = WRITES + 1
  writing = true
  fn()
  writing = false
end
local modules = {
  LrApplication = { activeCatalog = function() return catalog end },
  LrBinding = { makePropertyTable = function(context) return {} end },
  -- dateTimeOriginal is stored here as the formatted text already; the real SDK returns a number
  LrDate = { timeToUserFormat = function(t, fmt) assert(fmt == '%Y-%m-%d %H:%M:%S') return t end,
             currentTime = function() return NOW_UNIX - 978307200 end },
  LrDialogs = {
    message = function(title, text, kind) MESSAGE = text end,
    showBezel = function(text) BEZEL = text end,
    presentModalDialog = function(args)
      assert(args.title and args.actionVerb == 'Apply')
      DIALOG_TEXT = args.contents.items[1].title
      args.contents.bind_to_object.overwrite = OVERWRITE
      return ANSWER
    end,
  },
  LrFileUtils = {
    exists = function(path) return EXISTS(path) end,
    files = function(folder)
      local names = LIST_DIR(folder)
      local i = 0
      return function() i = i + 1 return names[i] end
    end,
    readFile = function(path) local f = assert(io.open(path, 'rb')) local t = f:read('*a') f:close() return t end,
    delete = function(path) os.remove(path) return true end,
  },
  LrFunctionContext = {
    callWithContext = function(name, fn)
      local failure
      local context = { addFailureHandler = function(self, h) failure = h end }
      local ok, err = taskPcall(fn, context)
      if not ok then if failure then failure(false, err) end error(err) end
    end,
  },
  LrPathUtils = {
    extension = function(path) return path:match('%.([^%./]+)$') or '' end,
    child = function(a, b) return a .. '/' .. b end,
    getStandardFilePath = function(kind) return '/Users/test' end,
  },
  LrTasks = {
    startAsyncTask = function(fn) runTask(fn) end,
    pcall = taskPcall,
    -- one pass of the background loop, then the plug-in is shut down
    sleep = function(s) SLEEPS = SLEEPS + 1 dofile(PLUGIN_DIR .. '/Shutdown.lua') end,
  },
  LrView = {
    bind = function(key) return { bind = key } end,
    osFactory = function()
      local f = {}
      function f:column(t) local items = {} for i, v in ipairs(t) do items[i] = v end t.items = items return t end
      function f:static_text(t) return t end
      function f:checkbox(t) return t end
      function f:control_spacing() return 8 end
      return f
    end,
  },
}
function import(name) return assert(modules[name], 'unknown SDK module ' .. name) end
'''


if __name__ == '__main__':
    unittest.main()
