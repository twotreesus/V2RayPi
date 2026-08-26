#!/usr/bin/env bash
# Make Armbian UEFI boxes boot without a monitor attached.
#
# A fresh Armbian x86 image has at least three independent places that still
# wait on a display.  Editing only /etc/default/grub is not enough: Armbian's
# overlay forces gfxterm, and Dell Wyse firmware may try ThinOS before the
# disk.  This script updates every layer, regenerates grub.cfg, and verifies.
#
# Usage:
#   sudo bash script/configure_headless_boot.sh
set -euo pipefail

PATH=/bin:/sbin:/usr/bin:/usr/sbin:/usr/local/bin:/usr/local/sbin:~/bin
export PATH

GRUB_DEFAULT_FILE=/etc/default/grub
ARMBIAN_GRUB_D=/etc/default/grub.d/98-armbian.cfg
HEADLESS_GRUB_D=/etc/default/grub.d/99-headless.cfg
GRUB_CFG=/boot/grub/grub.cfg
GRUBENV=/boot/grub/grubenv
THINOS_GUID='99e275e7-75a0-4b37-a2e6-c5385e6c00cb'
KERNEL_CMDLINE_DEFAULT='quiet nomodeset'

log() { printf '[headless-boot] %s\n' "$*"; }
fail() { printf '[headless-boot] error: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || fail "run as root (sudo bash $0)"

set_grub_key() {
    local file="$1" key="$2" value="$3"
    local tmp
    [ -f "$file" ] || fail "missing $file"
    tmp="$(mktemp)"
    awk -v key="$key" -v value="$value" '
        BEGIN { re = "^[[:space:]]*#?[[:space:]]*" key "=" }
        $0 ~ re {
            print key "=" value
            found = 1
            next
        }
        { print }
        END {
            if (!found) print key "=" value
        }
    ' "$file" > "$tmp"
    cat "$tmp" > "$file"
    rm -f "$tmp"
}

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || fail "$1 is required"
}

log "1/4 updating $GRUB_DEFAULT_FILE"
[ -f "$GRUB_DEFAULT_FILE" ] || fail "missing $GRUB_DEFAULT_FILE"
set_grub_key "$GRUB_DEFAULT_FILE" GRUB_TERMINAL console
set_grub_key "$GRUB_DEFAULT_FILE" GRUB_TERMINAL_INPUT console
set_grub_key "$GRUB_DEFAULT_FILE" GRUB_TERMINAL_OUTPUT console
set_grub_key "$GRUB_DEFAULT_FILE" GRUB_TIMEOUT 2
set_grub_key "$GRUB_DEFAULT_FILE" GRUB_TIMEOUT_STYLE countdown
set_grub_key "$GRUB_DEFAULT_FILE" GRUB_RECORDFAIL_TIMEOUT 2
set_grub_key "$GRUB_DEFAULT_FILE" GRUB_GFXPAYLOAD_LINUX text
set_grub_key "$GRUB_DEFAULT_FILE" GRUB_CMDLINE_LINUX_DEFAULT "\"$KERNEL_CMDLINE_DEFAULT\""

if [ -f "$ARMBIAN_GRUB_D" ]; then
    log "2/4 updating $ARMBIAN_GRUB_D (Armbian overlay, this is the one that overrides /etc/default/grub)"
    set_grub_key "$ARMBIAN_GRUB_D" GRUB_TERMINAL '"console"'
    set_grub_key "$ARMBIAN_GRUB_D" GRUB_TIMEOUT 2
    set_grub_key "$ARMBIAN_GRUB_D" GRUB_TIMEOUT_STYLE countdown
    set_grub_key "$ARMBIAN_GRUB_D" GRUB_GFXPAYLOAD_LINUX text
    set_grub_key "$ARMBIAN_GRUB_D" GRUB_CMDLINE_LINUX_DEFAULT "\"$KERNEL_CMDLINE_DEFAULT\""
else
    log "2/4 $ARMBIAN_GRUB_D not present, skipping"
fi

log "writing $HEADLESS_GRUB_D (last-wins drop-in so an Armbian upgrade of 98-armbian.cfg cannot restore gfxterm)"
mkdir -p /etc/default/grub.d
cat > "$HEADLESS_GRUB_D" <<'EOF'
# Last-wins overlay.  Armbian ships 98-armbian.cfg with GRUB_TERMINAL=gfxterm,
# which hangs on machines whose EFI GOP is missing without HDMI (Wyse 3040).
GRUB_TERMINAL="console"
GRUB_TERMINAL_INPUT="console"
GRUB_TERMINAL_OUTPUT="console"
GRUB_TIMEOUT=2
GRUB_TIMEOUT_STYLE=countdown
GRUB_RECORDFAIL_TIMEOUT=2
GRUB_GFXPAYLOAD_LINUX=text
GRUB_CMDLINE_LINUX_DEFAULT="quiet nomodeset"
EOF
chmod 644 "$HEADLESS_GRUB_D"

