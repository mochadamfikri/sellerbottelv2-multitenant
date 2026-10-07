# IDSE Marketplace / sellerbottel — handover untuk Hermes, Codex, dan agent lain

Terakhir diperbarui: 28 September 2026 (UTC). Dokumen ini adalah titik masuk untuk
melanjutkan pekerjaan, bukan permintaan untuk mereset atau membangun ulang sistem.
Bahasa komunikasi pemilik: Indonesia. Kerjakan perubahan sampai teruji dan jelas
status deployment-nya; jangan menyebut selesai jika hanya mengubah source.

## 1. Status yang perlu dipahami lebih dahulu

- Repository sekaligus instalasi production: `/opt/sellerbottel`.
- Storefront: https://idseshop.my.id/store ; host lain: `idsedm.duckdns.org`.
- Revisi storefront/admin terakhir sudah dipasang. Build yang diverifikasi:
  `main.86a3cfa3.js`, CSS `main.e7a9b64a.css` (upgrade saldo + campaign).
- Branch `main`, commit dasar `9692069`. **Banyak perubahan terbaru masih dirty
  atau untracked**. Commit Git saja tidak mewakili aplikasi yang berjalan.
  Jangan `git reset --hard`, `git clean`, atau menimpa checkout ini.
- Frontend disajikan dari `frontend/build`; backend systemd `sellerbottel` berjalan
  dari `backend`, Uvicorn `server:app` di `127.0.0.1:8000`; Nginx proxy `/api/`.
- MongoDB container `sellerbottel-mongodb`, image `mongo:7.0`, database `sellerbottel`.
- Bot utama telah memakai katalog. Kode bot kedua sudah disesuaikan, tetapi saat
  rilis sebelumnya bot kedua tidak aktif/token belum disediakan. Periksa konfigurasi
  terkini sebelum mengklaim bot kedua berjalan.
- Konfigurasi bisnis bisa diubah pemilik melalui admin. Jangan mengembalikan nilai
  pengaturan ke default hanya berdasarkan dokumen ini.

## 2. Aturan menjaga production

1. Audit source dan working tree terlebih dahulu; utamakan extension/refactor.
2. Backup source lengkap termasuk untracked, build, `.env`, dan database sebelum
   perubahan production. Database harus mencakup nilai dokumen, bukan hanya schema.
3. Pertahankan ID produk, inventory, order/invoice, transaksi, deposit, akun, saldo,
   relasi Telegram, dan `settings.stats_reset_at`. Jangan reset/reseed database.
4. Jangan mengganti `INVENTORY_ENCRYPTION_KEY` atau `TG_SESSION_KEY`: data lama
   membutuhkan kunci asli. Rahasia hanya di konfigurasi/backup privat, tidak di MD,
   screenshot, output terminal, commit, atau aset frontend.
5. Tes backend **wajib melalui runner offline** di bawah. Jangan memakai database
   production untuk fixture/tes. Jangan menjalankan test lama sembarangan.
6. Pembelian, broadcast, kick/block, dan pembayaran sungguhan bukan smoke test.
7. Restore diuji ke lingkungan terisolasi dahulu. Jangan menjalankan `--drop` ke
   database production hanya untuk memverifikasi backup.
8. Cocokkan ID/hash dokumen, jumlah, dan agregat keuangan sebelum/sesudah rilis.
   Selisih akibat transaksi sah harus direkonsiliasi, tidak ditimpa backup lama.

## Hotfix terbaru — sumber broadcast transaksi asli

Hotfix backend setelah upgradeversi: channel order baru disimpan sebagai
`purchases.purchase_source = WEB/BOT`. Checkout storefront saldo mengirim parameter
WEB eksplisit ke execute_checkout; default jalur bot adalah BOT. QRIS storefront,
bot utama, dan bot kedua menyimpan sumber eksplisit pada order masing-masing.
Jangan memakai telegram_id, customer_id, registration source atau traffic source
untuk menebak channel checkout.

Broadcast sukses: `🌐 Penjualan Web` / `🤖 Penjualan Bot`, beserta `Sumber: WEB/BOT`.
WEB tanpa Telegram tidak menampilkan placeholder identitas. WEB linked tetap WEB;
identitas linked dan identitas BOT dimasking pada output saja. Kartu gambar
PENJUALAN BERHASIL dan campaign PROMO IDSE tidak diubah.

