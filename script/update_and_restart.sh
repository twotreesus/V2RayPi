#!/bin/bash

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$( cd "$SCRIPT_DIR/.." && pwd )"

# Change to project directory
cd "$PROJECT_DIR"

# Pull latest code
git pull

# Update venv dependencies
VENV_DIR="$PROJECT_DIR/venv"
if [ -d "$VENV_DIR" ]; then
    source "$VENV_DIR/bin/activate"
    pip install -r "$SCRIPT_DIR/requirements.txt"
    deactivate
fi

# Restart service via supervisor
SUPERVISOR_CONFIG="/etc/supervisor/supervisord.conf"
supervisorctl -c "$SUPERVISOR_CONFIG" restart v2raypi
