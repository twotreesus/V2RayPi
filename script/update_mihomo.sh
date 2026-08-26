#!/usr/bin/env bash
# Install or update the official mihomo binary.
#
# The portable release binaries are used instead of a distribution-specific
# package so this works on macOS and on Linux distributions with different
# package managers/init systems.
set -euo pipefail

REPOSITORY="${MIHOMO_REPOSITORY:-MetaCubeX/mihomo}"
INSTALL_DIR="${MIHOMO_INSTALL_DIR:-/usr/local/bin}"
DEFAULT_BINARY="$INSTALL_DIR/mihomo"
MODE="${1:-update}"

usage() {
    cat <<USAGE
Usage: $(basename "$0") [install|update|version]

Environment overrides:
  MIHOMO_INSTALL_DIR  Installation directory (default: /usr/local/bin)
  MIHOMO_BIN          Absolute destination path (default: /usr/local/bin/mihomo)
  MIHOMO_REPOSITORY   GitHub repository (default: MetaCubeX/mihomo)
USAGE
}

log() { printf '[mihomo] %s\n' "$*"; }
fail() { printf '[mihomo] error: %s\n' "$*" >&2; exit 1; }

if [[ "$MODE" != install && "$MODE" != update && "$MODE" != version ]]; then
    usage >&2
    exit 2
fi

