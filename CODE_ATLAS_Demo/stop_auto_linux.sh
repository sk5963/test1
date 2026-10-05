#!/usr/bin/env bash
set -eu
cd -- "$(dirname -- "$0")"
exec .venv/bin/python -m CODE_Controller.cli stop
