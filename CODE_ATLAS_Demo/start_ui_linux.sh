#!/usr/bin/env bash
set -eu
cd -- "$(dirname -- "$0")"
.venv/bin/python -m CODE_Controller.cli demo
cd CODE_UI
exec npm start
