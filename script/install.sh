#!/usr/bin/env bash
PATH=/bin:/sbin:/usr/bin:/usr/sbin:/usr/local/bin:/usr/local/sbin:~/bin
export PATH
export DEBIAN_FRONTEND=noninteractive

set -eEuo pipefail

C_BLUE='\033[1;34m'
C_GREEN='\033[1;32m'
C_RED='\033[1;31m'
C_RESET='\033[0m'
CURRENT_STEP=""

print_start() { printf '%b▸ %s%b\n' "$C_BLUE" "$1" "$C_RESET"; }
print_ok() { printf '%b✔ %s%b\n' "$C_GREEN" "$1" "$C_RESET"; }
print_fail() { printf '%b✘ %s%b\n' "$C_RED" "$1" "$C_RESET" >&2; }

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

#check Root
if [[ "$(id -u)" != "0" ]]; then
    print_fail "Must run as root"
    exit 1
fi

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$( cd "$SCRIPT_DIR/.." && pwd )"
VENV_DIR="$PROJECT_DIR/venv"

# Preserve the TPROXY service state across reinstalls. A fresh installation
# remains disabled until the first node is successfully applied.
IPTABLES_WAS_ENABLED=0
if command -v systemctl >/dev/null 2>&1 && systemctl is-enabled --quiet mihomo_iptable.service 2>/dev/null; then
    IPTABLES_WAS_ENABLED=1
fi

install_packages() {
    apt-get update -y
    apt-get install wget curl socat git iptables python3 python3-venv python3-dev openssl libssl-dev ca-certificates supervisor -y
}

install_python_deps() {
    python3 -m venv "$VENV_DIR"
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
    pip install --upgrade pip setuptools wheel
    pip install -r "$SCRIPT_DIR/requirements.txt"
    deactivate
}

configure_rc_local() {
    cat>/etc/rc.local<<-EOF
#!/bin/sh -e
#
# rc.local
#
# This script is executed at the end of each multiuser runlevel.
# Make sure that the script will "exit 0" on success or any other
# value on error.
#
# In order to enable or disable this script just change the execution
# bits.
#
# By default this script does nothing.
if [ ! -d "/var/log/mihomo" ]; then
    mkdir /var/log/mihomo
fi
exit 0
EOF
    chmod +x /etc/rc.local
}

install_mihomo() {
    mkdir -p /etc/mihomo/
    mkdir -p /var/log/mihomo/
    bash "$SCRIPT_DIR/update_mihomo.sh" install
}

install_ipinfo() {
    echo "deb [trusted=yes] https://ppa.ipinfo.net/ /" \
        > /etc/apt/sources.list.d/ipinfo.ppa.list
    apt-get update -y
    apt-get install -y ipinfo
}

seed_mihomo_config() {
    # mihomo refuses to start without a config file.  Seed a direct-mode
    # placeholder so the service is startable before the first node is applied;
    # V2RayPi overwrites it on every node application.
    if [ ! -f /etc/mihomo/config.yaml ]; then
        cat>/etc/mihomo/config.yaml<<-EOF
mode: direct
log-level: warning
rules:
  - MATCH,DIRECT
EOF
    fi
    chmod 644 /etc/mihomo/config.yaml
}

install_geo_data() {
    # Download the GEO databases and persist the release version before the web
    # app starts.  CoreService keeps the user config in memory for the life of the
    # process, so writing current_version after supervisor has already loaded an
    # empty config would leave the UI showing "[Built-in version]" until restart.
    cd "$PROJECT_DIR"
    "$VENV_DIR/bin/python" - <<'PY'
from core.core_service import CoreService

CoreService.load()
CoreService.update_geo_data()
PY
}

configure_supervisor() {
    mkdir -p /etc/supervisor/conf.d
    echo_supervisord_conf > /etc/supervisor/supervisord.conf
    cat>>/etc/supervisor/supervisord.conf<<EOF
[include]
files = /etc/supervisor/conf.d/*.ini
EOF
    cat>/etc/supervisor/conf.d/v2raypi.ini<<-EOF
[program:v2raypi]
command=/usr/local/V2RayPi/script/start.sh run
stdout_logfile=/var/log/v2raypi
redirect_stderr=true
environment=PYTHONUNBUFFERED=1
autostart=true
autorestart=true
startsecs=5
priority=1
stopasgroup=true
killasgroup=true
EOF
    systemctl restart supervisor
    supervisorctl -c /etc/supervisor/supervisord.conf restart v2raypi \
        || supervisorctl -c /etc/supervisor/supervisord.conf start v2raypi
}

configure_mihomo_service() {
    # Logs are appended to a file rather than left in the journal so that the
    # management UI can tail them the same way it always has.  The redirection
    # is done by a shell instead of StandardOutput=append:, which needs systemd
    # 240 and is silently ignored on older distributions.
    cat>/etc/systemd/system/mihomo.service<<-EOF
[Unit]
Description=mihomo Daemon
After=network.target nss-lookup.target
Wants=network.target

[Service]
Type=simple
ExecStartPre=/bin/sleep 1s
ExecStart=/bin/sh -c 'exec /usr/local/bin/mihomo -d /etc/mihomo >>/var/log/mihomo/mihomo.log 2>&1'
Restart=always
CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_RAW CAP_NET_BIND_SERVICE CAP_SYS_TIME CAP_SYS_PTRACE CAP_DAC_READ_SEARCH CAP_DAC_OVERRIDE
AmbientCapabilities=CAP_NET_ADMIN CAP_NET_RAW CAP_NET_BIND_SERVICE CAP_SYS_TIME CAP_SYS_PTRACE CAP_DAC_READ_SEARCH CAP_DAC_OVERRIDE

[Install]
WantedBy=multi-user.target
EOF
}

configure_iptables_service() {
    echo net.ipv4.ip_forward=1 >> /etc/sysctl.conf && sysctl -p
    cat>/etc/systemd/system/mihomo_iptable.service<<-EOF
[Unit]
Description=Tproxy rule
After=network-online.target
Before=mihomo.service
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/bash /usr/local/V2RayPi/script/config_iptable.sh

[Install]
WantedBy=multi-user.target
EOF
}

enable_services() {
    systemctl daemon-reload
    systemctl enable mihomo.service

    # Keep a fresh installation safe, while preserving an already-enabled
    # service when the installer is run again.
    if [[ "$IPTABLES_WAS_ENABLED" -eq 1 ]]; then
        systemctl enable mihomo_iptable.service
        systemctl restart mihomo_iptable.service
    else
        systemctl disable mihomo_iptable.service >/dev/null 2>&1 || true
        systemctl stop mihomo_iptable.service >/dev/null 2>&1 || true
    fi

    systemctl start rc-local
    systemctl status rc-local --no-pager || true
    sync
}

step "Installing system packages" "Installed system packages" install_packages
step "Installing Python dependencies" "Installed Python dependencies" install_python_deps
step "Configuring rc.local" "Configured rc.local" configure_rc_local
step "Installing mihomo" "Installed mihomo" install_mihomo
step "Installing ipinfo" "Installed ipinfo" install_ipinfo
step "Seeding mihomo config" "Seeded mihomo config" seed_mihomo_config
step "Installing GEO databases" "Installed GEO databases" install_geo_data
step "Configuring Supervisor" "Configured Supervisor" configure_supervisor
step "Configuring mihomo service" "Configured mihomo service" configure_mihomo_service
step "Configuring TPROXY service" "Configured TPROXY service" configure_iptables_service
step "Enabling services" "Enabled services" enable_services

print_ok "Install finished"
