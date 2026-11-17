# OrangeFox R12.0 (`klee`) — Düzeltilmiş Recovery Ramdisk & `vendor_boot` İmajı

POCO X8 Pro / Redmi Turbo 5 (`klee`, MT6899) için **OrangeFox R12.0 (`5d47f659`)** recovery yamalarını ve derleme betiğini içerir.

## Dosyalar
- **`ofox_r12_klee_recovery_ramdisk.lz4`** (`32.556.129` B, LZ4 legacy CPIO):
  - Yalnızca `vendor_ramdisk01` (`type=recovery`) fragmentidir.
  - Başka geliştiricilerin kendi ROM'larının `vendor_boot.img` (`vendor_ramdisk00` + `dtb`) yapısına `mkbootimg --header_version 4` ile enjekte etmesi için çıkarılmıştır.
- **`OrangeFox-R12.0-klee-OS4.0.7-fixed.img`** (`67.108.864` B):
  - `OS4.0.7.0.XPJEUXM` stok `vendor_ramdisk00` + `dtb` ile paketlenmiş, doğrudan `vendor_boot_a`/`vendor_boot_b` üzerine yazılabilir imaj.
- **`build_fixed_ofox.py`**: `vendor_ramdisk01` yamalarını otomatik uygulayıp `vendor_boot.img` paketleyen Python betiği.

## İndirme Bağlantıları (Google Drive)
- **`ofox_r12_klee_recovery_ramdisk.lz4`** (`32.556.129` B): https://drive.google.com/file/d/1ht35j7uJd6fcH4CFkghyIy1wE_30X-nA/view?usp=drivesdk
- **`OrangeFox-R12.0-klee-OS4.0.7-fixed.img`** (`67.108.864` B): https://drive.google.com/file/d/1EljlFDioPf1hHIndN5QNHJvRrfnfQKI8/view?usp=drivesdk

## Uygulanan Düzeltmeler
1. **MITEE KeyMint `-33` / `/data` Şifre Çözme Fixi**: `prop.default` değerleri Android 17 / SDK 37 / `2026-10-01` güvenlik yaması (`ro.vendor.build.security_patch=2026-10-01`, `ro.vendor.build.version.release=15`) ile eşitlendi; metadata + User 0 Weaver FBE sorunsuz çözülür.
2. **`/persist` Yazılabilirliği**: `ro,noload` kaldırıldı (wipe bayrakları eklenmedi); `/persist/.foxs` kalıcı kaydedilir.
3. **`fastbootd` & USB ConfigFS Fixi**: `prep-fastbootd.sh` + tekilleştirilmiş `init.recovery.usb.rc` ile `mtp,adb` (`2717:ff48`) ve `fastbootd` (9/9 dinamik bölüm) sorunsuz çalışır.
4. **`fstab` / `twrp.flags` / `init.recovery.mt6899.rc`**: `import /init.recovery.project.rc`, `/init_boot`, `/mi_ext_image`, `/odm_image`, temiz `/fstab.mt6899` ve güvenli `/usb_otg` (`sdd`/`sde`).

---

> [!CAUTION]
> **⚠️ UYARI — BU DOSYA `vendor_boot` DEĞİLDİR (SADECE GELİŞTİRİCİLER İÇİNDİR):**
> `ofox_r12_klee_recovery_ramdisk.lz4` dosyası tek başına bir `vendor_boot.img` veya `boot.img` **DEĞİLDİR**; doğrudan `fastboot flash` ile cihaza yazılmaz ve tek başına cihazı açmaz! Yalnızca geliştiricilerin kendi ROM sürümlerine ait `vendor_ramdisk00` ve `dtb` ile `mkbootimg` kullanarak yeni `vendor_boot.img` derlemesi içindir.
>
> Doğrudan `vendor_boot` bölümüne yazmak istiyorsanız yalnızca kendi sürümünüzle (`OS4.0.7.0.XPJEUXM`) eşleşen `OrangeFox-R12.0-klee-OS4.0.7-fixed.img` dosyasını kullanın.

---

## Teşekkürler / Credits
- **Kylixd** — `klee` için OrangeFox R12.0 temel derlemesi için.