if [ -f "$GRUBENV" ]; then
    grub-editenv "$GRUBENV" unset recordfail 2>/dev/null || true
fi

log "3/4 regenerating $GRUB_CFG"
require_cmd update-grub
update-grub

[ -f "$GRUB_CFG" ] || fail "update-grub did not produce $GRUB_CFG"
if grep -qE '^[[:space:]]*terminal_output[[:space:]]+gfxterm' "$GRUB_CFG"; then
    fail "$GRUB_CFG still uses gfxterm; GRUB drop-ins did not take effect"
fi
if ! grep -qE '^[[:space:]]*terminal_output[[:space:]]+console' "$GRUB_CFG"; then
    fail "$GRUB_CFG has no terminal_output console"
fi
log "grub.cfg terminal is console"
if ! grep -E '^[[:space:]]*linux ' "$GRUB_CFG" | grep -qw nomodeset; then
    fail "$GRUB_CFG kernel command line is missing nomodeset"
fi
if ! grep -E '^[[:space:]]*linux ' "$GRUB_CFG" | grep -qw quiet; then
    fail "$GRUB_CFG kernel command line is missing quiet"
fi
log "grub.cfg kernel command line includes: $KERNEL_CMDLINE_DEFAULT"

log "4/4 adjusting EFI BootOrder"
if ! command -v efibootmgr >/dev/null 2>&1; then
    if command -v apt-get >/dev/null 2>&1; then
        apt-get install -y efibootmgr
    else
        fail "efibootmgr is not installed"
    fi
fi

python3 - "$THINOS_GUID" <<'PY'
import re
import subprocess
import sys

thinos_guid = sys.argv[1].lower()
raw = subprocess.check_output(["efibootmgr", "-v"], text=True, errors="replace")

entries = []
order = []
for line in raw.splitlines():
    if line.startswith("BootOrder:"):
        order = [part.strip() for part in line.split(":", 1)[1].split(",") if part.strip()]
        continue
    match = re.match(r"Boot([0-9A-Fa-f]{4})\*?\s+(.*)", line)
    if not match:
        continue
    boot_id, rest = match.group(1), match.group(2)
    rest_l = rest.lower()
    is_disk_efi = ("hd(" in rest_l) and (
        "bootx64.efi" in rest_l or "grubx64.efi" in rest_l or r"efi\debian" in rest_l
        or r"efi/debian" in rest_l or r"efi\armbian" in rest_l
    )
    is_thinos = thinos_guid in rest_l or "dellthinos" in rest_l
    entries.append((boot_id, rest, is_disk_efi, is_thinos))

disk_ids = [boot_id for boot_id, _, is_disk, _ in entries if is_disk]
thinos_ids = [boot_id for boot_id, _, _, is_thinos in entries if is_thinos]
known = {boot_id for boot_id, _, _, _ in entries}

if not disk_ids:
    print("[headless-boot] warning: no HD EFI loader found, leaving BootOrder unchanged", flush=True)
    sys.exit(0)

for boot_id in thinos_ids:
    print(f"[headless-boot] deactivating leftover ThinOS entry Boot{boot_id}", flush=True)
    subprocess.check_call(["efibootmgr", "-b", boot_id, "-A"])

remainder = [boot_id for boot_id in order if boot_id in known and boot_id not in disk_ids and boot_id not in thinos_ids]
new_order = disk_ids + remainder + [boot_id for boot_id in thinos_ids if boot_id not in disk_ids]
# Keep ids that efibootmgr listed but that our parser skipped (PXE, etc.).
for boot_id in order:
    if boot_id not in new_order:
        new_order.append(boot_id)

joined = ",".join(new_order)
print(f"[headless-boot] BootOrder {','.join(order) or '(empty)'} -> {joined}", flush=True)
subprocess.check_call(["efibootmgr", "-o", joined])
PY

echo
log "done. current EFI boot entries:"
efibootmgr
echo
log "effective GRUB terminal lines:"
grep -E '^[[:space:]]*terminal_(input|output) ' "$GRUB_CFG"
log "effective kernel command line:"
grep -E '^[[:space:]]*linux ' "$GRUB_CFG" | head -5
log "reboot once without HDMI to confirm SSH comes up"
