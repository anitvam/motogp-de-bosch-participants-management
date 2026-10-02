#!/usr/bin/env bash
# Launch the MotoGP de Bosch manager (Linux / macOS).
# On first run, creates a virtualenv in .venv and installs the package (requires internet once).
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "First run: installing dependencies (internet connection needed only this time)..."
  python3 -m venv .venv
  .venv/bin/pip install -q -e .
fi

exec .venv/bin/streamlit run src/motogp_bosch/app.py \
  --server.headless false \
  --browser.gatherUsageStats false
