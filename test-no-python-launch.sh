#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
export FILMPAD_TEST_NO_PYTHON=1
exec ./start-filmpad.sh
