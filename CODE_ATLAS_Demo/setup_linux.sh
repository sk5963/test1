#!/usr/bin/env bash
set -eu
cd -- "$(dirname -- "$0")"
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cd CODE_UI
npm ci --ignore-scripts
node node_modules/electron/install.js
