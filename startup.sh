#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
echo "Starting PIHU MUSIC"
exec python3 main.py
