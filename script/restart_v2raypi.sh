#!/usr/bin/env bash
# Restart the V2RayPi supervisor program.
#
# echo_supervisord_conf keeps the control socket in /tmp. systemd-tmpfiles
# deletes unused files there after 10 days, after which supervisorctl cannot
# reach supervisord and "update and restart" only pulls git. Move the runtime
# files to /run and restart via systemd when the unit exists.

set -euo pipefail

SUPERVISOR_CONFIG="${SUPERVISOR_CONFIG:-/etc/supervisor/supervisord.conf}"
RUN_SOCK="/run/supervisor.sock"
RUN_PID="/run/supervisord.pid"
LOG_FILE="/var/log/supervisor/supervisord.log"

ensure_supervisor_runtime_paths() {
    local conf="${1:-$SUPERVISOR_CONFIG}"
    [[ -f "$conf" ]] || return 0
    sed -i.bak \
        -e "s|^file=/tmp/supervisor.sock|file=${RUN_SOCK}|" \
        -e "s|^serverurl=unix:///tmp/supervisor.sock|serverurl=unix://${RUN_SOCK}|" \
        -e "s|^pidfile=/tmp/supervisord.pid|pidfile=${RUN_PID}|" \
        -e "s|^logfile=/tmp/supervisord.log|logfile=${LOG_FILE}|" \
        "$conf"
    rm -f "${conf}.bak"
}

restart_v2raypi() {
    mkdir -p /run /var/log/supervisor
    ensure_supervisor_runtime_paths "$SUPERVISOR_CONFIG"
    if command -v systemctl >/dev/null 2>&1 && systemctl restart supervisor; then
        echo "Restarted supervisor via systemd"
        return 0
    fi
    echo "systemd restart unavailable, trying supervisorctl"
    supervisorctl -c "$SUPERVISOR_CONFIG" restart v2raypi
}

if [[ "${1:-}" == "--ensure-only" ]]; then
    ensure_supervisor_runtime_paths "${2:-$SUPERVISOR_CONFIG}"
    exit 0
fi

restart_v2raypi
