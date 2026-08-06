#!/usr/bin/env bash
set -u

PATH=/bin:/sbin:/usr/bin:/usr/sbin:/usr/local/bin:/usr/local/sbin:/opt/homebrew/bin:/opt/homebrew/sbin:~/bin
export PATH

if [[ "$(id -u)" -ne 0 ]]; then
    echo "Error: You must be root to run this script" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
OS="$(uname -s)"

ignore_failure() {
    "$@" >/dev/null 2>&1 || true
}

remove_path() {
    local path="$1"
    if [[ -e "$path" || -L "$path" ]]; then
        rm -rf "$path"
    fi
}

# Stop the application first.  This is intentionally separate from protocol
# switching: uninstalling should not leave a sidecar or supervisor process
# holding files and ports after the project has been removed.
if command -v supervisorctl >/dev/null 2>&1; then
    ignore_failure supervisorctl stop v2raypi
fi

# Mieru is a native sidecar and has no systemd service in this project.  Kill
# the dedicated-user processes directly; the native RPC stop command can time
# out while leaving the daemon alive.
MIERU_USER="${MIERU_USER:-mieru}"
if [[ "$OS" == "Linux" ]] && id -u "$MIERU_USER" >/dev/null 2>&1; then
    ignore_failure pkill -KILL -u "$MIERU_USER" -x mieru
else
    for mieru_bin in /usr/local/bin/mieru /opt/homebrew/bin/mieru; do
        if [[ -x "$mieru_bin" ]]; then
            ignore_failure pkill -KILL -x mieru
        fi
    done
fi

if [[ "$OS" == "Linux" ]] && command -v systemctl >/dev/null 2>&1; then
    ignore_failure systemctl stop xray_iptable.service
    ignore_failure systemctl disable xray_iptable.service
    ignore_failure systemctl stop xray.service
    ignore_failure systemctl disable xray.service
fi

# Homebrew services are used by the macOS installer.  Ignore missing services
# and Homebrew errors so removal is also safe on Linux.
if [[ "$OS" == "Darwin" ]] && command -v brew >/dev/null 2>&1; then
    ignore_failure brew services stop xray
    ignore_failure brew services stop sing-box
fi

# Supervisor configuration and logs.
remove_path /etc/supervisor/conf.d/v2raypi.ini
if command -v supervisorctl >/dev/null 2>&1; then
    ignore_failure supervisorctl reread
fi
remove_path /var/log/v2raypi

# Xray and sidecar service files.
remove_path /etc/systemd/system/xray_iptable.service
remove_path /etc/systemd/system/xray.service
remove_path /etc/systemd/system/xray@.service
remove_path /etc/systemd/system/xray.service.d
remove_path /etc/systemd/system/xray@.service.d
remove_path /usr/local/bin/xray
remove_path /usr/local/bin/sing-box
remove_path /opt/homebrew/bin/xray
remove_path /opt/homebrew/bin/sing-box
remove_path /usr/local/etc/xray
remove_path /etc/sing-box
remove_path /opt/homebrew/etc/sing-box
remove_path /var/log/xray
remove_path /usr/local/share/xray

# Mieru is installed from the portable release script.  Remove both default
# locations used on Linux and macOS.  A custom MIERU_BIN installation is left
# untouched unless the caller explicitly exports that path for this script.
remove_path /usr/local/bin/mieru
remove_path /opt/homebrew/bin/mieru
if [[ -n "${MIERU_BIN:-}" && "$MIERU_BIN" == */* ]]; then
    remove_path "$MIERU_BIN"
fi

if [[ "$OS" == "Linux" ]] && id -u "$MIERU_USER" >/dev/null 2>&1; then
    MIERU_HOME="${MIERU_HOME:-/var/lib/$MIERU_USER}"
    ignore_failure userdel -r "$MIERU_USER"
    # userdel normally removes the home directory.  Remove the configured
    # default explicitly for systems where the account had a custom home.
    remove_path "$MIERU_HOME"
fi

if [[ "$OS" == "Linux" ]] && command -v systemctl >/dev/null 2>&1; then
    ignore_failure systemctl daemon-reload
    ignore_failure systemctl reset-failed
fi

# Remove the V2RayPi checkout, virtualenv and generated Mieru config.
remove_path "$PROJECT_DIR"

echo "remove success, please reboot device!"
