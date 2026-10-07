# Audit sebelum revisi master IDSE Marketplace

Audit repository dan backup dilakukan sebelum perubahan kode pada revisi ini.

| Area | Temuan |
| --- | --- |
| Frontend | React 19, React Router 7, CRA/CRACO, Tailwind, Lucide, Radix Dialog. `frontend/src/pages` untuk storefront/admin, `components` untuk UI, `lib` untuk API/katalog. |
| Backend | Python FastAPI/Uvicorn, modul route di `backend`, Pydantic untuk request validation. |
| Database/client | MongoDB `sellerbottel`, Motor AsyncIOMotorClient/PyMongo; tidak memakai ORM relasional. |
| Schema | Dokumen MongoDB; `products`, `product_catalogs`, `inventory_items`, `bot_users`, `store_customers`, `purchases`, `deposits`, `gopay_payments`, `settings`, dan koleksi pendukung. Relasi menggunakan `_id`, `product_id`, `order_id`, `customer_id`, `user_tid`/`telegram_id`. Index dikelola `db.py`. |
| Authentication/session | Admin: JWT HS256 `access_token`, bcrypt, 12 jam. Pelanggan: JWT `customer_access_token`, HttpOnly/Secure/SameSite=Lax, 12 jam, `session_version`; email OTP untuk daftar/reset password. |
| Telegram | Webhook bot utama/kedua/reseller; Telegram dan akun web dapat ditautkan. Tidak mengubah webhook, token, atau aturan moderasi pada revisi ini. |
| Cart | Storefront memakai localStorage `store_cart` berisi `{pid, qty}`. Quote API memvalidasi harga/stok; bot menyimpan cart di akun Telegram. |
| Order | `purchases`, ID/invoice tetap, idempotency checkout, reservasi/commit inventory. Jasa memiliki status menunggu penyelesaian. |
| Transaction/deposit | Riwayat menggabungkan pembelian/deposit. QRIS dipantau backend. Deposit terverifikasi menambah saldo lewat penanda kredit idempoten. |
| Saldo | `balance_idr`/`balance_usd` pada bot atau pelanggan web. Penautan mempunyai `wallet_merge`; tidak memindahkan/menghitung ulang saldo dalam revisi ini. |
| Catalog/variant | Katalog eksplisit atau inferensi nama; varian adalah produk yang memiliki ID sendiri di katalog sama. UI akan memperjelas pilihan varian tanpa mengganti schema/ID. |
| Admin | Route protected `/products`, `/catalogs`, `/inventory`, `/users`, `/orders`, `/reports`, `/settings`, dan halaman operasional lainnya. Daftar pengguna saat ini menggabungkan dua respons di frontend. |
| Statistik | Statistik dan laporan menghitung koleksi purchases/deposits dengan cutoff `settings.stats_reset_at`. Terdapat endpoint reset terpisah; tidak digunakan. Rumus/riwayat keuangan dipertahankan. |
| Deployment | systemd `sellerbottel`: Uvicorn `server:app` di 127.0.0.1:8000. Nginx melayani `frontend/build`, proxy `/api/`. Host `idseshop.my.id` dan `idsedm.duckdns.org`. |

Branch `main`, HEAD `9692069`. Working tree berisi perubahan rilis sebelumnya dan
file untracked; semua disertakan dalam snapshot repository, bukan hanya commit Git.
Daftar branch, 10 commit terakhir, status, dan binary diff tersimpan bersama backup.

## Backup sebelum perubahan

Direktori privat: `/home/ubuntu/backups/idse-master-revision-20260928/`.

- `repository.tar.gz` (5.759.655 byte): source, `.git`, file untracked, konfigurasi,
  build produksi; dependency terpasang/cache tidak disertakan.
- `mongodb.archive.gz` (397.040 byte): seluruh database; gzip diverifikasi, log dump
  dan SHA256 tersimpan. Tidak ada restore/reset pada production.
- `baseline.json`: hash tiap dokumen seluruh koleksi, nama field schema, agregat
  saldo/penjualan/deposit per mata uang/status, dan cutoff statistik. Tidak berisi
  plaintext akun inventory. File privat, tidak masuk repository/build.
- Snapshot awal: 37 produk, 1.058 inventory, 52 purchases, 15 deposits,
  25 bot_users, 2 store_customers.

