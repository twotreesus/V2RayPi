#!/bin/bash
set -eEuo pipefail

C_BLUE='\033[1;34m'
C_GREEN='\033[1;32m'
C_RED='\033[1;31m'
C_RESET='\033[0m'
CURRENT_STEP=""

print_start() { printf '%b▸ %s%b\n' "$C_BLUE" "$1" "$C_RESET"; }
print_ok() { printf '%b✔ %s%b\n' "$C_GREEN" "$1" "$C_RESET"; }
print_fail() { printf '%b✘ Failed: %s%b\n' "$C_RED" "$1" "$C_RESET" >&2; }

on_error() {
    local rc=$?
    trap - ERR
    if [[ -n "${CURRENT_STEP:-}" ]]; then
        print_fail "$CURRENT_STEP"
    fi
    exit "$rc"
}
trap on_error ERR

step() {
    local start_msg="$1"
    local done_msg="$2"
    shift 2
    CURRENT_STEP="$start_msg"
    print_start "$start_msg"
    "$@"
    print_ok "$done_msg"
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

step "Installing Homebrew packages" "Installed Homebrew packages" install_packages
step "Installing Python dependencies" "Installed Python dependencies" install_python_deps
step "Starting mihomo" "Started mihomo" brew services start mihomo
step "Installing GEO databases" "Installed GEO databases" install_geo_data

print_ok "Install finished"