Resolver di backend/telegram_identity.py mendahulukan purchase_source. Untuk order
lama, payment_scope store/bot1/bot2, flag bot2/reseller_bot_id, atau kombinasi
customer_id + idempotency_key khusus checkout storefront dipakai sebagai bukti
jalur creation. Jika metadata lama ambigu, tampilkan sumber TIDAK DIKETAHUI dan
header Penjualan netral, jangan menganggap pengguna Telegram pasti membeli via bot.
Tidak ada backfill atau perubahan nilai order lama. Invoice contoh
INV-20260929-0001 terdeteksi WEB dari metadata checkout lamanya.

Tes offline hotfix: 49 PASS. Command dari backend:
`./venv/bin/python run_offline_tests.py tests/test_purchase_source.py tests/test_upgradeversi.py tests/test_direct_checkout.py tests/test_catalog_delivery_flow.py -q`.
Mencakup lima acceptance cases, source persisten pada saldo/QRIS, identity privacy,
fallback legacy, regresi checkout/campaign dan image passthrough. Log:
`/tmp/idse-source-hotfix-tests.log`. Backup sebelum edit:
`backups/handover-20260928T192949Z` (full values + isolated restore verified).
Frontend tidak berubah; build frontend sebelumnya tetap dipakai.

## Tambahan terbaru — upgradeversi.md (28 September 2026)

Sudah implemented dan deployed; detail serta perintah tes ada di
[laporan upgrade](docs/upgradeversi-release-20260928.md).

- Pengguna → ikon saldo kini bekerja untuk WEB, BOT, dan akun tertaut. Tambah/kurang
  IDR/USD, catatan wajib, audit sebelum/sesudah, admin actor, request ID idempoten,
  dan riwayat manual terpisah dari deposit. Search mencakup ID internal.
- Wallet tetap pada bot_users/store_customers. Akun tertaut menggunakan wallet bot.
  Mongo standalone tidak mendukung transaksi multi-dokumen: saldo dan receipt audit
  disimpan atomik pada dokumen akun, lalu ledger balance_adjustments diproyeksikan
  idempoten. Worker memperbaiki proyeksi yang tertunda. Jangan menghapus field
  admin_balance_audit; itu bukti durable dan receipt retry.
- Broadcast transaksi asli menyertakan ID Telegram first3/last2 dan username first2
  yang dimasking. Identitas asli di database tidak berubah; tidak dibuat identitas
  palsu. Campaign promosi tidak memanggil notifikasi transaksi.
- Broadcast → Campaign Promo Otomatis: tujuan terkonfigurasi, nama, interval acak
  1–10.080 menit, 1–500 pesan, semua/pilihan produk inventory, progres, log event,
  Pause/Resume/Stop. Tidak ada campaign yang dibuat/dikirim sungguhan saat deployment.
- Campaign disimpan di broadcasts(kind=marketing_campaign), event tertanam dengan
  ID tetap, worker startup async persisten melalui DB (poll 15 detik), lease 3 menit.
  Status sending yang tertinggal saat restart atau timeout ditahan sebagai unknown;
  Telegram tidak menyediakan idempotency key. Periksa channel lalu konfirmasi ID
  pesan yang memang terkirim, atau Stop. Jangan otomatis mengirim ulang unknown.
- Satu item actual inventory dialokasikan sebagai marketing_allocated per event;
  tidak mengubah sold/purchases/revenue/deposit/balance. Batas stok manual ikut
  memperhitungkan alokasi. Reserved/sold tidak diambil. Jasa tanpa inventory tidak
  dipilih karena tidak mempunyai unit inventory untuk alokasi.
- Ledger stok menggunakan stock_events event_type OWNER_MARKETING_ALLOCATION/RESTORE,
  status recorded (bukan antrean notifikasi). Receipt stock juga tertanam atomik
  pada inventory.marketing_audit. Restore 1/semua tersedia pada detail campaign.
  Event yang belum terkirim perlu Stop dahulu sebelum alokasinya bisa dipulihkan;
  retry kegagalan Telegram memakai unit yang sama. Restore tidak bisa menggandakan stok.
