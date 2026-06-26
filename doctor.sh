#!/usr/bin/env bash
set -euo pipefail

models=("mistral:7b" "llama3.1:8b" "qwen2.5-coder:7b")
missing=0

ok() {
  printf 'PASS  %s\n' "$1"
}

warn() {
  printf 'FAIL  %s\n' "$1"
  missing=1
}

note() {
  printf 'INFO  %s\n' "$1"
}

print_linux_install_hint() {
  local pkg="$1"
  if command -v apt-get >/dev/null 2>&1; then
    printf '      sudo apt-get update && sudo apt-get install -y %s\n' "$pkg"
    return
  fi
  if command -v dnf >/dev/null 2>&1; then
    printf '      sudo dnf install -y %s\n' "$pkg"
    return
  fi
  if command -v pacman >/dev/null 2>&1; then
    printf '      sudo pacman -Sy --noconfirm %s\n' "$pkg"
    return
  fi
  if command -v zypper >/dev/null 2>&1; then
    printf '      sudo zypper install -y %s\n' "$pkg"
    return
  fi
  printf '      Install package manually: %s\n' "$pkg"
}

printf 'FilmPad doctor (v0.4)\n\n'

if command -v python3 >/dev/null 2>&1; then
  ok "python3 found ($(python3 --version 2>/dev/null || true))"
else
  warn "python3 not found"
  print_linux_install_hint "python3"
fi

if python3 - <<'PY' >/dev/null 2>&1
import tkinter
PY
then
  ok "tkinter import works"
else
  warn "tkinter missing for python3"
  print_linux_install_hint "python3-tk"
fi

if command -v ollama >/dev/null 2>&1; then
  ok "ollama found"
else
  warn "ollama not found (required for AI features only)"
  note "     Install from: https://ollama.com/download"
fi

if command -v ollama >/dev/null 2>&1; then
  if ollama list >/tmp/filmpad-doctor-ollama-list.txt 2>/dev/null; then
    ok "ollama service responding"
    for m in "${models[@]}"; do
      if grep -q "^${m}[[:space:]]" /tmp/filmpad-doctor-ollama-list.txt; then
        ok "model present: ${m}"
      else
        warn "model missing: ${m}"
        note "     Run: ollama pull ${m}"
      fi
    done
  else
    warn "ollama installed but not responding"
    note "     Try: systemctl start ollama  (or: ollama serve)"
  fi
  rm -f /tmp/filmpad-doctor-ollama-list.txt
fi

if command -v spd-say >/dev/null 2>&1; then
  ok "spd-say found (read-aloud available)"
else
  warn "spd-say missing (read-aloud optional)"
  print_linux_install_hint "speech-dispatcher"
fi

if command -v aspell >/dev/null 2>&1 || command -v hunspell >/dev/null 2>&1; then
  ok "spellcheck tool found (aspell/hunspell)"
else
  warn "spellcheck tool missing (optional)"
  print_linux_install_hint "aspell"
fi

printf '\nSummary: '
if [[ $missing -eq 0 ]]; then
  printf 'all checks passed.\n'
  exit 0
fi
printf 'one or more checks failed.\n'
exit 1
