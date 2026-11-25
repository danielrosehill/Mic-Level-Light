#!/bin/sh
# Run by .github/workflows/release.yml
set -e
v=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' mic_level_light.py)
r=dist/root; rm -rf dist
install -Dm755 mic_level_light.py $r/usr/bin/mic-level-light
install -Dm644 mic-level-light.desktop $r/usr/share/applications/mic-level-light.desktop
install -Dm644 LICENSE $r/usr/share/doc/mic-level-light/copyright
mkdir -p $r/DEBIAN
cat > $r/DEBIAN/control <<C
Package: mic-level-light
Version: $v
Architecture: all
Maintainer: Daniel Rosehill <danielrosehill@users.noreply.github.com>
Depends: python3, python3-numpy, python3-pyqt6, pulseaudio-utils
Section: sound
Priority: optional
Homepage: https://github.com/danielrosehill/Mic-Level-Light
Description: One big light for the microphone level
 Shows CLIPPING, TOO LOUD, GOOD or TOO LOW for the chosen input. Read-only.
C
dpkg-deb --root-owner-group --build $r dist/mic-level-light_${v}_all.deb
