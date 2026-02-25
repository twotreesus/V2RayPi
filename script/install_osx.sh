#!/bin/bash

brew update
brew install wget curl python3 xray

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

mkdir -p ~/Library/Logs/xray/
brew services start xray