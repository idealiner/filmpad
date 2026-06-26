#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

arch="${ARCH:-x86_64}"
version="${VERSION:-0.3}"

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
for size in 16x16 22x22 24x24 32x32 48x48 64x64 128x128 256x256 512x512 scalable; do
    mkdir -p "AppDir/usr/share/icons/hicolor/$size/apps"
done

icon_src="assets/filmpad-icon.png"

# Generate any missing sized icons
for s in 16 22 24 32 48 64 128 256 512; do
    f="assets/filmpad-icon-${s}.png"
    if [[ ! -f "$f" ]] && command -v convert >/dev/null 2>&1; then
        convert "$icon_src" -resize "${s}x${s}" -quality 100 "$f"
    fi
done

icon_256="assets/filmpad-icon-256.png"
[[ ! -f "$icon_256" ]] && icon_256="$icon_src"

install -m 0755 dist/filmpad AppDir/usr/bin/filmpad
install -m 0644 packaging/filmpad.desktop AppDir/usr/share/applications/filmpad.desktop
install -m 0644 assets/filmpad-icon.svg AppDir/usr/share/icons/hicolor/scalable/apps/filmpad.svg
for s in 16 22 24 32 48 64 128 256 512; do
    f="assets/filmpad-icon-${s}.png"
    [[ -f "$f" ]] && install -m 0644 "$f" "AppDir/usr/share/icons/hicolor/${s}x${s}/apps/filmpad.png"
done
install -m 0644 packaging/filmpad.desktop AppDir/filmpad.desktop
install -m 0644 assets/filmpad-icon.svg AppDir/filmpad.svg
install -m 0644 "$icon_256" AppDir/filmpad.png
cp "$icon_256" AppDir/.DirIcon
cat > AppDir/AppRun <<'EOF'
#!/usr/bin/env bash
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/filmpad" "$@"
EOF
chmod +x AppDir/AppRun

ARCH="$arch" "$appimagetool_bin" AppDir "FilmPad-v${version}-${arch}.AppImage"

echo "Built FilmPad-v${version}-${arch}.AppImage"
