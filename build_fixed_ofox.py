#!/usr/bin/env python3
"""Build a fixed OrangeFox R12.0 vendor_boot.img for klee (OS4.0.7.0) without
altering stock vendor_ramdisk00 or stock dtb.

Fixes applied in vendor_ramdisk01 (recovery ramdisk):
1. Writable /persist without wipe flags so OrangeFox saves settings (.foxs).
2. Unified ConfigFS USB triggers (no init.rc vs init.recovery.usb.rc race,
   always unbind UDC before changing gadget functions, stop adbd on pure MTP).
3. Sync pre-fastbootd cleanup (prep-fastbootd.sh): unmounts mounted logical
   partitions, unmaps all dynamic super logical partitions, and removes stale
   dm-* symlinks under /dev/block/by-name before fastbootd binds USB.
4. Import /init.recovery.project.rc inside init.recovery.mt6899.rc (matching stock).
5. Provide clean /fstab.mt6899, deduplicate mi_ext in recovery.fstab, add
   /init_boot and logical *_image targets + safe /usb_otg paths in twrp.flags.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

OUT_DIR = Path("/tmp/ofox_build")
OUT_IMG = Path("/home/emre/Masaüstü/EU ROM/OrangeFox-R12.0-klee-OS4.0.7-fixed.img")
FASTBOOT_VBOOT = Path("/home/emre/Masaüstü/EU ROM/klee_eea_OS4.0.7.0_fastboot/images/vendor_boot.img")
PORTED_VBOOT = Path("/home/emre/Masaüstü/EU ROM/klee_eea_OS4.0.7.0_fastboot/images/vendor_boot.img")
STOCK_VBOOT = Path(
    "/home/emre/Masaüstü/EU ROM/klee_eea_global-ota_full-OS4.0.7.0.XPJEUXM-user-17.0-ba76c0cfd8/"
    "extracted_20261116_143528/vendor_boot.img"
)

PREP_FASTBOOTD_SH = """#!/sbin/sh
# Unmount/unmap all dynamic super partitions and clear stale dm-* symlinks
# before fastbootd starts so every logical slot partition opens rw cleanly.

LOG=/tmp/prep-fastbootd.log
echo "=== prep-fastbootd start ===" > "$LOG"

for mnt in /system_root /system /vendor /product /system_ext /odm /mnt/vendor/mi_ext /mi_ext /vendor_dlkm /odm_dlkm /system_dlkm /tmp_system_rom; do
    if grep -q " ${mnt} " /proc/mounts 2>/dev/null; then
        umount "$mnt" >> "$LOG" 2>&1 || umount -l "$mnt" >> "$LOG" 2>&1 || true
    fi
done

for base in system system_ext product mi_ext mi_product vendor odm vendor_dlkm odm_dlkm system_dlkm; do
    for suffix in _a _b ""; do
        part="${base}${suffix}"
        if [ -e "/dev/block/mapper/${part}" ]; then
            echo "Unmapping ${part}" >> "$LOG"
            /system/bin/lptools unmap "$part" >> "$LOG" 2>&1 || /system/bin/dmctl delete "$part" >> "$LOG" 2>&1 || true
        fi
    done
done

