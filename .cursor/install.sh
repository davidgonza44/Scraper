#!/usr/bin/env bash
# Idempotent dependency setup for the BERA Price Tracker Cloud Agent environment.
set -euo pipefail

# The default image ships Python 3.12 but not the venv module, which is a stable
# system dependency. Install it once (a no-op when already present).
if ! python3 -c "import ensurepip" >/dev/null 2>&1; then
    sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3.12-venv
fi

# Create (or reuse) the project virtual environment.
if [ ! -x ".venv/bin/python" ]; then
    python3 -m venv .venv
fi

.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[dev]"
