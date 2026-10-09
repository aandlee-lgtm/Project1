#!/bin/bash
# Build PhotoSelect.app and PhotoSelect-AppleSilicon.dmg on an Apple silicon Mac.
#
# Requirements on the BUILD machine only (end users need nothing): native arm64 CPython 3.12 from
# python.org (default path below, override with PYTHON=...), Xcode command line tools, internet
# access to PyPI. Output: dist/PhotoSelect.app and dist/PhotoSelect-AppleSilicon.dmg.
#
# Signing: ad-hoc by default (fine for personal use on the Mac that builds it). Set
# CODESIGN_IDENTITY="Developer ID Application: Name (TEAMID)" to sign with the hardened runtime, and
# additionally NOTARY_PROFILE=<notarytool keychain profile> to notarise and staple the DMG.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
[ "$(uname -s)" = Darwin ] && [ "$(uname -m)" = arm64 ] || { echo 'Build on an Apple silicon (arm64) Mac.' >&2; exit 1; }
PYTHON=${PYTHON:-/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12}
"$PYTHON" -c 'import sys,platform; assert sys.version_info[:2]==(3,12), sys.version; assert platform.machine()=="arm64"' \
  || { echo "Need native arm64 CPython 3.12 at $PYTHON (python.org installer)." >&2; exit 1; }
VERSION=${PHOTOSELECT_VERSION:-1.5.0}
export PHOTOSELECT_VERSION=$VERSION
BUILD="$ROOT/build"
DIST="$ROOT/dist"
APP="$DIST/PhotoSelect.app"
DMG="$DIST/PhotoSelect-AppleSilicon.dmg"
echo "== host: macOS $(sw_vers -productVersion) $(uname -m); python $("$PYTHON" -V 2>&1)"

rm -rf "$BUILD" "$DIST"
mkdir -p "$BUILD/wheels" "$DIST"

echo '== dependencies (exact pins, binary wheels for macOS 11+ arm64)'
"$PYTHON" -m venv "$BUILD/venv"
VPY="$BUILD/venv/bin/python"
PINS=$(grep -hv -e '^\s*#' -e '^\s*$' -e proxy_tools requirements-mac.txt requirements-build.txt)
# Downloading for the macosx_11_0_arm64 platform tag stops pip choosing NumPy's macOS-14-only wheel.
"$VPY" -m pip download --quiet --only-binary=:all: --no-deps --platform macosx_11_0_arm64 --python-version 3.12 \
  --implementation cp --abi cp312 -d "$BUILD/wheels" $PINS
"$VPY" -m pip download --quiet --no-deps --no-binary=:all: -d "$BUILD/wheels" proxy_tools==0.1.0
"$VPY" -m pip install --quiet --no-index --find-links "$BUILD/wheels" -r requirements-mac.txt -r requirements-build.txt
"$VPY" -m pip freeze > "$BUILD/installed-packages.txt"
"$VPY" -c 'import rawpy, numpy, PIL, webview; print("rawpy", rawpy.__version__, "LibRaw", ".".join(map(str, rawpy.libraw_version)), "numpy", numpy.__version__, "Pillow", PIL.__version__)'

echo '== unit tests (source)'
(cd tests && "$VPY" -W ignore -m unittest -v 2>&1 | tail -n 40)

echo '== licences and icon'
"$VPY" packaging/collect_notices.py "$BUILD/THIRD_PARTY_NOTICES.txt"
if grep -q 'NOT INSTALLED' "$BUILD/THIRD_PARTY_NOTICES.txt"; then echo 'Missing licence notices' >&2; exit 1; fi
"$VPY" packaging/make_icon.py "$BUILD/icon-1024.png"
ICONSET="$BUILD/PhotoSelect.iconset"
mkdir -p "$ICONSET"
for s in 16 32 128 256 512; do
  sips -z $s $s "$BUILD/icon-1024.png" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  sips -z $((s*2)) $((s*2)) "$BUILD/icon-1024.png" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$BUILD/PhotoSelect.icns"

echo '== PyInstaller'
"$VPY" -m PyInstaller --clean --noconfirm --log-level WARN --distpath "$DIST" --workpath "$BUILD/pyinstaller" \
  packaging/PhotoSelect.spec
rm -rf "$DIST/PhotoSelect"   # the intermediate COLLECT folder; the .app is the product

echo '== verify Mach-O binaries (arm64 only, no external libraries)'
"$VPY" scripts/verify_bundle.py "$APP" --thin --report "$BUILD/bundle-report.json"
MIN_MACOS=$("$VPY" -c 'import json,sys; v=json.load(open(sys.argv[1]))["min_macos"]; print(v if tuple(map(int,v.split(".")))>=(11,0) else "11.0")' "$BUILD/bundle-report.json")
/usr/libexec/PlistBuddy -c "Set :LSMinimumSystemVersion $MIN_MACOS" "$APP/Contents/Info.plist"
echo "minimum macOS required by bundled binaries: $MIN_MACOS"
echo "$MIN_MACOS" > "$BUILD/min-macos.txt"

echo '== code signing'
if [ -n "${CODESIGN_IDENTITY:-}" ]; then
  # Inside-out: every Mach-O, then the bundle, hardened runtime + secure timestamp.
  find "$APP/Contents" -type f -print0 | while IFS= read -r -d '' f; do
    if file -b "$f" | grep -q 'Mach-O'; then
      codesign --force --timestamp --options runtime --sign "$CODESIGN_IDENTITY" "$f"
    fi
  done
  codesign --force --timestamp --options runtime --entitlements packaging/entitlements.plist \
    --sign "$CODESIGN_IDENTITY" "$APP"
else
  codesign --force --deep --sign - "$APP"
fi
codesign --verify --deep --strict "$APP" && echo "signature verified: $APP"
codesign -dv "$APP" 2>&1 | grep -E 'Signature|TeamIdentifier|flags' || true

echo '== disk image'
STAGE="$BUILD/dmg"
mkdir -p "$STAGE"
ditto "$APP" "$STAGE/PhotoSelect.app"
ln -s /Applications "$STAGE/Applications"
hdiutil create -quiet -volname PhotoSelect -srcfolder "$STAGE" -fs HFS+ -format UDZO -imagekey zlib-level=9 -ov "$DMG"
hdiutil verify -quiet "$DMG"
if [ -n "${CODESIGN_IDENTITY:-}" ]; then
  codesign --force --timestamp --sign "$CODESIGN_IDENTITY" "$DMG"
  if [ -n "${NOTARY_PROFILE:-}" ]; then
    xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_PROFILE" --wait
    xcrun stapler staple "$DMG"
    xcrun stapler validate "$DMG"
  fi
fi
(cd "$DIST" && shasum -a 256 "$(basename "$DMG")" > "$(basename "$DMG").sha256")
du -sh "$APP" "$DMG"
echo "Built $DMG"
