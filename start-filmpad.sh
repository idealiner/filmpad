#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

show_message() {
	local title="$1"
	local text="$2"
	if [[ -n "${DISPLAY:-}" || -n "${WAYLAND_DISPLAY:-}" ]]; then
		if command -v zenity >/dev/null 2>&1; then
			zenity --error --title="$title" --width=520 --text="$text" >/dev/null 2>&1 || true
			return
		fi
		if command -v kdialog >/dev/null 2>&1; then
			kdialog --error "$text" --title "$title" >/dev/null 2>&1 || true
			return
		fi
		if command -v xmessage >/dev/null 2>&1; then
			xmessage -center "$title\n\n$text" >/dev/null 2>&1 || true
			return
		fi
	fi
	printf '%s\n\n%s\n' "$title" "$text" >&2
}

python_install_hint() {
	if command -v apt-get >/dev/null 2>&1; then
		printf '%s\n' "sudo apt-get update && sudo apt-get install -y python3 python3-tk"
		return
	fi
	if command -v dnf >/dev/null 2>&1; then
		printf '%s\n' "sudo dnf install -y python3 python3-tkinter"
		return
	fi
	if command -v pacman >/dev/null 2>&1; then
		printf '%s\n' "sudo pacman -Sy --noconfirm python tk"
		return
	fi
	if command -v zypper >/dev/null 2>&1; then
		printf '%s\n' "sudo zypper install -y python3 python3-tk"
		return
	fi
	printf '%s\n' "Install Python 3 and Tkinter using your distro package manager."
}

pick_appimage() {
	local candidates=()
	shopt -s nullglob
	candidates=(FilmPad-v*-x86_64.AppImage)
	shopt -u nullglob
	if [[ ${#candidates[@]} -gt 0 ]]; then
		printf '%s\n' "${candidates[@]}" | sort -V | tail -n 1
		return 0
	fi
	if [[ -f FilmPad-x86_64.AppImage ]]; then
		printf '%s\n' "FilmPad-x86_64.AppImage"
		return 0
	fi
	return 1
}

run_appimage_with_fallback() {
	local appimage="$1"
	shift
	local log_file
	log_file="$(mktemp -t filmpad-appimage-XXXXXX.log)"

	set +e
	"./$appimage" "$@" >"$log_file" 2>&1
	local rc=$?
	set -e

	if [[ $rc -eq 0 ]]; then
		rm -f "$log_file"
		return 0
	fi

	if grep -qiE "cannot mount appimage|squashfs|fuse" "$log_file"; then
		echo "AppImage mount failed. Retrying with APPIMAGE_EXTRACT_AND_RUN=1..."
		APPIMAGE_EXTRACT_AND_RUN=1 "./$appimage" "$@"
		rc=$?
	else
		cat "$log_file" >&2
	fi

	if [[ $rc -ne 0 ]]; then
		local details
		details="$(tail -n 40 "$log_file" 2>/dev/null || true)"
		if [[ -z "$details" ]]; then
			details="No launcher output was captured."
		fi
		show_message \
			"FilmPad failed to launch" \
			"Tried to launch $appimage but it exited with code $rc.\n\nLast output:\n$details\n\nTip: install FUSE support or run:\nAPPIMAGE_EXTRACT_AND_RUN=1 ./$appimage"
	fi

	rm -f "$log_file"
	return $rc
}

run_dist_binary() {
	local log_file
	log_file="$(mktemp -t filmpad-dist-XXXXXX.log)"
	set +e
	./dist/filmpad "$@" >"$log_file" 2>&1
	local rc=$?
	set -e
	if [[ $rc -ne 0 ]]; then
		local details
		details="$(tail -n 40 "$log_file" 2>/dev/null || true)"
		show_message \
			"FilmPad dist launch failed" \
			"dist/filmpad exited with code $rc.\n\nLast output:\n$details"
	fi
	rm -f "$log_file"
	return $rc
}

run_source_fallback() {
	local log_file
	log_file="$(mktemp -t filmpad-source-XXXXXX.log)"
	set +e
	python3 ./filmpad.py "$@" >"$log_file" 2>&1
	local rc=$?
	set -e
	if [[ $rc -ne 0 ]]; then
		local details
		details="$(tail -n 60 "$log_file" 2>/dev/null || true)"
		show_message \
			"FilmPad source launch failed" \
			"python3 filmpad.py exited with code $rc.\n\nLast output:\n$details\n\nTip: install tkinter with:\nsudo apt-get install -y python3-tk"
	fi
	rm -f "$log_file"
	return $rc
}

if [[ "${FILMPAD_TEST_NO_PYTHON:-0}" == "1" ]] || ! command -v python3 >/dev/null 2>&1; then
	show_message \
		"FilmPad dependency missing" \
		"Python 3 is required and should be installed first.\n\nInstall command:\n$(python_install_hint)\n\nTest mode: unset FILMPAD_TEST_NO_PYTHON to restore normal detection."
	exit 1
fi

if appimage="$(pick_appimage)"; then
	chmod +x "$appimage"
	if run_appimage_with_fallback "$appimage" "$@"; then
		exit 0
	fi
fi

if [[ -x ./dist/filmpad ]]; then
	if run_dist_binary "$@"; then
		exit 0
	fi
fi

if [[ -f ./filmpad.py ]] && command -v python3 >/dev/null 2>&1; then
	run_source_fallback "$@"
	exit $?
fi

show_message \
	"FilmPad not found" \
	"No runnable FilmPad binary found in this folder.\n\nExpected one of:\n- FilmPad-vX.Y-x86_64.AppImage\n- FilmPad-x86_64.AppImage\n- ./dist/filmpad"
exit 1