- Migrasi hanya 2 index tambahan: inventory marketing.event_id unique partial dan
  broadcasts(kind,status,next_scheduled_at). Tidak ada reset, konversi ID, atau
  pengubahan nilai historis. Index dikelola ensure_indexes seperti sebelumnya.
- File inti: backend/balance_admin.py, telegram_identity.py, marketing_campaigns.py;
  frontend/src/components/BalanceAdjustment.jsx, MarketingCampaigns.jsx. Terintegrasi
  dengan admin_routes/admin_user_routes/services/checkout/stock_monitor/db/server dan
  halaman Users/Broadcasts/Inventory; tidak merombak storefront sebelumnya.
- Validasi upgrade: 51 tes backend targeted PASS, browser WEB add/BOT subtract/audit/
  filters/campaign/pause/resume/stop PASS, build PASS. Snapshot seluruh dokumen sebelum
  dan sesudah deployment identik; semua agregat saldo/order/deposit dan cutoff statistik
  sama. Bukti sementara `/tmp/idse-upgrade-{before,after}.json`,
  `/tmp/idse-upgrade-final-tests.log`, `/tmp/idse-upgrade-ui/report.json`.

## 3. Fitur yang sudah diterapkan

| Area | Perilaku sekarang |
| --- | --- |
| Katalog | Produk dikelompokkan dalam katalog; katalog Claude memuat varian 1/3/6 bulan sesuai produk yang benar-benar tersedia. Katalog eksplisit atau inferensi nama lama. Varian tetap produk dengan ID sendiri, bukan schema varian baru. |
| Bot | Menu Katalog Produk → katalog → varian, pagination maksimal 8 pilihan. Tombol stok mengarah ke katalog. Callback memakai ID stabil. |
| Admin katalog | `/catalogs`: buat, rename, pindahkan produk massal, hapus katalog tanpa menghapus produk/inventory/riwayat; produk dialihkan ke Produk Lainnya. |
| Produk/import | `/products`: katalog, filter/search, jenis inventory/jasa, schema inventory, foto upload/otomatis, import manual/XLSX/CSV/TXT, template diperbarui. |
| Inventory | `/inventory`: kelompok katalog, preview/validasi/import, template sesuai produk, pagination, edit/hapus satu item dan penggantian file session. Item reserved/terjual dilindungi dari edit/hapus. |
| Gambar produk | Fallback otomatis berbasis logo lokal, nama plan PRO/TRIAL/PLUS/PREMIUM/MAX dan durasi. Upload foto menggantikan fallback; hapus upload mengembalikan fallback. Merek tanpa aset memakai inisial katalog. |
| Broadcast | `/broadcasts`, `/central-broadcasts`: preview, pilihan produk/katalog, target pengguna/channel/grup, judul poster, gambar otomatis/teks, download poster, riwayat, pembatalan sisa antrean. |
| Target broadcast | `/settings`: tujuan umum, transaksi sukses, dan rekap terpisah; nilai lama menjadi fallback bila target khusus kosong. |
| Tindak lanjut | `/bot-moderation`: OFF atau auto-kick channel + silent block akses bot. Berjalan setelah order delivered/completed, bukan sekadar bayar; order jasa harus diselesaikan. Order lain yang masih berjalan menunda tindakan. |
| Pengecualian | Tindak lanjut mendukung pengecualian ID Telegram, reseller, katalog, produk. Rename/hapus katalog mempertahankan pengecualian. Tindakan manual tetap tersedia terpisah. Jangan mengaktifkan mode otomatis tanpa instruksi bisnis pemilik. |
| Beranda storefront | Katalog, pencarian, rekomendasi produk tersedia/harga asli, dan panduan pembelian; tidak memakai statistik penjualan fiktif. |
| Detail produk | Popup/modal blur, varian/durasi/harga/stok/jumlah/subtotal, keyboard/focus trap/Escape/X. URL `/store/product/:id` tetap bekerja, termasuk tautan langsung. Varian habis dapat dilihat tetapi tidak ditambahkan. |
| Navigasi/tema | Menu mobile berikon dan deskripsi, indikator aktif, keranjang/akun. Auto/light/dark disimpan di browser dan berlaku pada portal modal. Judul tab dan logo IDSE Marketplace. |
| Keranjang | Struktur lama `localStorage.store_cart` tetap `{pid,qty}`. Tombol tambah memutar/loading 5 detik, lalu notifikasi item masuk. Backend tetap menghitung ulang harga/stok/diskon. |
| Checkout | Popup pemrosesan dengan gambar keranjang berputar, centang hanya setelah order selesai, otomatis tutup 10 detik atau X. QRIS menunggu status berhasil; bukan sukses palsu saat QR dibuat. |
| Detail order | Kredensial akun milik pelanggan dapat dilihat/diunduh TXT; file session dapat diunduh. Endpoint memeriksa kepemilikan/status dan memakai no-store untuk data rahasia. |
| Profil | `/store/profile`: edit nama tampilan dan nomor kontak opsional, simpan/batal. Email login tetap read-only. Link Telegram tetap tersedia. PATCH tidak menerima saldo/ID/email/password/session_version. |
| Admin pengguna | `/users`: filter Semua, Telegram saja, Website saja, Web + Telegram; pencarian dan pagination server. Akun tertaut tampil sekali dan order berkunci web+Telegram dihitung sekali. Filter sumber berarti keberadaan/tautan akun saat ini, bukan atribusi pemasaran historis. |

