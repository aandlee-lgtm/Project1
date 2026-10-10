# PyInstaller spec for PhotoSelect.app (Apple silicon only). Run via scripts/build_mac.sh.
import os
from pathlib import Path

ROOT = Path(SPECPATH).parent
BUILD = ROOT / 'build'
VERSION = os.environ.get('PHOTOSELECT_VERSION', '1.10.0')
MIN_MACOS = os.environ.get('PHOTOSELECT_MIN_MACOS', '11.0')

a = Analysis(
    [str(ROOT / 'desktop.py')],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / 'static'), 'static'), (str(ROOT / 'lightroom'), 'lightroom'),
           (str(BUILD / 'THIRD_PARTY_NOTICES.txt'), '.')],
    hiddenimports=['webview.platforms.cocoa', 'waitress', 'rawpy', 'exifread'],
    excludes=['tkinter', '_tkinter', 'webview.platforms.qt', 'webview.platforms.gtk', 'webview.platforms.cef',
              'webview.platforms.winforms', 'webview.platforms.edgechromium', 'webview.platforms.mshtml',
              'webview.platforms.android', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'IPython', 'pytest',
              'matplotlib', 'scipy', 'pidng', 'playwright'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='PhotoSelect', console=False, debug=False,
          strip=False, upx=False, target_arch='arm64', argv_emulation=False,
          codesign_identity=os.environ.get('CODESIGN_IDENTITY') or None,
          entitlements_file=str(ROOT / 'packaging' / 'entitlements.plist') if os.environ.get('CODESIGN_IDENTITY') else None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='PhotoSelect')
app = BUNDLE(
    coll,
    name='PhotoSelect.app',
    icon=str(BUILD / 'PhotoSelect.icns'),
    bundle_identifier='io.github.aandlee-lgtm.photoselect',
    version=VERSION,
    info_plist={
        'CFBundleName': 'PhotoSelect',
        'CFBundleDisplayName': 'PhotoSelect',
        'CFBundleShortVersionString': VERSION,
        'CFBundleVersion': VERSION,
        'LSMinimumSystemVersion': MIN_MACOS,
        'LSArchitecturePriority': ['arm64'],
        'LSApplicationCategoryType': 'public.app-category.photography',
        'NSHighResolutionCapable': True,
        'NSRequiresAquaSystemAppearance': False,
        'NSHumanReadableCopyright': 'PhotoSelect. Third-party components under their own licences (see Help menu).',
        # Shown by macOS only if the user chooses a folder in a protected location.
        'NSRemovableVolumesUsageDescription': 'PhotoSelect reads photos from the folder you choose on this drive. Originals are never changed.',
        'NSNetworkVolumesUsageDescription': 'PhotoSelect reads photos from the folder you choose on this network volume. Originals are never changed.',
        'NSDesktopFolderUsageDescription': 'PhotoSelect reads photos from the Desktop folder you choose. Originals are never changed.',
        'NSDocumentsFolderUsageDescription': 'PhotoSelect reads photos from the Documents folder you choose. Originals are never changed.',
        'NSDownloadsFolderUsageDescription': 'PhotoSelect reads photos from the Downloads folder you choose. Originals are never changed.',
    },
)
