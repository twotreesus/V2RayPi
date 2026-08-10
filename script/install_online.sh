#!/usr/bin/env bash
# Online one-click installer for V2RayPi on Debian-family side routers.
#
# Usage (piped):
#   curl -fsSL https://raw.githubusercontent.com/twotreesus/V2RayPi/feat/mihomo/script/install_online.sh \
#     | sudo bash -s -- [--socks5 URL] [--branch BRANCH] [--dir DIR]
#
# Usage (local copy):
#   sudo bash install_online.sh --socks5 socks5://127.0.0.1:1080 --branch feat/mihomo
#
# When --socks5 is set, proxychains4 is installed first (via apt, without the
# proxy) and then used to wrap every subsequent network step, including the
# full script/install.sh run.
set -euo pipefail

PATH=/bin:/sbin:/usr/bin:/usr/sbin:/usr/local/bin:/usr/local/sbin:~/bin
export PATH

REPO_URL="${V2RAYPI_REPO_URL:-https://github.com/twotreesus/V2RayPi.git}"
RAW_BASE="${V2RAYPI_RAW_BASE:-https://raw.githubusercontent.com/twotreesus/V2RayPi}"
INSTALL_DIR="${V2RAYPI_INSTALL_DIR:-/usr/local/V2RayPi}"
BRANCH="${V2RAYPI_BRANCH:-}"
SOCKS5_URL="${V2RAYPI_SOCKS5:-}"
PROXYCHAINS_CONF="${V2RAYPI_PROXYCHAINS_CONF:-/tmp/v2raypi-proxychains.conf}"
PROXYCHAINS_BIN=""

CFAILURE='\033[1;31m'
CSUCCESS='\033[1;32m'
CINFO='\033[1;34m'
CEND='\033[0m'

log() { printf "${CINFO}[v2raypi]${CEND} %s\n" "$*"; }
ok() { printf "${CSUCCESS}[v2raypi]${CEND} %s\n" "$*"; }
fail() { printf "${CFAILURE}[v2raypi] error:${CEND} %s\n" "$*" >&2; exit 1; }

usage() {
    cat <<USAGE
Usage: $(basename "$0") [options]

Options:
  --socks5 URL    SOCKS5 proxy used for the rest of the install after
                  proxychains4 is configured. Accepted forms:
                    socks5://host:port
                    socks5://user:pass@host:port
                    host:port
  -b, --branch B  Git branch or tag to install (default: remote HEAD)
  --dir DIR       Install directory (default: /usr/local/V2RayPi)
  -h, --help      Show this help

Environment overrides:
  V2RAYPI_SOCKS5 V2RAYPI_BRANCH V2RAYPI_INSTALL_DIR
  V2RAYPI_REPO_URL V2RAYPI_PROXYCHAINS_CONF

Examples:
  curl -fsSL ${RAW_BASE}/feat/mihomo/script/install_online.sh \\
    | sudo bash -s -- --branch feat/mihomo

  curl -fsSL --socks5-hostname 127.0.0.1:1080 \\
    ${RAW_BASE}/feat/mihomo/script/install_online.sh \\
    | sudo bash -s -- --socks5 socks5://127.0.0.1:1080 --branch feat/mihomo
USAGE
}

url_decode() {
    # Minimal percent-decoder for proxy user/password fields.
    local data="${1//+/ }"
    printf '%b' "${data//%/\\x}"
}

