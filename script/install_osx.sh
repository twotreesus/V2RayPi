#!/bin/bash

brew update
brew install wget curl python3 mihomo ipinfo-cli

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$( cd "$SCRIPT_DIR/.." && pwd )"

# setup venv and install pip packages
VENV_DIR="$PROJECT_DIR/venv"
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"
pip install --upgrade pip setuptools wheel
pip install -r $SCRIPT_DIR/requirements.txt
deactivate

brew services start mihomo

# Download the GEO databases before the first node is applied, and persist the
# release version so GEO-based routing is enabled from the first configuration.
if ! (
    cd "$PROJECT_DIR"
    "$VENV_DIR/bin/python" - <<'PY'
from core.core_service import CoreService

CoreService.load()
CoreService.update_geo_data()
PY
); then
    echo "Failed to install GEO databases" >&2
    exit 1
fi
