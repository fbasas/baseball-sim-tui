#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -x venv/bin/python ]]; then
    echo "venv not found — creating one and installing deps..."
    python3 -m venv venv
    venv/bin/pip install -q -r requirements.txt
fi

if [[ ! -f data/lahman.sqlite ]]; then
    echo "data/lahman.sqlite missing — run: venv/bin/python scripts/build_lahman_db.py"
    exit 1
fi

exec venv/bin/python -m src.tui.app "$@"
