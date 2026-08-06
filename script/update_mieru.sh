#!/usr/bin/env bash
# Install or update the official Mieru client binary.
#
# The portable release archives are used instead of a distribution-specific
# package so this works on macOS and on Linux distributions with different
# package managers/init systems.
set -euo pipefail

REPOSITORY="${MIERU_REPOSITORY:-enfein/mieru}"
INSTALL_DIR="${MIERU_INSTALL_DIR:-/usr/local/bin}"
DEFAULT_BINARY="$INSTALL_DIR/mieru"
MODE="${1:-update}"

usage() {
    cat <<USAGE
Usage: $(basename "$0") [install|update|version]

Environment overrides:
  MIERU_INSTALL_DIR  Installation directory (default: /usr/local/bin)
  MIERU_BIN          Absolute destination path (default: /usr/local/bin/mieru)
  MIERU_REPOSITORY   GitHub repository (default: enfein/mieru)
USAGE
}

log() { printf '[mieru] %s\n' "$*"; }
fail() { printf '[mieru] error: %s\n' "$*" >&2; exit 1; }

if [[ "$MODE" != install && "$MODE" != update && "$MODE" != version ]]; then
    usage >&2
    exit 2
fi

if [[ -n "${MIERU_BIN:-}" && "$MIERU_BIN" == */* ]]; then
    DESTINATION="$MIERU_BIN"
else
    DESTINATION="$DEFAULT_BINARY"
fi

command -v uname >/dev/null 2>&1 || fail "uname is required"
OS="$(uname -s)"
ARCH="$(uname -m)"
case "$OS:$ARCH" in
    Darwin:x86_64) ASSET_PLATFORM="macos_amd64" ;;
    Darwin:arm64|Darwin:aarch64) ASSET_PLATFORM="macos_arm64" ;;
    Linux:x86_64|Linux:amd64) ASSET_PLATFORM="linux_amd64" ;;
    Linux:aarch64|Linux:arm64) ASSET_PLATFORM="linux_arm64" ;;
    Linux:armv7l|Linux:armv7) ASSET_PLATFORM="linux_armv7" ;;
    Linux:riscv64) ASSET_PLATFORM="linux_riscv64" ;;
    *) fail "unsupported platform: $OS $ARCH" ;;
esac

command -v tar >/dev/null 2>&1 || fail "tar is required"
if command -v curl >/dev/null 2>&1; then
    fetch() { curl -fsSL --retry 3 --connect-timeout 10 "$@"; }
elif command -v wget >/dev/null 2>&1; then
    fetch() { wget -qO- "$1"; }
else
    fail "curl or wget is required"
fi

if [[ "$MODE" == version ]]; then
    if [[ -x "$DESTINATION" ]]; then
        "$DESTINATION" version 2>/dev/null || "$DESTINATION" --version 2>/dev/null || true
    else
        printf 'not installed\n'
    fi
    exit 0
fi

command -v python3 >/dev/null 2>&1 || fail "python3 is required to read the GitHub release metadata"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/mieru-update.XXXXXX")"
cleanup() { rm -rf "$TMP_DIR"; }
trap cleanup EXIT

API_JSON="$TMP_DIR/release.json"
fetch "https://api.github.com/repos/$REPOSITORY/releases/latest" > "$API_JSON"

readarray_compat() {
    # Print one JSON value per line.  Python is part of V2RayPi's runtime on
    # both supported operating systems, and avoids requiring jq.
    python3 - "$API_JSON" "$ASSET_PLATFORM" <<'PY'
import json
import sys

with open(sys.argv[1], encoding='utf-8') as stream:
    release = json.load(stream)
platform = sys.argv[2]
version = release.get('tag_name', '').lstrip('v')
if not version:
    raise SystemExit('GitHub release has no tag_name')
archive = f'mieru_{version}_{platform}.tar.gz'
checksum = archive + '.sha256.txt'
assets = {item.get('name'): item.get('browser_download_url') for item in release.get('assets', [])}
if archive not in assets or checksum not in assets:
    raise SystemExit(f'no Mieru assets found for {platform}: {archive}')
print(release['tag_name'])
print(archive)
print(assets[archive])
print(assets[checksum])
PY
}

# macOS still ships Bash 3.x, so avoid Bash 4's mapfile/readarray.
OLD_IFS=$IFS
IFS=$'\n'
set -f
# shellcheck disable=SC2207
RELEASE_INFO=( $(readarray_compat) )
set +f
IFS=$OLD_IFS
TAG="${RELEASE_INFO[0]}"
ARCHIVE_NAME="${RELEASE_INFO[1]}"
ARCHIVE_URL="${RELEASE_INFO[2]}"
CHECKSUM_URL="${RELEASE_INFO[3]}"
ARCHIVE_PATH="$TMP_DIR/$ARCHIVE_NAME"
CHECKSUM_PATH="$TMP_DIR/$ARCHIVE_NAME.sha256.txt"

log "downloading $TAG for $ASSET_PLATFORM"
fetch "$ARCHIVE_URL" > "$ARCHIVE_PATH"
fetch "$CHECKSUM_URL" > "$CHECKSUM_PATH"

EXPECTED="$(awk -v name="$ARCHIVE_NAME" '$2 == name { print $1; exit }' "$CHECKSUM_PATH")"
if [[ -z "$EXPECTED" ]]; then
    EXPECTED="$(awk 'NF { print $1; exit }' "$CHECKSUM_PATH")"
fi
[[ ${#EXPECTED} -eq 64 && "$EXPECTED" =~ ^[[:xdigit:]]+$ ]] || fail "invalid SHA-256 checksum for $ARCHIVE_NAME"

if command -v sha256sum >/dev/null 2>&1; then
    ACTUAL="$(sha256sum "$ARCHIVE_PATH" | awk '{print $1}')"
elif command -v shasum >/dev/null 2>&1; then
    ACTUAL="$(shasum -a 256 "$ARCHIVE_PATH" | awk '{print $1}')"
else
    fail "sha256sum or shasum is required"
fi
[[ "$EXPECTED" == "$ACTUAL" ]] || fail "checksum verification failed"

EXTRACT_DIR="$TMP_DIR/extracted"
mkdir -p "$EXTRACT_DIR"
tar -xzf "$ARCHIVE_PATH" -C "$EXTRACT_DIR"
SOURCE="$(find "$EXTRACT_DIR" -type f -name mieru -print | sed -n '1p')"
[[ -n "$SOURCE" ]] || fail "the release archive does not contain an executable named mieru"

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
"$DESTINATION" version 2>/dev/null || "$DESTINATION" --version 2>/dev/null || true