parse_socks5() {
    local raw="$1"
    local rest userinfo hostport user pass host port

    [[ -n "$raw" ]] || fail "empty --socks5 value"

    case "$raw" in
        socks5h://*|socks5://*)
            rest="${raw#*://}"
            ;;
        *)
            rest="$raw"
            ;;
    esac

    if [[ "$rest" == *@* ]]; then
        userinfo="${rest%%@*}"
        hostport="${rest#*@}"
        user="${userinfo%%:*}"
        if [[ "$userinfo" == *:* ]]; then
            pass="${userinfo#*:}"
        else
            pass=""
        fi
        user="$(url_decode "$user")"
        pass="$(url_decode "$pass")"
    else
        user=""
        pass=""
        hostport="$rest"
    fi

    host="${hostport%%:*}"
    port="${hostport#*:}"
    if [[ -z "$host" || "$host" == "$hostport" || ! "$port" =~ ^[0-9]+$ ]]; then
        fail "invalid SOCKS5 URL: $raw (expected host:port)"
    fi
    if (( port < 1 || port > 65535 )); then
        fail "invalid SOCKS5 port: $port"
    fi

    SOCKS5_HOST="$host"
    SOCKS5_PORT="$port"
    SOCKS5_USER="$user"
    SOCKS5_PASS="$pass"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --socks5)
            [[ $# -ge 2 ]] || fail "--socks5 requires a value"
            SOCKS5_URL="$2"
            shift 2
            ;;
        --socks5=*)
            SOCKS5_URL="${1#*=}"
            shift
            ;;
        -b|--branch)
            [[ $# -ge 2 ]] || fail "--branch requires a value"
            BRANCH="$2"
            shift 2
            ;;
        --branch=*)
            BRANCH="${1#*=}"
            shift
            ;;
        --dir)
            [[ $# -ge 2 ]] || fail "--dir requires a value"
            INSTALL_DIR="$2"
            shift 2
            ;;
        --dir=*)
            INSTALL_DIR="${1#*=}"
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            fail "unknown option: $1 (use --help)"
            ;;
    esac
done

[[ "$(id -u)" -eq 0 ]] || fail "run as root (sudo)"

if ! command -v apt-get >/dev/null 2>&1; then
    fail "apt-get not found; this installer supports Debian / Ubuntu / Armbian only"
fi

if [[ -n "$SOCKS5_URL" ]]; then
    parse_socks5 "$SOCKS5_URL"
fi

export DEBIAN_FRONTEND=noninteractive

log "Installing bootstrap packages (apt, without proxychains)"
apt-get update -y
apt-get install -y --no-install-recommends \
    ca-certificates curl wget git \
    apt-transport-https

if [[ -n "$SOCKS5_URL" ]]; then
    log "Installing proxychains4 for SOCKS5 ${SOCKS5_HOST}:${SOCKS5_PORT}"
    if ! apt-get install -y --no-install-recommends proxychains4; then
        log "proxychains4 package missing, trying proxychains"
        apt-get install -y --no-install-recommends proxychains
    fi

    if command -v proxychains4 >/dev/null 2>&1; then
        PROXYCHAINS_BIN="$(command -v proxychains4)"
    elif command -v proxychains >/dev/null 2>&1; then
        PROXYCHAINS_BIN="$(command -v proxychains)"
    else
        fail "proxychains4 installed but binary not found in PATH"
    fi

    {
        cat <<'EOF'
# Generated by V2RayPi install_online.sh — used only during installation.
strict_chain
proxy_dns
remote_dns_subnet 224
tcp_read_time_out 15000
tcp_connect_time_out 8000
localnet 127.0.0.0/255.0.0.0
localnet 10.0.0.0/255.0.0.0
localnet 172.16.0.0/255.240.0.0
localnet 192.168.0.0/255.255.0.0
[ProxyList]
EOF
        if [[ -n "$SOCKS5_USER" ]]; then
            printf 'socks5 %s %s %s %s\n' \
                "$SOCKS5_HOST" "$SOCKS5_PORT" "$SOCKS5_USER" "$SOCKS5_PASS"
        else
            printf 'socks5 %s %s\n' "$SOCKS5_HOST" "$SOCKS5_PORT"
        fi
    } >"$PROXYCHAINS_CONF"
    chmod 600 "$PROXYCHAINS_CONF"
    ok "Wrote proxychains config: $PROXYCHAINS_CONF"
fi

run_net() {
    if [[ -n "$PROXYCHAINS_BIN" ]]; then
        # -q keeps install logs readable; -f uses the dedicated temp config.
        "$PROXYCHAINS_BIN" -q -f "$PROXYCHAINS_CONF" "$@"
    else
        "$@"
    fi
}

clone_or_update_repo() {
    local branch_args=()
    if [[ -n "$BRANCH" ]]; then
        branch_args=(-b "$BRANCH")
        log "Target branch: $BRANCH"
    else
        log "Target branch: remote default"
    fi

    if [[ -d "$INSTALL_DIR/.git" ]]; then
        log "Existing install at $INSTALL_DIR, updating"
        if [[ -n "$BRANCH" ]]; then
            run_net git -C "$INSTALL_DIR" fetch --depth 1 origin "$BRANCH"
            run_net git -C "$INSTALL_DIR" checkout -B "$BRANCH" "FETCH_HEAD"
        else
            run_net git -C "$INSTALL_DIR" pull --ff-only
        fi
    elif [[ -e "$INSTALL_DIR" ]]; then
        fail "$INSTALL_DIR exists but is not a git checkout; move it aside and retry"
    else
        log "Cloning $REPO_URL into $INSTALL_DIR"
        run_net git clone --depth 1 "${branch_args[@]}" "$REPO_URL" "$INSTALL_DIR"
    fi
}

clone_or_update_repo

[[ -x "$INSTALL_DIR/script/install.sh" ]] \
    || fail "missing $INSTALL_DIR/script/install.sh after clone"

log "Running script/install.sh"
# Run the full local installer under the same proxychains session so apt,
# pip, git and GitHub downloads all share the SOCKS5 path when configured.
run_net bash "$INSTALL_DIR/script/install.sh"

ok "Online install finished"
log "Open http://<device-ip>:1086 after networking is configured"
if [[ -n "$PROXYCHAINS_BIN" ]]; then
    log "proxychains4 remains installed; install-only config: $PROXYCHAINS_CONF"
fi
