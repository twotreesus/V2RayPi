#!/bin/bash
set -eEuo pipefail

C_GREEN='\033[1;32m'
C_RED='\033[1;31m'
C_RESET='\033[0m'
CURRENT_STEP=""

on_error() {
    local rc=$?
    trap - ERR
    if [[ -n "${CURRENT_STEP:-}" ]]; then
        printf '%b %s\n' "${C_RED}✘${C_RESET}" "$CURRENT_STEP" >&2
    fi
    exit "$rc"
}
trap on_error ERR

step() {
    CURRENT_STEP="$1"
    shift
    "$@"
    printf '%b %s\n' "${C_GREEN}✔${C_RESET}" "$CURRENT_STEP"
    CURRENT_STEP=""
}

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$( cd "$SCRIPT_DIR/.." && pwd )"
VENV_DIR="$PROJECT_DIR/venv"

install_packages() {
    brew update
    brew install wget curl python3 mihomo ipinfo-cli
}

install_python_deps() {
    python3 -m venv "$VENV_DIR"
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
    pip install --upgrade pip setuptools wheel
    pip install -r "$SCRIPT_DIR/requirements.txt"
    deactivate
}

install_geo_data() {
    # Download the GEO databases before the first node is applied, and persist
    # the release version so GEO-based routing is enabled from the first
    # configuration.
    cd "$PROJECT_DIR"
    "$VENV_DIR/bin/python" - <<'PY'
from core.core_service import CoreService

CoreService.load()
CoreService.update_geo_data()
PY
}

step "Installed Homebrew packages" install_packages
step "Installed Python dependencies" install_python_deps
step "Started mihomo" brew services start mihomo
step "Installed GEO databases" install_geo_data

printf '%b %s\n' "${C_GREEN}✔${C_RESET}" "Install finished"