### Format produk dan inventory

Format produk (harga IDR; kolom sama pada XLSX/CSV):

```text
katalog|product|jenis (inventory/jasa)|Harga
Claude Pro|Claude Pro 1 bulan|inventory|100000
Claude Pro|Claude Pro 3 bulan|inventory|275000
Layanan|Jasa Payment|jasa|50000
```

Header lama tetap didukung. Template inventory mengikuti schema produk, misalnya
`email|password|recovery|2fa`, **bukan** empat kolom produk di atas. Normalisasi header
mengabaikan case/spasi, mengizinkan urutan kolom berbeda, dan meremap ke schema
kanonik. Nama field berbeda tidak diterjemahkan diam-diam. Produk tanpa schema
dapat menetapkan schema melalui upload valid pertama. Jasa tidak memakai inventory.

## 4. Peta teknis dan file utama

- Frontend React 19, React Router 7, CRA/CRACO, Tailwind, Lucide, Radix Dialog.
  Entry routing `frontend/src/App.js`; API client di `frontend/src/lib`.
- Backend FastAPI/Uvicorn, Pydantic, Python 3.12; Mongo via Motor/PyMongo, tanpa ORM
  relasional. Koneksi dan index: `backend/db.py`.
- Admin auth JWT HS256 + bcrypt, cookie `access_token`; pelanggan cookie HttpOnly
  `customer_access_token`, Secure/SameSite Lax, session_version dan OTP email.
- Saldo IDR/USD pada bot_users atau store_customers; penautan Telegram mempunyai
  wallet_merge idempoten. Jangan memicu merge atau memindahkan saldo lewat edit profil.
- Order/pembayaran memakai quote, idempotency, reservasi/commit inventory, penanda
  kredit deposit, dan status fulfillment. Riwayat transaksi mengambil order/deposit.
- Statistik dihitung dari purchases/deposits dengan cutoff stats_reset_at. Rumus
  statistik lama tidak diubah pada revisi UI ini; jangan berasumsi seluruh metrik
  otomatis hanya menghitung delivered.