## Rencana extension

1. Komponen modal menggunakan Radix yang sudah terpasang; blur, fokus keyboard,
   Escape/tombol tutup, pilihan varian ber-ID tetap, URL detail lama tetap berfungsi.
2. Homepage lebih padat informasi dengan katalog/produk/harga/ketersediaan asli;
   menu mobile berikon, keterangan, dan indikator halaman aktif.
3. PATCH profil hanya memperbarui field nama tampilan/kontak opsional; tidak menerima
   ID akun, email login, saldo, password, atau relasi Telegram melalui mass assignment.
4. Direktori admin menyatukan pembacaan akun Telegram/web, filter sumber, pencarian,
   paging, dan penghitungan order unik. Endpoint operasional lama tetap tersedia.
5. Tes offline database tiruan/network disabled dan browser mock. Bandingkan baseline
   data dan statistik sebelum/sesudah rilis; perubahan transaksi sah harus diperiksa,
   bukan ditimpa dengan baseline.

## Hasil implementasi dan rilis

- Homepage diperbarui dengan pencarian, katalog, produk tersedia, harga, dan panduan
  pembelian. Semua isi katalog/produk memakai data yang sudah ada.
- Detail produk menjadi modal Radix dengan blur, pilihan varian/durasi, stok, jumlah,
  subtotal, fokus keyboard, Escape, dan tautan langsung yang tetap berfungsi.
- Navigasi mobile berikon dan deskripsi; tema auto/light/dark berlaku pula pada modal.
- Profil dapat menyimpan nama tampilan dan nomor kontak opsional. Email login tetap
  read-only; endpoint menolak perubahan saldo, identitas, password, dan session.
- Direktori admin menyediakan filter Telegram saja, Website saja, Web + Telegram,
  pencarian dan pagination. Sumber menjelaskan keberadaan/tautan akun saat ini,
  bukan atribusi pemasaran historis. Akun tertaut dan ordernya dihitung sekali.
- Tidak ada migrasi schema, reset, restore, atau penghapusan data pada revisi master.

Validasi: 59 tes backend offline dan 4 tes frontend lulus; build produksi berhasil.
Browser mock menguji katalog, tema, modal/varian/stok/quantity/focus/deep link,
animasi keranjang, checkout saldo/QRIS, detail akun/TXT, profil, menu mobile,
serta filter admin tanpa error browser. Tes memakai data sintetis dan tidak
melakukan pembelian, pengiriman pesan, atau edit akun production.

Build `main.fff03623.js` telah diterapkan ke `frontend/build` dengan pergantian
index atomik dan aset hash lama dipertahankan. Backend direstart dan aktif.
HTTPS storefront mengembalikan build baru dan judul IDSE Marketplace. Endpoint
direktori terautentikasi dan statistik merespons 200; akses anonim direktori dan
PATCH profil ditolak 401. Filter production: 24 Telegram saja, 2 Website saja,
1 akun tertaut (27 pengguna unik pada pemeriksaan rilis).

Backup tambahan tepat sebelum deployment: `mongodb-predeploy.archive.gz`
beserta log di direktori backup privat di atas; gzip diverifikasi. Konfigurasi
proses tidak mengarahkan upload ke lokasi eksternal, dan folder storage lokal
belum ada saat audit. Tidak ada file upload eksternal yang perlu dipindahkan.

Pemeriksaan hash sebelum rilis: seluruh data inti identik dengan baseline.
Pemeriksaan setelah rilis: tidak ada ID dokumen lama yang hilang, seluruh 52 order
lama tetap identik, 37 produk dan 1.058 inventory tetap ada, 15 deposit tetap
identik, 25 akun bot dan 2 akun web lama dipertahankan. Aktivitas production
menambahkan 1 akun web dan 1 order delivered pada 16:49:19 UTC senilai
Rp1.443.200; penurunan total saldo persis sama dengan nilai order baru itu.
Total purchases menjadi 53. Cutoff statistik tidak berubah. Data baru ini
dipertahankan, bukan ditimpa dengan backup. Snapshot/verifikasi privat tersedia
di `/tmp/idse-master-predeploy.json` dan `/tmp/idse-master-postdeploy.json`;
skrip pemeriksaan baca-saja: `scripts/verify_master_data.py`.