if [[ -n "${MIHOMO_BIN:-}" && "$MIHOMO_BIN" == */* ]]; then
    DESTINATION="$MIHOMO_BIN"
else
    DESTINATION="$DEFAULT_BINARY"
fi

command -v uname >/dev/null 2>&1 || fail "uname is required"
OS="$(uname -s)"
ARCH="$(uname -m)"

# The unnamed *-amd64 assets are built with GOAMD64=v3 (AVX2).  Older chips
# such as Intel Atom need the compatible (GOAMD64=v1) build instead.
cpu_supports_amd64_v3() {
    local flags=""
    if [[ -r /proc/cpuinfo ]]; then
        flags="$(awk '/^flags[[:space:]]*:/{print; exit}' /proc/cpuinfo)"
    elif command -v sysctl >/dev/null 2>&1; then
        flags="$(sysctl -n machdep.cpu.features 2>/dev/null || true)"
        flags="$flags $(sysctl -n machdep.cpu.leaf7_features 2>/dev/null || true)"
    fi
    flags=" $(printf '%s' "$flags" | tr '[:upper:]' '[:lower:]') "
    case "$flags" in
        *" avx2 "*) return 0 ;;
        *) return 1 ;;
    esac
}

amd64_platform() {
    local os_prefix="$1"
    if cpu_supports_amd64_v3; then
        printf '%s-amd64\n' "$os_prefix"
    else
        printf '%s-amd64-compatible\n' "$os_prefix"
    fi
}

case "$OS:$ARCH" in
    Darwin:x86_64) ASSET_PLATFORM="$(amd64_platform darwin)" ;;
    Darwin:arm64|Darwin:aarch64) ASSET_PLATFORM="darwin-arm64" ;;
    Linux:x86_64|Linux:amd64) ASSET_PLATFORM="$(amd64_platform linux)" ;;
    Linux:aarch64|Linux:arm64) ASSET_PLATFORM="linux-arm64" ;;
    Linux:armv7l|Linux:armv7) ASSET_PLATFORM="linux-armv7" ;;
    Linux:armv6l|Linux:armv6) ASSET_PLATFORM="linux-armv6" ;;
    Linux:riscv64) ASSET_PLATFORM="linux-riscv64" ;;
    *) fail "unsupported platform: $OS $ARCH" ;;
esac

command -v gzip >/dev/null 2>&1 || fail "gzip is required"
if command -v curl >/dev/null 2>&1; then
    fetch() { curl -fsSL --retry 3 --connect-timeout 10 "$@"; }
    # Progress goes to stderr so the install log still reads cleanly when the
    # archive itself is written to a file.  -f still fails on HTTP errors; -s
    # is intentionally omitted so the meter is visible.
    download_file() {
        local url="$1" dest="$2"
        curl -fL --retry 3 --connect-timeout 10 --progress-bar -o "$dest" "$url"
    }
elif command -v wget >/dev/null 2>&1; then
    fetch() { wget -qO- "$1"; }
    download_file() {
        local url="$1" dest="$2"
        # force:noscroll keeps one updating line even when stderr is not a TTY
        # (for example when the installer is piped through `tee`).
        wget --progress=bar:force:noscroll -O "$dest" "$url"
    }
else
    fail "curl or wget is required"
fi

if [[ "$MODE" == version ]]; then
    if [[ -x "$DESTINATION" ]]; then
        "$DESTINATION" -v 2>/dev/null || true
    else
        printf 'not installed\n'
    fi
    exit 0
fi

command -v python3 >/dev/null 2>&1 || fail "python3 is required to read the GitHub release metadata"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/mihomo-update.XXXXXX")"
cleanup() { rm -rf "$TMP_DIR"; }
trap cleanup EXIT

API_JSON="$TMP_DIR/release.json"
fetch "https://api.github.com/repos/$REPOSITORY/releases/latest" > "$API_JSON"

read_release_info() {
    # Print one value per line.  Python is part of V2RayPi's runtime on both
    # supported operating systems, and avoids requiring jq.
    python3 - "$API_JSON" "$ASSET_PLATFORM" <<'PY'
import json
import sys

with open(sys.argv[1], encoding='utf-8') as stream:
    release = json.load(stream)
platform = sys.argv[2]
tag = release.get('tag_name', '')
if not tag:
    raise SystemExit('GitHub release has no tag_name')
archive = f'mihomo-{platform}-{tag}.gz'
for item in release.get('assets', []):
    if item.get('name') == archive:
        # `digest` is only present on assets uploaded by newer GitHub versions;
        # the stable releases ship no checksums.txt, so this is the only
        # verification source available.  An empty line means "not published".
        digest = item.get('digest') or ''
        print(tag)
        print(archive)
        print(item.get('browser_download_url'))
        print(digest)
        break
else:
    raise SystemExit(f'no mihomo asset found for {platform}: {archive}')
PY
}

sha256_of() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{print $1}'
    else
        fail "sha256sum or shasum is required"
    fi
}

load_release_info() {
    local old_ifs=$IFS
    IFS=$'\n'
    set -f
    # macOS still ships Bash 3.x, so avoid Bash 4's mapfile/readarray.
    # shellcheck disable=SC2207
    RELEASE_INFO=( $(read_release_info) )
    set +f
    IFS=$old_ifs
    TAG="${RELEASE_INFO[0]}"
    ARCHIVE_NAME="${RELEASE_INFO[1]}"
    ARCHIVE_URL="${RELEASE_INFO[2]}"
    DIGEST="${RELEASE_INFO[3]:-}"
    ARCHIVE_PATH="$TMP_DIR/$ARCHIVE_NAME"
}

download_and_extract() {
    log "downloading $TAG for $ASSET_PLATFORM"
    download_file "$ARCHIVE_URL" "$ARCHIVE_PATH"

    if [[ -n "$DIGEST" ]]; then
        EXPECTED="${DIGEST#sha256:}"
        [[ ${#EXPECTED} -eq 64 && "$EXPECTED" =~ ^[[:xdigit:]]+$ ]] || fail "invalid digest for $ARCHIVE_NAME"
        ACTUAL="$(sha256_of "$ARCHIVE_PATH")"
        [[ "$EXPECTED" == "$ACTUAL" ]] || fail "checksum verification failed"
        log "verified sha256 $EXPECTED"
    else
        # The release publishes no checksum for this asset.  Fall back to proving
        # the download is a complete gzip stream and that the extracted binary
        # actually runs, and say so plainly rather than implying verification.
        log "warning: release publishes no checksum for $ARCHIVE_NAME, skipping verification"
    fi

    gzip -dc "$ARCHIVE_PATH" > "$SOURCE" || fail "the downloaded archive is not a valid gzip stream"
    chmod 755 "$SOURCE"
    "$SOURCE" -v >/dev/null 2>&1
}

SOURCE="$TMP_DIR/mihomo"
load_release_info
if ! download_and_extract; then
    case "$ASSET_PLATFORM" in
        linux-amd64|darwin-amd64)
            log "default amd64 binary does not run, retrying with compatible (GOAMD64=v1)"
            ASSET_PLATFORM="${ASSET_PLATFORM}-compatible"
            load_release_info
            download_and_extract || fail "the extracted binary does not run on this platform"
            ;;
        *)
            fail "the extracted binary does not run on this platform"
            ;;
    esac
fi

DEST_DIR="$(dirname "$DESTINATION")"
if [[ ! -d "$DEST_DIR" ]]; then
    if mkdir -p "$DEST_DIR" 2>/dev/null; then
        :
    elif command -v sudo >/dev/null 2>&1; then
        sudo mkdir -p "$DEST_DIR"
    else
        fail "cannot create $DEST_DIR (run with root or install sudo)"
    fi
fi

# Install atomically when possible.  sudo is used only if the destination is
# not writable by the current user, which keeps local/custom installs simple.
if [[ -w "$DEST_DIR" ]]; then
    STAGED_DEST="$DESTINATION.tmp.$$"
    install -m 755 "$SOURCE" "$STAGED_DEST"
    mv -f "$STAGED_DEST" "$DESTINATION"
elif command -v sudo >/dev/null 2>&1; then
    sudo install -m 755 "$SOURCE" "$DESTINATION"
else
    fail "cannot write $DESTINATION (run with root or install sudo)"
fi

log "installed $TAG at $DESTINATION"
"$DESTINATION" -v 2>/dev/null || true