| File/module | Tanggung jawab |
| --- | --- |
| `backend/product_catalog.py`, `catalog_routes.py` | Normalisasi katalog, grouping, CRUD admin |
| `backend/bulk_product_import.py`, `inventory_admin.py`, `inventory.py` | Import produk, CRUD/template inventory, schema dan enkripsi |
| `backend/product_artwork.py`, `assets/brands/README.md` | Gambar otomatis dan sumber logo |
| `backend/broadcast_composer.py`, `broadcast_image.py`, `daily_recap.py` | Broadcast, poster dan rekap |
| `backend/post_purchase.py`, `order_fulfillment.py` | Followup, pengecualian dan finalisasi order |
| `backend/bot.py`, `bot2.py`, `direct_checkout.py`, `services.py` | Bot dan integrasi alur pembelian |
| `backend/storefront_routes.py` | API storefront, auth pelanggan, cart/order, profil GET/PATCH `/api/store/me` |
| `backend/admin_user_routes.py` | Direktori `/api/admin/user-directory?source=all\|telegram\|web\|linked`, paging/search; aksi admin lama |
| `frontend/src/pages/Storefront.jsx` | Orkestrasi storefront/cart/checkout/routes |
| `frontend/src/components/StoreHome.jsx` | Homepage |
| `frontend/src/components/StoreProductDialog.jsx` | Modal produk/varian |
| `frontend/src/components/StoreNavigation.jsx`, `StoreProfile.jsx` | Navigasi dan profil |
| `frontend/src/components/StoreFeedback.jsx`, `OrderDelivery.jsx` | Animasi checkout/toast dan detail akun |
| `frontend/src/lib/catalog.js`, `frontend/src/storefront.css` | Grouping/label varian dan tema |
| `frontend/src/pages/Users.jsx` | Filter direktori admin |
| `frontend/src/pages/Catalogs.jsx`, `Products.jsx`, `Inventory.jsx` | Panel produk/katalog/inventory |
| `scripts/verify_master_data.py`, `release_data_snapshot.py` | Verifikasi DB baca-saja; bukan backup nilai database |

Koleksi penting: products, product_catalogs (dapat belum ada bila semua katalog
masih inferensi), inventory_items, purchases, deposits, gopay_payments, bot_users,
store_customers, settings, tg_accounts, reseller_*, broadcast/stock/followup logs.
Backup harus mengambil semua koleksi, tidak terbatas daftar ini.

## 5. Pengujian dan deployment

Hasil rilis terakhir: **59 tes backend + 4 tes frontend lulus**, build sukses dan
uji browser sintetis tanpa error. Tes browser mencakup modal, blur, varian habis,
quantity, keyboard, deep link, tema, checkout/QRIS, TXT, profil, menu mobile dan
filter admin. Itu bukan pembelian sungguhan di production.

```bash
cd /opt/sellerbottel/backend
./venv/bin/python run_offline_tests.py tests/test_master_revision.py tests/test_catalog_delivery_flow.py tests/test_feature_upgrade.py tests/test_product_catalog.py tests/test_broadcast_composer_stock.py tests/test_broadcast_reports.py tests/test_inventory_upload.py tests/test_storefront_auth.py -q

cd /opt/sellerbottel/frontend
CI=true npm test -- --watchAll=false --runInBand --runTestsByPath src/lib/catalog.test.js
BUILD_PATH=/tmp/idse-candidate-build npm run build

cd /opt/sellerbottel
/opt/AntWork/.venv/bin/python scripts/verify_marketplace_ui.py --build /tmp/idse-candidate-build --chrome /home/ubuntu/.cache/ms-playwright/chromium-1181/chrome-linux/chrome --output /tmp/idse-candidate-ui
git diff --check
```

Path Chromium/Playwright di atas khusus VPS ini; sediakan dependency setara bila
pindah mesin. Backend dependency `backend/requirements.txt`; frontend package/lock
files adalah acuan. Jangan menjalankan build langsung ke produksi saat pengujian.
Deployment frontend: salin aset candidate, pertahankan aset hash lama, lalu ganti
index secara atomik. Restart service backend hanya setelah tes dan backup.
Verifikasi HTTPS, API protected, service, log, dan data sebelum menyatakan live.

## 6. Backup terbaru dan pemulihan

Backup yang dibuat bersama handover ini disimpan di:
`/opt/sellerbottel/backups/handover-<timestamp-UTC>/`.
`/opt/sellerbottel/backups/LATEST` menunjuk direktori backup yang **sudah lulus**
verifikasi. Periksa `MANIFEST.json`, `RESTORE.md`, `SHA256SUMS`, dan `verification.json`
di dalamnya untuk waktu, ukuran, jumlah koleksi/dokumen serta hasil uji restore.

