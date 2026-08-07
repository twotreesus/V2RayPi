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

# Stop the application first, so supervisor does not restart it while the rest
# of the uninstall runs.
if command -v supervisorctl >/dev/null 2>&1; then
    ignore_failure supervisorctl stop v2raypi
fi

if [[ "$OS" == "Linux" ]] && command -v systemctl >/dev/null 2>&1; then
    ignore_failure systemctl stop mihomo_iptable.service
    ignore_failure systemctl disable mihomo_iptable.service
    ignore_failure systemctl stop mihomo.service
    ignore_failure systemctl disable mihomo.service
fi

# Homebrew services are used by the macOS installer.  Ignore missing services
# and Homebrew errors so removal is also safe on Linux.
if [[ "$OS" == "Darwin" ]] && command -v brew >/dev/null 2>&1; then
    ignore_failure brew services stop mihomo
fi

# Supervisor configuration and logs.
remove_path /etc/supervisor/conf.d/v2raypi.ini
if command -v supervisorctl >/dev/null 2>&1; then
    ignore_failure supervisorctl reread
fi
remove_path /var/log/v2raypi

# mihomo service files, binary, config and logs.
remove_path /etc/systemd/system/mihomo_iptable.service
remove_path /etc/systemd/system/mihomo.service
remove_path /usr/local/bin/mihomo
remove_path /opt/homebrew/bin/mihomo
remove_path /etc/mihomo
remove_path /opt/homebrew/etc/mihomo
remove_path /usr/local/etc/mihomo
remove_path /var/log/mihomo
if [[ -n "${MIHOMO_BIN:-}" && "$MIHOMO_BIN" == */* ]]; then
    remove_path "$MIHOMO_BIN"
fi

# Leftovers from installations that predate the move to mihomo.  Uninstalling
# has to leave nothing behind on those devices either, so these are cleaned up
# unconditionally rather than detected.
if [[ "$OS" == "Linux" ]] && command -v systemctl >/dev/null 2>&1; then
    ignore_failure systemctl stop xray_iptable.service
    ignore_failure systemctl disable xray_iptable.service
    ignore_failure systemctl stop xray.service
    ignore_failure systemctl disable xray.service
    ignore_failure systemctl stop sing-box.service
    ignore_failure systemctl disable sing-box.service
fi
if [[ "$OS" == "Darwin" ]] && command -v brew >/dev/null 2>&1; then
    ignore_failure brew services stop xray
    ignore_failure brew services stop sing-box
fi
ignore_failure pkill -KILL -x mieru
for legacy in \
    /etc/systemd/system/xray_iptable.service \
    /etc/systemd/system/xray.service \
    /etc/systemd/system/xray@.service \
    /etc/systemd/system/xray.service.d \
    /etc/systemd/system/xray@.service.d \
    /usr/local/bin/xray /opt/homebrew/bin/xray \
    /usr/local/bin/sing-box /opt/homebrew/bin/sing-box \
    /usr/local/bin/mieru /opt/homebrew/bin/mieru \
    /usr/local/etc/xray /var/log/xray /usr/local/share/xray \
    /etc/sing-box /opt/homebrew/etc/sing-box; do
    remove_path "$legacy"
done
LEGACY_MIERU_USER="${MIERU_USER:-mieru}"
if [[ "$OS" == "Linux" ]] && id -u "$LEGACY_MIERU_USER" >/dev/null 2>&1; then
    ignore_failure userdel -r "$LEGACY_MIERU_USER"
    remove_path "${MIERU_HOME:-/var/lib/$LEGACY_MIERU_USER}"
fi

if [[ "$OS" == "Linux" ]] && command -v systemctl >/dev/null 2>&1; then
    ignore_failure systemctl daemon-reload
    ignore_failure systemctl reset-failed
fi

# Remove the V2RayPi checkout and virtualenv.
remove_path "$PROJECT_DIR"

echo "remove success, please reboot device!"
