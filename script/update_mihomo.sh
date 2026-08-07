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
case "$OS:$ARCH" in
    Darwin:x86_64) ASSET_PLATFORM="darwin-amd64" ;;
    Darwin:arm64|Darwin:aarch64) ASSET_PLATFORM="darwin-arm64" ;;
    Linux:x86_64|Linux:amd64) ASSET_PLATFORM="linux-amd64" ;;
    Linux:aarch64|Linux:arm64) ASSET_PLATFORM="linux-arm64" ;;
    Linux:armv7l|Linux:armv7) ASSET_PLATFORM="linux-armv7" ;;
    Linux:armv6l|Linux:armv6) ASSET_PLATFORM="linux-armv6" ;;
    Linux:riscv64) ASSET_PLATFORM="linux-riscv64" ;;
    *) fail "unsupported platform: $OS $ARCH" ;;
esac

command -v gzip >/dev/null 2>&1 || fail "gzip is required"
if command -v curl >/dev/null 2>&1; then
    fetch() { curl -fsSL --retry 3 --connect-timeout 10 "$@"; }
elif command -v wget >/dev/null 2>&1; then
    fetch() { wget -qO- "$1"; }
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

# macOS still ships Bash 3.x, so avoid Bash 4's mapfile/readarray.
OLD_IFS=$IFS
IFS=$'\n'
set -f
# shellcheck disable=SC2207
RELEASE_INFO=( $(read_release_info) )
set +f
IFS=$OLD_IFS
TAG="${RELEASE_INFO[0]}"
ARCHIVE_NAME="${RELEASE_INFO[1]}"
ARCHIVE_URL="${RELEASE_INFO[2]}"
DIGEST="${RELEASE_INFO[3]:-}"
ARCHIVE_PATH="$TMP_DIR/$ARCHIVE_NAME"

log "downloading $TAG for $ASSET_PLATFORM"
fetch "$ARCHIVE_URL" > "$ARCHIVE_PATH"

sha256_of() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{print $1}'
    else
        fail "sha256sum or shasum is required"
    fi
}

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

SOURCE="$TMP_DIR/mihomo"
gzip -dc "$ARCHIVE_PATH" > "$SOURCE" || fail "the downloaded archive is not a valid gzip stream"
chmod 755 "$SOURCE"
"$SOURCE" -v >/dev/null 2>&1 || fail "the extracted binary does not run on this platform"

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