- `repository.tar.gz`: seluruh source tracked/untracked, `.git`, `.env`, build aktif,
  aset/foto/session di repository, lockfiles dan dokumen ini. Dependency terpasang
  (node_modules/venv), cache dan direktori backups tidak disalin; dapat direinstall.
- `mongodb.archive.gz`: **seluruh nilai BSON semua koleksi database sellerbottel**,
  termasuk user, saldo, transaksi, inventory terenkripsi, konfigurasi, log, index
  dan metadata. Bukan sekadar hash/schema. Ciphertext asli dan kunci `.env` disimpan.
- `runtime-config.tar.gz`: konfigurasi Nginx/systemd/TLS yang tersedia di server.
- `docker-inspect.json`, git status/diff/log, versi dependency, snapshot dokumen
  sebelum/sesudah dump, manifest dan checksums: konteks reproduksi/verifikasi.
- Jika storage berada di luar repository, `external-storage.tar.gz` menyertakannya.
- Uji restore dilakukan di container Mongo sementara tanpa jaringan/port publik;
  perbandingan jumlah, hash seluruh nilai dokumen, index dan opsi koleksi direkam.

Direktori/file backup privat (700/600), diabaikan Git, tidak di bawah webroot
`frontend/build`. Arsip mengandung rahasia dan belum dienkripsi sebagai satu paket;
transfer hanya ke lokasi privat. Backup lokal ini tidak otomatis menjadi backup
off-server. Jangan meminta agent membaca nilai rahasia ke chat.

Saat pindah: salin handover + **seluruh direktori backup**, verifikasi SHA256, baca
RESTORE.md, ekstrak ke folder baru dan uji DB terisolasi terlebih dahulu. Jangan
menyalakan bot/payment worker di lingkungan uji. Jangan regenerasi key enkripsi.
Pemulihan ke production bukan bagian dari pembuatan backup ini.

## 7. Riwayat penting dan batasan

- Pernah terjadi insiden tes lama mengenai DB production sebelum rilis katalog:
  koleksi produk/inventory terkena fixture. Sudah dipulihkan dan direkonsiliasi.
  Dua produk TEST lama dipertahankan nonaktif karena metadata lengkap tidak ada;
  timestamp satu item direkonstruksi dari order. Detail jujur ada di laporan rilis.
  Runner offline/mock sebelum import ditambahkan untuk mencegah pengulangan.
- Revisi master UI berikutnya tidak mereset/menghapus DB. Pada verifikasi rilis
  tersebut 52 order lama tetap identik; 1 order sah Rp1.443.200 dan 1 akun web baru
  muncul selama pengerjaan. Delta saldo sama persis dengan order baru tersebut.
- Angka historis terakhir: 37 produk, 1.058 inventory, 53 order, 15 deposit,
  25 bot_users, 3 store_customers. Gunakan manifest backup terbaru untuk angka
  aktual; jangan mengembalikan angka historis dengan menghapus transaksi baru.
- Nama/kontak bisa diedit; perubahan email login belum dibuat. Filter sumber akun
  bukan tracking asal campaign. Gambar merek tak dikenal memakai inisial.
- Auto-followup OFF pada rilis katalog; status terkini ada di DB, tidak dipaksakan
  oleh handover. Bot memerlukan hak admin channel untuk kick.

Referensi: [rilis katalog](docs/marketplace-catalog-release-2026-09-28.md),
[audit/revisi master](docs/master-revision-audit-20260928.md).
Laporan browser lama di `/tmp/idse-master-revision-ui/report.json`; `/tmp` bukan
penyimpanan permanen. Dokumentasi di repo dan bundle backup harus dibawa saat migrasi.

## 8. Instruksi singkat untuk agent baru

> Baca `/opt/sellerbottel/AGENT_HANDOVER.md`, kedua dokumen rilis terkait, dan manifest
> backup terbaru. Audit working tree serta implementasi nyata sebelum mengubah kode.
> Pertahankan seluruh data production dan kunci enkripsi. Gunakan tes offline.
> Jangan menganggap commit Git dasar sudah berisi semua fitur yang berjalan.
> Laporkan dengan jelas perubahan source, hasil tes, dan apakah sudah deployed.
