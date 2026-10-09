"""Write THIRD_PARTY_NOTICES.txt from the build environment's installed distributions."""
import sys
import sysconfig
from importlib import metadata
from pathlib import Path

BUNDLED = ['flask', 'werkzeug', 'jinja2', 'markupsafe', 'itsdangerous', 'click', 'blinker', 'waitress', 'numpy',
           'pillow', 'rawpy', 'exifread', 'pywebview', 'proxy_tools', 'bottle', 'typing_extensions', 'pyobjc-core',
           'pyobjc-framework-Cocoa', 'pyobjc-framework-Quartz', 'pyobjc-framework-WebKit',
           'pyobjc-framework-Security', 'pyobjc-framework-UniformTypeIdentifiers', 'pyinstaller']

HEADER = """PhotoSelect — third-party notices
==================================

PhotoSelect bundles the components below. Each is distributed under its own licence, reproduced
here from the installed package metadata at build time.

Notes on native libraries
-------------------------
* LibRaw (inside rawpy, rawpy/.dylibs) is used under the GNU LGPL 2.1 (LibRaw is dual-licensed
  LGPL-2.1 / CDDL-1.0). It is dynamically linked and can be replaced; source code is available
  from https://www.libraw.org/ and https://github.com/LibRaw/LibRaw. LibRaw is copyright
  LibRaw LLC and based on dcraw by Dave Coffin.
* rawpy also bundles Little CMS (MIT) and libjpeg-turbo (IJG / BSD-style).
* Pillow bundles libjpeg-turbo, libpng, libtiff, zlib, libwebp, lcms2, freetype, openjpeg,
  harfbuzz, brotli and others under their permissive licences (see the Pillow licence below).
* NumPy bundles OpenBLAS (BSD-3-Clause) and the GCC runtime libraries libgfortran/libquadmath
  (GPL-3.0 with the GCC Runtime Library Exception).
* The PyInstaller bootloader is GPL-2.0 with an exception that allows distribution with
  non-GPL programs.
* Python itself is distributed under the PSF License Agreement (reproduced at the end).
"""


def main(out):
    parts = [HEADER]
    for name in BUNDLED:
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            parts.append(f'\n\n######## {name}: NOT INSTALLED IN BUILD ENVIRONMENT ########\n')
            continue
        meta = dist.metadata
        lic = meta.get('License-Expression') or meta.get('License') or ''
        parts.append(f"\n\n{'#' * 78}\n{dist.metadata['Name']} {dist.version}\n"
                     f"Licence: {lic.splitlines()[0] if lic else 'see text'}\n"
                     f"Home: {meta.get('Home-page') or meta.get('Project-URL', '')}\n{'#' * 78}\n")
        texts = []
        for f in dist.files or []:
            n = f.name.upper()
            if any(n.startswith(p) for p in ('LICENSE', 'LICENCE', 'COPYING', 'NOTICE', 'AUTHORS')) or \
                    '/licenses/' in str(f).lower():
                try:
                    texts.append(f'--- {f} ---\n' + Path(f.locate()).read_text(errors='replace'))
                except OSError:
                    pass
        if not texts and lic and len(lic) > 40:
            texts.append(lic)
        parts.append('\n'.join(texts) or '(licence text not shipped in the package; see licence name above)')
    py_license = Path(sysconfig.get_paths()['stdlib']) / 'LICENSE.txt'
    if py_license.exists():
        parts.append(f"\n\n{'#' * 78}\nPython {sys.version.split()[0]}\n{'#' * 78}\n" + py_license.read_text())
    Path(out).write_text(''.join(parts), encoding='utf-8')
    print(f'wrote {out}')


if __name__ == '__main__':
    main(sys.argv[1])
