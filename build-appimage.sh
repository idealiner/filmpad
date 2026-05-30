#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

arch="${ARCH:-x86_64}"

if ! command -v pyinstaller >/dev/null 2>&1; then
    echo "pyinstaller is required" >&2
    exit 1
fi

if ! command -v appimagetool >/dev/null 2>&1; then
    echo "appimagetool is required to produce an AppImage" >&2
    echo "Download it from https://appimage.github.io/appimagetool/ and place it on PATH." >&2
    exit 1
fi

if ! command -v convert >/dev/null 2>&1; then
    echo "ImageMagick 'convert' is required to generate PNG icon assets" >&2
    exit 1
fi

rm -rf build dist AppDir
pyinstaller basicpad.spec

mkdir -p AppDir/usr/bin
mkdir -p AppDir/usr/share/applications
mkdir -p AppDir/usr/share/icons/hicolor/scalable/apps
mkdir -p AppDir/usr/share/icons/hicolor/256x256/apps

icon_png="build/basicpad-icon.png"
convert assets/basicpad-icon.svg -resize 256x256 "$icon_png"

install -m 0755 dist/basicpad AppDir/usr/bin/basicpad
install -m 0644 packaging/basicpad.desktop AppDir/usr/share/applications/basicpad.desktop
install -m 0644 assets/basicpad-icon.svg AppDir/usr/share/icons/hicolor/scalable/apps/basicpad.svg
install -m 0644 "$icon_png" AppDir/usr/share/icons/hicolor/256x256/apps/basicpad.png
install -m 0644 packaging/basicpad.desktop AppDir/basicpad.desktop
install -m 0644 assets/basicpad-icon.svg AppDir/basicpad.svg
install -m 0644 "$icon_png" AppDir/basicpad.png
cp "$icon_png" AppDir/.DirIcon
cat > AppDir/AppRun <<'EOF'
#!/usr/bin/env bash
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/basicpad" "$@"
EOF
chmod +x AppDir/AppRun

ARCH="$arch" appimagetool AppDir "BasicPad-${arch}.AppImage"

echo "Built BasicPad-${arch}.AppImage"
