# Installing PhotoSelect

**Requirements:** a Mac with Apple silicon (M1, M2, M3, M4 or later). The app declares
**macOS 11.0** as its minimum, because that is the highest minimum required by any binary
inside it (measured at build time). It has been **tested on macOS 14.8 (Sonoma) and 15.7
(Sequoia)**. macOS 11–13 and 26 have not been tested. The interface needs the system WebKit
from Safari 15.4 or later, which current macOS versions include. Intel Macs are not supported. Nothing else is needed: no Python, Terminal, Homebrew or
downloads after installation, and it works offline.

## Install

1. Open `PhotoSelect-AppleSilicon.dmg`.
2. Drag **PhotoSelect** onto the **Applications** shortcut in the window.
3. Eject the PhotoSelect disk image (Finder sidebar ⏏).
4. Open PhotoSelect from Applications or Launchpad.

## The first time you open it

This build is **ad-hoc signed, not notarised by Apple** (no Apple Developer ID was available).
What happens depends on how the DMG reached your Mac:

* **Built on your own Mac** with `scripts/build_mac.sh`: it opens normally.
* **Downloaded** (for example the GitHub Actions artifact, a browser download, AirDrop or
  email): macOS marks the file as downloaded, and Gatekeeper will say Apple could not verify
  that PhotoSelect is free of malware. Opening it then needs the standard override, once:
  1. Try to open PhotoSelect and click **Done** (or **OK**) in the warning.
  2. Open **System Settings → Privacy & Security** and scroll to **Security**. You'll see
     "PhotoSelect was blocked…". Click **Open Anyway** and confirm with your password or
     Touch ID.

  Only do this for a build you trust, such as one produced from your own repository's
  workflow. To avoid the warning entirely, a Developer ID certificate and notarisation are
  needed (see README → Building).

PhotoSelect never asks you to disable Gatekeeper or run Terminal commands.

## Access to your photos

PhotoSelect reads only folders you choose with **Choose folder**. For external drives, or
Desktop/Documents/Downloads, macOS may ask whether PhotoSelect may access files there: click
**Allow**. If you denied it earlier, enable PhotoSelect in **System Settings → Privacy &
Security → Files and Folders**. Then choose the folder again.

## Uninstall

Drag PhotoSelect from Applications to the Bin. To also remove your saved decisions, cache and
logs, delete these folders:

* `~/Library/Application Support/PhotoSelect`
* `~/Library/Caches/PhotoSelect`
* `~/Library/Logs/PhotoSelect`
