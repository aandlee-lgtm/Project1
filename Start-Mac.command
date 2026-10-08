#!/bin/bash
# Finder-safe launcher for native Apple silicon Python, macOS 11 or newer.
cd "$(dirname "$0")" || exit 1
fail() {
  printf '\n%s\n' "$1"
  read -r -p 'Press Return to close this window.'
  exit 1
}
[ "$(uname -s)" = Darwin ] || fail 'This launcher is for macOS.'
mac_version=$(/usr/bin/sw_vers -productVersion)
mac_major=${mac_version%%.*}
[ "$mac_major" -ge 11 ] || fail 'PhotoSelect requires macOS 11 or newer.'
# Look in official Python installer locations first, avoiding Apple's developer Python.
photo_python=''
for candidate in \
  /Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12 \
  /Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13 \
  /Library/Frameworks/Python.framework/Versions/3.14/bin/python3.14 \
  /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.14 \
  /usr/local/bin/python3.12 /usr/local/bin/python3.13 /usr/local/bin/python3.14 \
  python3; do
  if "$candidate" -c 'import sys,platform; assert (3,12)<=sys.version_info[:2]<=(3,14); assert platform.machine()=="arm64"' >/dev/null 2>&1; then
    photo_python="$candidate"
    break
  fi
done
if [ -z "$photo_python" ]; then
  /usr/bin/open 'https://www.python.org/downloads/macos/'
  fail 'Install Python 3.12, 3.13 or 3.14 using the macOS 64-bit universal2 installer, then run this again. This package targets Apple silicon (M-series) Macs. Python must run natively, not under Rosetta.'
fi
printf 'PhotoSelect · macOS %s · Apple silicon\n' "$mac_version"
# Keep this environment separate from older app packages and other Python installs.
if [ ! -x .venv-mac/bin/python ] || ! .venv-mac/bin/python -c 'import sys,platform; assert (3,12)<=sys.version_info[:2]<=(3,14); assert platform.machine()=="arm64"' >/dev/null 2>&1; then
  "$photo_python" -m venv --clear .venv-mac || fail 'Could not create the app environment. Move this folder to your home folder and retry.'
fi
if ! .venv-mac/bin/python -c 'import flask,numpy,PIL,rawpy,exifread; assert rawpy.__version__=="0.27.1"' >/dev/null 2>&1; then
  printf '\nFirst-time setup: downloading the photo decoder and app dependencies…\n'
  .venv-mac/bin/python -m pip install --upgrade pip || fail 'Setup failed. Check your internet connection and retry.'
  .venv-mac/bin/python -m pip install --only-binary=:all: -r requirements-mac.txt || fail 'Could not install compatible Mac packages. Check your internet connection. No compiler or Xcode should be needed.'
fi
.venv-mac/bin/python -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",8765)); s.close()' 2>/dev/null || fail 'Port 8765 is in use. Close the earlier PhotoSelect Terminal window, then retry.'
printf '\nKeep this window open while reviewing. Press Control+C here to stop.\n'
.venv-mac/bin/python app.py
result=$?
[ "$result" -eq 0 ] || fail 'PhotoSelect stopped with an error. The details are above.'
