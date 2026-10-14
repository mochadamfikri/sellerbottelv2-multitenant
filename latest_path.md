# Laporan Status Terbaru — V3 Production / Tenant Payment

- **Dibuat**: 2026-10-15 01:16 WIB
- **Host**: `sellerbottel-prod` (`54.151.240.15`)
- **Ruang kerja source release**: `/tmp/v3-production-migrator-release`
- **Revision terakhir**: `561ce93` — Enforce platform settlement Kasera in production tenant UI
- **Revision sebelumnya**: `743c976` — Default new tenants to platform Kasera live
- **Secret**: Tidak ada API key, webhook secret, token Telegram, password, atau material enkripsi yang dicatat pada laporan ini.

## Status Runtime

| Komponen | Status | Bukti ringkas |
|---|---|---|
| V1 rollback service | Aktif | `sellerbottel.service` aktif pada `127.0.0.1:8000` |
| V3 backend | Aktif | `sellerbottel-v3.service` aktif pada `127.0.0.1:8001`; `GET /api/` memberi HTTP 200 |
| V3 bot dispatcher | Aktif | `sellerbottel-v3-bot.service` aktif |
| Nginx | Aktif | Service aktif |
| Kasera webhook | Siap menerima POST | URL `https://pay.idsepos.my.id/api/payments/webhooks/kasera`; pemeriksaan GET memberi HTTP 405, sesuai karena endpoint hanya menerima POST webhook bertanda tangan |
| Wildcard certificate | Terbit | `/etc/letsencrypt/live/sellerbottel-v3-wildcard/fullchain.pem` ada |

## Domain Aktif

- `idseshop.my.id`: storefront utama IDSE pada V3.
- `idsestock.my.id`: panel owner/platform IDSE.
- `*.idsestock.my.id`: panel tenant; contoh `dedekunstore.idsestock.my.id`.
- `idseconnect.my.id`: landing dan pendaftaran tenant.
- `*.idseconnect.my.id`: storefront tenant.
- `idsepos.my.id`: halaman checkout/pembayaran IDSE.
- `pay.idsepos.my.id`: ingress webhook Kasera Live.
- `idsedm.duckdns.org`: domain lama dipensiunkan dari fungsi panel aktif.

## Cloudflare API dan Wildcard SSL

- Fitur pengaturan Cloudflare tersedia pada `https://idsestock.my.id/settings`.
- Hanya platform owner yang dapat membaca atau menyimpan konfigurasi.
- API token diverifikasi terhadap Cloudflare dan kedua zone: `idsestock.my.id`, `idseconnect.my.id`.
- Token disimpan terenkripsi; panel hanya menampilkan status serta hint termasking.
- Plugin `python3-certbot-dns-cloudflare` telah terpasang.
- Wildcard certificate sudah tersedia untuk:
  - `idsestock.my.id` dan `*.idsestock.my.id`
  - `idseconnect.my.id` dan `*.idseconnect.my.id`
- Catatan UX: permintaan awal penerbitan certificate dapat memakan sekitar satu menit karena DNS challenge. Jika browser Cloudflare menampilkan timeout, jangan masukkan ulang token berulang kali; status certificate di server telah terverifikasi ada. Endpoint perlu dipisahkan menjadi proses background pada perbaikan UX berikutnya agar respons panel tidak menunggu certbot.

## Kasera dan Tenant Payment

### Konfigurasi platform

- Provider platform: **Kasera**.
- Environment platform: **Live**.
- Credential Kasera platform ada, terenkripsi, dan tidak dicabut.
- Capability terakhir yang tersimpan mencakup:
  - QRIS
  - Virtual Account BRI, BNI, Mandiri, Permata, CIMB Niaga, Danamon, dan Maybank
- Commerce maintenance terakhir terverifikasi: `false`.

### Perbaikan tenant baru

Masalah yang ditemukan pada tenant `dedekunstore`:

1. Database tenant belum memiliki dokumen `payment_settings`.
2. UI sebelumnya memakai fallback `mock` dan tombol `Test Connection` mencoba mencari credential gateway lokal tenant.
3. Ini menyebabkan pesan `Gateway credentials unavailable` atau `Payment mode not configured`.
4. Tenant sempat mengubah mode ke `Gateway Saya Sendiri` + `Sandbox` dan memasukkan API key Live; sistem menolak dengan benar karena Sandbox hanya menerima key `kp_test_...`.

Perbaikan yang dipasang:

- Tenant tanpa pengaturan lokal otomatis menggunakan `platform_settlement`.
- Provider efektif otomatis `kasera` dengan environment efektif `live` dari konfigurasi platform.
- Tombol `Test Connection` tenant baru memeriksa Kasera platform, bukan credential tenant kosong.
- Pada profil produksi `v1_kasera`, opsi `Gateway Saya Sendiri` disembunyikan dari panel tenant.
- Backend juga menolak paksa request self-gateway pada profil produksi untuk mencegah salah konfigurasi maupun pencampuran merchant.
- Panel tenant menampilkan keterangan bahwa:
  - checkout tenant memakai Kasera Live melalui IDSE;
  - tenant tidak memasukkan API key Kasera sendiri;
  - GoPay Merchant dipakai untuk deposit bot pusat IDSE, bukan checkout tenant.

### Verifikasi runtime `dedekunstore`

- `payment_mode`: `platform_settlement`
- `provider`: `kasera`
- `environment`: `live`
- `platform_configured`: `true`
- `Test Connection`: lulus
- Capability runtime: QRIS dan VA BRI, BNI, Mandiri, Permata, CIMB Niaga, Danamon, Maybank.

## Validasi yang Dijalankan

- Python compile untuk payment router dan orchestrator: lulus.
- Test regresi payment: `17 passed`.
- Frontend production build: lulus.
- `sellerbottel-v3.service`: direstart setelah deploy dan kembali aktif.
- V1 tetap aktif dan tidak diubah.

## Tindakan Pengguna Setelah Ini

1. Di panel tenant, lakukan refresh penuh browser atau buka ulang halaman `?tab=payments`.
2. Pastikan mode hanya tampil sebagai **Settlement IDSE — Kasera Live**.
3. Jangan isi API key atau webhook secret Kasera pada panel tenant.
4. Jangan gunakan menu lama GoPay Merchant untuk checkout tenant; menu itu khusus deposit bot pusat IDSE.

## Riwayat Laporan Sebelumnya

- `real_laporan.md`
- `docs/audits/v3-final-cutover-success-codex9-20261012-1100WIB.md`
- `docs/audits/v3-production-migrator-codex9-20261012-0221WIB.md`
- `docs/audits/v3-production-migration-internal-v3-codex9-20261012-0221WIB.md`