for dir in /dev/block/by-name /dev/block/bootdevice/by-name; do
    [ -d "$dir" ] || continue
    for lnk in "$dir"/*; do
        [ -L "$lnk" ] || continue
        tgt="$(readlink "$lnk" 2>/dev/null)"
        case "$tgt" in
            /dev/block/dm-*)
                echo "Removing stale dm symlink: $lnk -> $tgt" >> "$LOG"
                rm -f "$lnk"
                ;;
        esac
    done
done

ls -la /dev/block/mapper/ >> "$LOG" 2>&1
echo "=== prep-fastbootd done ===" >> "$LOG"
exit 0
"""

INIT_RECOVERY_USB_RC = """# USB gadget configuration (configfs) - authoritative single source for recovery

on early-init
    setprop sys.usb.configfs 0

on fs
    mkdir /config
    mount configfs none /config
    mkdir /config/usb_gadget/g1 0770 shell shell
    write /config/usb_gadget/g1/bcdUSB 0x0200
    write /config/usb_gadget/g1/os_desc/use 1
    write /config/usb_gadget/g1/idVendor 0x2717
    write /config/usb_gadget/g1/idProduct 0x4EE7
    mkdir /config/usb_gadget/g1/strings/0x409 0770 shell shell
    write /config/usb_gadget/g1/strings/0x409/serialnumber ${ro.serialno}
    write /config/usb_gadget/g1/strings/0x409/manufacturer ${ro.product.manufacturer}
    write /config/usb_gadget/g1/strings/0x409/product ${ro.product.model}
    mkdir /config/usb_gadget/g1/functions/mass_storage.0
    mkdir /config/usb_gadget/g1/functions/ffs.mtp
    mkdir /config/usb_gadget/g1/functions/ffs.adb
    mkdir /config/usb_gadget/g1/functions/ffs.fastboot
    mkdir /config/usb_gadget/g1/configs/b.1 0770
    mkdir /config/usb_gadget/g1/configs/b.1/strings/0x409 0770
    write /config/usb_gadget/g1/configs/b.1/MaxPower 900
    write /config/usb_gadget/g1/os_desc/b_vendor_code 0x1
    write /config/usb_gadget/g1/os_desc/qw_sign "MSFT100"
    symlink /config/usb_gadget/g1/configs/b.1 /config/usb_gadget/g1/os_desc/b.1
    mkdir /dev/usb-ffs 0775 shell system
    mkdir /dev/usb-ffs/mtp
    mkdir /dev/usb-ffs/adb
    mkdir /dev/usb-ffs/fastboot
    mount functionfs mtp /dev/usb-ffs/mtp uid=1024,gid=1024,rmode=0770,fmode=0660
    mount functionfs adb /dev/usb-ffs/adb uid=2000,gid=1000,rmode=0770,fmode=0660
    mount functionfs fastboot /dev/usb-ffs/fastboot uid=1000,gid=1000,rmode=0770,fmode=0660
    setprop sys.usb.mtp.device_type 3
    setprop sys.usb.configfs 1

on property:ro.boot.usbcontroller=*
    setprop sys.usb.controller ${ro.boot.usbcontroller}
    write /sys/class/udc/${ro.boot.usbcontroller}/device/../mode peripheral

on property:sys.usb.config=none && property:sys.usb.configfs=1
    write /config/usb_gadget/g1/UDC "none"
    stop adbd
    stop fastbootd
    setprop sys.usb.ffs.ready 0
    setprop sys.usb.ffs.mtp.ready 0
    write /config/usb_gadget/g1/bDeviceClass 0
    write /config/usb_gadget/g1/bDeviceSubClass 0
    write /config/usb_gadget/g1/bDeviceProtocol 0
    rm /config/usb_gadget/g1/configs/b.1/f1
    rm /config/usb_gadget/g1/configs/b.1/f2
    rm /config/usb_gadget/g1/configs/b.1/f3
    setprop sys.usb.state ${sys.usb.config}

on property:init.svc.adbd=stopped
    setprop sys.usb.ffs.ready 0

on property:init.svc.fastbootd=stopped
    setprop sys.usb.ffs.ready 0

on property:sys.usb.config=adb && property:sys.usb.configfs=1
    stop fastbootd
    start adbd

on property:sys.usb.config=mtp,adb && property:sys.usb.configfs=1
    stop fastbootd
    start adbd

on property:sys.usb.ffs.ready=1 && property:sys.usb.config=adb && property:sys.usb.configfs=1
    write /config/usb_gadget/g1/UDC "none"
    rm /config/usb_gadget/g1/configs/b.1/f1
    rm /config/usb_gadget/g1/configs/b.1/f2
    rm /config/usb_gadget/g1/configs/b.1/f3
    write /config/usb_gadget/g1/configs/b.1/strings/0x409/configuration "adb"
    write /config/usb_gadget/g1/idVendor 0x18D1
    write /config/usb_gadget/g1/idProduct 0x4EE7
    symlink /config/usb_gadget/g1/functions/ffs.adb /config/usb_gadget/g1/configs/b.1/f1
    write /config/usb_gadget/g1/UDC ${sys.usb.controller}
    setprop sys.usb.state ${sys.usb.config}

on property:sys.usb.ffs.ready=1 && property:sys.usb.config=sideload && property:sys.usb.configfs=1
    write /config/usb_gadget/g1/UDC "none"
    rm /config/usb_gadget/g1/configs/b.1/f1
    rm /config/usb_gadget/g1/configs/b.1/f2
    rm /config/usb_gadget/g1/configs/b.1/f3
    write /config/usb_gadget/g1/configs/b.1/strings/0x409/configuration "adb"
    write /config/usb_gadget/g1/idVendor 0x18D1
    write /config/usb_gadget/g1/idProduct 0x4EE7
    symlink /config/usb_gadget/g1/functions/ffs.adb /config/usb_gadget/g1/configs/b.1/f1
    write /config/usb_gadget/g1/UDC ${sys.usb.controller}
    setprop sys.usb.state ${sys.usb.config}

on property:sys.usb.config=mtp && property:sys.usb.configfs=1
    stop adbd
    stop fastbootd
    write /config/usb_gadget/g1/UDC "none"
    rm /config/usb_gadget/g1/configs/b.1/f1
    rm /config/usb_gadget/g1/configs/b.1/f2
    rm /config/usb_gadget/g1/configs/b.1/f3
    write /config/usb_gadget/g1/configs/b.1/strings/0x409/configuration "mtp"
    write /config/usb_gadget/g1/idVendor 0x2717
    write /config/usb_gadget/g1/idProduct 0xFF40
    symlink /config/usb_gadget/g1/functions/ffs.mtp /config/usb_gadget/g1/configs/b.1/f1
    write /config/usb_gadget/g1/UDC ${sys.usb.controller}
    setprop sys.usb.state ${sys.usb.config}

on property:sys.usb.ffs.ready=1 && property:sys.usb.config=mtp,adb && property:sys.usb.configfs=1
    write /config/usb_gadget/g1/UDC "none"
    rm /config/usb_gadget/g1/configs/b.1/f1
    rm /config/usb_gadget/g1/configs/b.1/f2
    rm /config/usb_gadget/g1/configs/b.1/f3
    write /config/usb_gadget/g1/configs/b.1/strings/0x409/configuration "mtp_adb"
    write /config/usb_gadget/g1/idVendor 0x2717
    write /config/usb_gadget/g1/idProduct 0xFF48
    symlink /config/usb_gadget/g1/functions/ffs.mtp /config/usb_gadget/g1/configs/b.1/f1
    symlink /config/usb_gadget/g1/functions/ffs.adb /config/usb_gadget/g1/configs/b.1/f2
    write /config/usb_gadget/g1/UDC ${sys.usb.controller}
    setprop sys.usb.state ${sys.usb.config}

on property:sys.usb.ffs.ready=1 && property:sys.usb.config=fastboot && property:sys.usb.configfs=1
    write /config/usb_gadget/g1/UDC "none"
    rm /config/usb_gadget/g1/configs/b.1/f1
    rm /config/usb_gadget/g1/configs/b.1/f2
    rm /config/usb_gadget/g1/configs/b.1/f3
    write /config/usb_gadget/g1/configs/b.1/strings/0x409/configuration "fastboot"
    write /config/usb_gadget/g1/idVendor 0x18D1
    write /config/usb_gadget/g1/idProduct 0xD00D
    symlink /config/usb_gadget/g1/functions/ffs.fastboot /config/usb_gadget/g1/configs/b.1/f1
    write /config/usb_gadget/g1/UDC ${sys.usb.controller}
    setprop sys.usb.state ${sys.usb.config}
"""


def parse_cpio(raw: bytes) -> list[tuple[dict, str, bytes]]:
    entries = []
    pos = 0
    while pos < len(raw):
        while pos < len(raw) and raw[pos : pos + 1] == b"\x00":
            pos += 1
        if pos >= len(raw):
            break
        assert raw[pos : pos + 6] == b"070701", f"Bad CPIO magic at {pos}"
        hdr = raw[pos : pos + 110]
        fields = {
            "ino": int(hdr[6:14], 16),
            "mode": int(hdr[14:22], 16),
            "uid": int(hdr[22:30], 16),
            "gid": int(hdr[30:38], 16),
            "nlink": int(hdr[38:46], 16),
            "mtime": int(hdr[46:54], 16),
            "filesize": int(hdr[54:62], 16),
            "devmajor": int(hdr[62:70], 16),
            "devminor": int(hdr[70:78], 16),
            "rdevmajor": int(hdr[78:86], 16),
            "rdevminor": int(hdr[86:94], 16),
            "namesize": int(hdr[94:102], 16),
            "check": int(hdr[102:110], 16),
        }
        ns = pos + 110
        name = raw[ns : ns + fields["namesize"] - 1].decode("utf-8", "surrogateescape")
        ds = (ns + fields["namesize"] + 3) & ~3
        data = raw[ds : ds + fields["filesize"]]
        pos = (ds + fields["filesize"] + 3) & ~3
        if name == "TRAILER!!!":
            break
        entries.append((fields, name, data))
    return entries


def build_cpio(entries: list[tuple[dict, str, bytes]]) -> bytes:
    chunks = []
    next_ino = max((e[0]["ino"] for e in entries), default=1) + 1
    for fields, name, data in entries:
        nb = name.encode("utf-8", "surrogateescape") + b"\x00"
        f = dict(fields)
        if f.get("ino", 0) == 0:
            f["ino"] = next_ino
            next_ino += 1
        f["namesize"] = len(nb)
        f["filesize"] = len(data)
        hdr = (
            f"070701"
            f"{f['ino']:08x}{f['mode']:08x}{f['uid']:08x}{f['gid']:08x}"
            f"{f['nlink']:08x}{f['mtime']:08x}{f['filesize']:08x}"
            f"{f['devmajor']:08x}{f['devminor']:08x}{f['rdevmajor']:08x}"
            f"{f['rdevminor']:08x}{f['namesize']:08x}{f['check']:08x}"
        ).encode("ascii")
        chunks.append(hdr + nb)
        pad1 = (-(len(hdr) + len(nb))) & 3
        if pad1:
            chunks.append(b"\x00" * pad1)
        chunks.append(data)
        pad2 = (-len(data)) & 3
        if pad2:
            chunks.append(b"\x00" * pad2)

    tb = b"TRAILER!!!\x00"
    thdr = (
        f"070701"
        f"00000000000000000000000000000000"
        f"000000010000000000000000"
        f"000000000000000000000000"
        f"00000000{len(tb):08x}00000000"
    ).encode("ascii")
    chunks.append(thdr + tb)
    total = sum(len(c) for c in chunks)
    pad_end = (-total) & 511
    if pad_end:
        chunks.append(b"\x00" * pad_end)
    return b"".join(chunks)


def patch_init_rc(txt: str) -> str:
    # 1. Replace fastbootd trigger with clean prep-fastbootd synchronous unmap
    old_fb_block = (
        "service fastbootd /system/bin/fastbootd\n"
        "    disabled\n"
        "    group system\n"
        "    seclabel u:r:fastbootd:s0\n"
    )
    new_fb_block = (
        "service prep-fastbootd /sbin/sh /system/bin/prep-fastbootd.sh\n"
        "    user root\n"
        "    group root system\n"
        "    oneshot\n"
        "    disabled\n"
        "    seclabel u:r:recovery:s0\n\n"
        "service fastbootd /system/bin/fastbootd\n"
        "    disabled\n"
        "    group system\n"
        "    seclabel u:r:fastbootd:s0\n"
    )
    assert old_fb_block in txt, "service fastbootd block not found"
    txt = txt.replace(old_fb_block, new_fb_block, 1)

    old_prop_fb = "on property:sys.usb.config=fastboot\n    start fastbootd\n"
    new_prop_fb = (
        "on property:sys.usb.config=fastboot\n"
        "    write /config/usb_gadget/g1/UDC \"none\"\n"
        "    stop adbd\n"
        "    setprop sys.usb.ffs.ready 0\n"
        "    exec_start prep-fastbootd\n"
        "    start fastbootd\n"
    )
    assert old_prop_fb in txt, "on property:sys.usb.config=fastboot not found"
    txt = txt.replace(old_prop_fb, new_prop_fb, 1)

    # 2. Remove conflicting ConfigFS mount/ffs/triggers from hw/init.rc so
    # init.recovery.usb.rc is the single authoritative owner.
    old_onfs_cfg = (
        "on fs && property:sys.usb.configfs=1\n"
        "    mount configfs none /config\n"
        "    mkdir /config/usb_gadget/g1 0770 shell shell\n"
        "    write /config/usb_gadget/g1/idVendor 0x${ro.recovery.usb.vid}\n"
        "    mkdir /config/usb_gadget/g1/strings/0x409 0770\n"
        "    write /config/usb_gadget/g1/strings/0x409/serialnumber ${ro.serialno}\n"
        "    write /config/usb_gadget/g1/strings/0x409/manufacturer ${ro.product.manufacturer}\n"
        "    write /config/usb_gadget/g1/strings/0x409/product ${ro.product.model}\n"
        "    mkdir /config/usb_gadget/g1/functions/ffs.adb\n"
        "    mkdir /config/usb_gadget/g1/functions/ffs.fastboot\n"
        "    mkdir /config/usb_gadget/g1/configs/b.1 0777 shell shell\n"
        "    # Set current limit to 900mA (b/277022505)\n"
        "    write /config/usb_gadget/g1/configs/b.1/MaxPower 0x384\n"
        "    mkdir /config/usb_gadget/g1/configs/b.1/strings/0x409 0770 shell shell\n\n"
    )
    assert old_onfs_cfg in txt, "on fs configfs=1 block not found"
    txt = txt.replace(old_onfs_cfg, "", 1)

    old_onfs_ffs = (
        "on fs\n"
        "    mount pstore pstore /sys/fs/pstore\n"
        "    mkdir /dev/usb-ffs 0770 shell shell\n"
        "    mkdir /dev/usb-ffs/adb 0770 shell shell\n"
        "    mount functionfs adb /dev/usb-ffs/adb uid=2000,gid=2000\n"
        "    mkdir /dev/usb-ffs/fastboot 0770 system system\n"
        "    mount functionfs fastboot /dev/usb-ffs/fastboot rmode=0770,fmode=0660,uid=1000,gid=1000\n"
    )
    new_onfs_ffs = "on fs\n    mount pstore pstore /sys/fs/pstore\n"
    assert old_onfs_ffs in txt, "on fs ffs block not found"
    txt = txt.replace(old_onfs_ffs, new_onfs_ffs, 1)

    marker = "# Configfs triggers\n"
    assert marker in txt, "# Configfs triggers marker not found"
    txt = txt[: txt.index(marker)].rstrip() + "\n"
    return txt


def patch_twrp_flags(txt: str) -> str:
    old_persist = '/persist            ext4      /dev/block/by-name/persist                                            flags=display="persist";fsflags=ro,noload'
    new_persist = '/persist            ext4      /dev/block/by-name/persist                                            flags=display="persist"'
    assert old_persist in txt, "twrp.flags /persist not found"
    txt = txt.replace(old_persist, new_persist, 1)

    old_boot = '/boot               emmc      /dev/block/by-name/boot                                               flags=display="boot";slotselect;backup=1;flashimg=1\n'
    new_boot = (
        old_boot
        + '/init_boot          emmc      /dev/block/by-name/init_boot                                          flags=display="init_boot";slotselect;backup=1;flashimg=1\n'
    )
    assert old_boot in txt, "twrp.flags /boot not found"
    txt = txt.replace(old_boot, new_boot, 1)

    old_otg = '/usb_otg            auto  /dev/block/sda1 /dev/block/sda /dev/block/sdd1 flags=display="USB-OTG";storage;wipeingui;removable'
    new_otg = '/usb_otg            auto  /dev/block/sdd1 /dev/block/sdd /dev/block/sde1 /dev/block/sde flags=display="USB-OTG";storage;wipeingui;removable'
    assert old_otg in txt, "twrp.flags /usb_otg not found"
    txt = txt.replace(old_otg, new_otg, 1)

    old_prod_img = '/product_image      emmc      /dev/block/mapper/product                                              flags=display="Product Image";slotselect;backup;flashimg'
    new_prod_img = (
        old_prod_img
        + '\n/mi_ext_image       emmc      /dev/block/mapper/mi_ext                                               flags=display="Mi_EXT Image";slotselect;backup;flashimg'
        + '\n/odm_image          emmc      /dev/block/mapper/odm                                                  flags=display="ODM Image";slotselect;backup;flashimg'
    )
    assert old_prod_img in txt, "twrp.flags /product_image not found"
    txt = txt.replace(old_prod_img, new_prod_img, 1)
    return txt


def patch_recovery_fstab(txt: str) -> str:
    dup_mi_ext = "mi_ext                                                 /mnt/vendor/mi_ext     ext4    ro                                                  wait,slotselect,logical,first_stage_mount,nofail\n"
    assert dup_mi_ext in txt, "duplicate mi_ext ext4 line not found"
    return txt.replace(dup_mi_ext, "", 1)


def patch_prop_default(txt: str) -> str:
    replacements = [
        ("ro.build.version.release=14\n", "ro.build.version.release=17\n"),
        ("ro.build.version.release_or_codename=14\n", "ro.build.version.release_or_codename=17\n"),
        ("ro.build.version.release_or_preview_display=14\n", "ro.build.version.release_or_preview_display=17\n"),
        ("ro.build.version.security_patch=2024-09-05\n", "ro.build.version.security_patch=2026-10-01\n"),
        (
            "ro.vendor.build.security_patch=\n",
            "ro.vendor.build.security_patch=2026-10-01\nro.vendor.build.version.release=15\n",
        ),
    ]
    for old, new in replacements:
        assert old in txt, f"prop.default missing: {old!r}"
        txt = txt.replace(old, new, 1)
    return txt


def main() -> None:
    subprocess.run(["rm", "-rf", str(OUT_DIR)], check=True)
    OUT_DIR.mkdir(parents=True)
    p_dir = OUT_DIR / "ported"
    s_dir = OUT_DIR / "stock"
    p_dir.mkdir()
    s_dir.mkdir()

    subprocess.run(["unpack_bootimg", "--boot_img", str(PORTED_VBOOT), "--out", str(p_dir)], check=True)
    subprocess.run(["unpack_bootimg", "--boot_img", str(STOCK_VBOOT), "--out", str(s_dir)], check=True)

    # Verify stock ramdisk00 & dtb parity vs ported
    assert (p_dir / "dtb").read_bytes() == (s_dir / "dtb").read_bytes(), "DTB mismatch!"

    raw_cpio = subprocess.check_output(["lz4", "-dc", str(p_dir / "vendor_ramdisk01")])
    entries = parse_cpio(raw_cpio)
    by_name = {name: i for i, (_, name, _) in enumerate(entries)}

    def update_file(name: str, new_bytes: bytes) -> None:
        idx = by_name[name]
        f, n, _ = entries[idx]
        entries[idx] = (f, n, new_bytes)
        print(f"Patched: {name} ({len(new_bytes)} B)")

    def add_file(name: str, new_bytes: bytes, mode: int) -> None:
        if name in by_name:
            update_file(name, new_bytes)
            return
        fields = {
            "ino": 0,
            "mode": mode,
            "uid": 0,
            "gid": 0,
            "nlink": 1,
            "mtime": 0,
            "filesize": len(new_bytes),
            "devmajor": 0,
            "devminor": 0,
            "rdevmajor": 0,
            "rdevminor": 0,
            "namesize": 0,
            "check": 0,
        }
        entries.append((fields, name, new_bytes))
        by_name[name] = len(entries) - 1
        print(f"Added: {name} (mode={oct(mode)}, {len(new_bytes)} B)")

    # 1. init.recovery.mt6899.rc -> import /init.recovery.project.rc
    rc_mt = entries[by_name["init.recovery.mt6899.rc"]][2].decode("utf-8")
    assert "import /init.recovery.project.rc" not in rc_mt
    rc_mt = rc_mt.replace(
        "import /init.recovery.keymint.rc\n",
        "import /init.recovery.keymint.rc\nimport /init.recovery.project.rc\n",
        1,
    )
    update_file("init.recovery.mt6899.rc", rc_mt.encode("utf-8"))

    # 2. init.recovery.keymint.rc -> mount persist rw
    rc_km = entries[by_name["init.recovery.keymint.rc"]][2].decode("utf-8")
    old_km_mount = "mount ext4 /dev/block/by-name/persist /mnt/vendor/persist ro noatime nosuid nodev wait noload"
    new_km_mount = "mount ext4 /dev/block/by-name/persist /mnt/vendor/persist rw noatime nosuid nodev wait"
    assert old_km_mount in rc_km
    rc_km = rc_km.replace(old_km_mount, new_km_mount, 1)
    update_file("init.recovery.keymint.rc", rc_km.encode("utf-8"))

    # 3. klee_fbe_prep.sh -> also remount /persist rw
    fbe_sh = entries[by_name["system/bin/klee_fbe_prep.sh"]][2].decode("utf-8")
    old_fbe = "mount -o remount,rw /mnt/vendor/persist 2>/dev/null\n"
    new_fbe = old_fbe + "mount -o remount,rw /persist 2>/dev/null\n"
    assert old_fbe in fbe_sh
    update_file("system/bin/klee_fbe_prep.sh", fbe_sh.replace(old_fbe, new_fbe, 1).encode("utf-8"))

    # 4. system/etc/twrp.flags & system/etc/recovery.fstab
    flags_txt = entries[by_name["system/etc/twrp.flags"]][2].decode("utf-8")
    update_file("system/etc/twrp.flags", patch_twrp_flags(flags_txt).encode("utf-8"))

    rec_fstab = entries[by_name["system/etc/recovery.fstab"]][2].decode("utf-8")
    update_file("system/etc/recovery.fstab", patch_recovery_fstab(rec_fstab).encode("utf-8"))

    # 5. system/etc/init/hw/init.rc + init.recovery.usb.rc + system/bin/prep-fastbootd.sh
    hw_init = entries[by_name["system/etc/init/hw/init.rc"]][2].decode("utf-8")
    update_file("system/etc/init/hw/init.rc", patch_init_rc(hw_init).encode("utf-8"))
    update_file("init.recovery.usb.rc", INIT_RECOVERY_USB_RC.encode("utf-8"))
    add_file("system/bin/prep-fastbootd.sh", PREP_FASTBOOTD_SH.encode("utf-8"), 0o100755)

    # 6. Clean root /fstab.mt6899 (from first_stage_ramdisk/fstab.emmc)
    emmc_fstab = entries[by_name["first_stage_ramdisk/fstab.emmc"]][2]
    add_file("fstab.mt6899", emmc_fstab, 0o100644)

    # 7. Align prop.default OS release / security_patch with OS4.0.7.0 (Android 17 / vendor 15 / 2026-10-01)
    prop_txt = entries[by_name["prop.default"]][2].decode("utf-8")
    update_file("prop.default", patch_prop_default(prop_txt).encode("utf-8"))

    new_cpio = build_cpio(entries)
    new_cpio_path = OUT_DIR / "new_ramdisk01.cpio"
    new_lz4_path = OUT_DIR / "vendor_ramdisk01.lz4"
    new_cpio_path.write_bytes(new_cpio)
    subprocess.run(["lz4", "-l", "-12", "-f", str(new_cpio_path), str(new_lz4_path)], check=True)
    print(f"Rebuilt CPIO: {len(new_cpio)} B -> LZ4 legacy: {new_lz4_path.stat().st_size} B")

    raw_vboot = OUT_DIR / "vendor_boot_raw.img"
    subprocess.run(
        [
            "mkbootimg",
            "--header_version", "4",
            "--pagesize", "0x00001000",
            "--base", "0x00000000",
            "--kernel_offset", "0x40000000",
            "--ramdisk_offset", "0x66f00000",
            "--tags_offset", "0x47c80000",
            "--dtb_offset", "0x0000000047c80000",
            "--vendor_cmdline", "bootopt=64S3,32N2,64N2 erofs.reserved_pages=64",
            "--board", "",
            "--dtb", str(s_dir / "dtb"),
            "--vendor_bootconfig", str(p_dir / "bootconfig"),
            "--ramdisk_type", "1",
            "--ramdisk_name", "",
            "--vendor_ramdisk_fragment", str(p_dir / "vendor_ramdisk00"),
            "--ramdisk_type", "2",
            "--ramdisk_name", "recovery",
            "--vendor_ramdisk_fragment", str(new_lz4_path),
            "--vendor_boot", str(raw_vboot),
        ],
        check=True,
    )

    subprocess.run(
        [
            "avbtool",
            "add_hash_footer",
            "--image", str(raw_vboot),
            "--partition_name", "vendor_boot",
            "--partition_size", "67108864",
            "--prop", "com.android.build.vendor_boot.fingerprint:alps/hal_mgvi_64_64only_armv82/mgvi_64_64only_armv82:15/AP3A.240905.015.A2/OS4.0.7.0.XPJEU:user/release-keys",
        ],
        check=True,
    )

    assert raw_vboot.stat().st_size == 67108864, f"Unexpected size: {raw_vboot.stat().st_size}"
    data = raw_vboot.read_bytes()
    OUT_IMG.write_bytes(data)
    sha = hashlib.sha256(data).hexdigest()
    print(f"Wrote {OUT_IMG} ({len(data)} B), SHA-256: {sha}")

    # Verify with unpack_bootimg + avbtool info_image + cpio parse
    chk_dir = OUT_DIR / "verify"
    chk_dir.mkdir()
    subprocess.run(["unpack_bootimg", "--boot_img", str(OUT_IMG), "--out", str(chk_dir)], check=True)
    re_cpio = subprocess.check_output(["lz4", "-dc", str(chk_dir / "vendor_ramdisk01")])
    re_entries = parse_cpio(re_cpio)
    print(f"Verified round-trip CPIO entries: {len(re_entries)} (expected {len(entries)})")
    assert len(re_entries) == len(entries)
    subprocess.run(["avbtool", "info_image", "--image", str(OUT_IMG)], check=True)


if __name__ == "__main__":
    main()
