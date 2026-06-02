#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

arch="${ARCH:-x86_64}"
version="${VERSION:-0.1}"

if ! command -v pyinstaller >/dev/null 2>&1; then
    echo "pyinstaller is required" >&2
    exit 1
fi

appimagetool_bin="$(command -v appimagetool || true)"
if [[ -z "$appimagetool_bin" ]]; then
    if [[ -x tools/appimagetool ]]; then
        appimagetool_bin="tools/appimagetool"
    else
        echo "appimagetool is required to produce an AppImage" >&2
        echo "Download it from https://appimage.github.io/appimagetool/ and place it on PATH." >&2
        exit 1
    fi
fi

rm -rf build dist AppDir
pyinstaller filmpad.spec

mkdir -p AppDir/usr/bin
mkdir -p AppDir/usr/share/applications
mkdir -p AppDir/usr/share/icons/hicolor/scalable/apps
mkdir -p AppDir/usr/share/icons/hicolor/256x256/apps

icon_png="assets/filmpad-icon.png"
if [[ ! -f "$icon_png" ]]; then
    if ! command -v convert >/dev/null 2>&1; then
        echo "Missing $icon_png and ImageMagick 'convert' is not available for SVG fallback." >&2
        exit 1
    fi
    if [[ ! -f assets/filmpad-icon.svg ]]; then
        echo "Missing both assets/filmpad-icon.png and assets/filmpad-icon.svg" >&2
        exit 1
    fi
    icon_png="build/filmpad-icon.png"
    convert assets/filmpad-icon.svg -resize 256x256 "$icon_png"
fi

install -m 0755 dist/filmpad AppDir/usr/bin/filmpad
install -m 0644 packaging/filmpad.desktop AppDir/usr/share/applications/filmpad.desktop
install -m 0644 assets/filmpad-icon.svg AppDir/usr/share/icons/hicolor/scalable/apps/filmpad.svg
install -m 0644 "$icon_png" AppDir/usr/share/icons/hicolor/256x256/apps/filmpad.png
install -m 0644 packaging/filmpad.desktop AppDir/filmpad.desktop
install -m 0644 assets/filmpad-icon.svg AppDir/filmpad.svg
install -m 0644 "$icon_png" AppDir/filmpad.png
cp "$icon_png" AppDir/.DirIcon
cat > AppDir/AppRun <<'EOF'
#!/usr/bin/env bash
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/filmpad" "$@"
EOF
chmod +x AppDir/AppRun

ARCH="$arch" "$appimagetool_bin" AppDir "FilmPad-v${version}-${arch}.AppImage"

echo "Built FilmPad-v${version}-${arch}.AppImage"
