# Rencana: Bot Telegram Jualan Produk Digital — Sistem Deposit/Saldo + Dashboard Admin

## Konsep Utama

Bukan "pilih produk lalu bayar". Pembeli **isi saldo (deposit) dulu**, lalu membeli produk menggunakan saldo. Pembelian dipotong dari saldo secara instan, produk langsung terkirim tanpa menunggu verifikasi apa pun.

## Alur Pengguna (di Telegram)

1. **/start** → bot mengirim formulir pilihan mata uang: **USD (default)** atau **IDR**. Pilihan ini tersimpan per pengguna dan bisa diubah kapan saja lewat menu **Pengaturan**.
2. Menu utama: **Lihat Produk, Keranjang, Deposit, Saldo Saya, Riwayat, Pengaturan, Bantuan**.
3. **Deposit**:
   - **Pengguna USD** — minimum deposit **$15**:
     - Pilih koin: **USDT** atau **USDC**
     - Pilih jaringan: **SOL, POL, BNB (BEP-20), Avalanche**
     - Bot otomatis mengirim **alamat deposit** sesuai kombinasi koin+jaringan yang dipilih (alamat-alamat ini Anda isi lewat dashboard).
     - Pengguna mengisi jumlah deposit, lalu mengirim bukti (screenshot atau TX hash) di chat.
   - **Pengguna IDR** — hanya **transfer bank**:
     - Bot mengirim detail rekening bank (Anda isi lewat dashboard) beserta jumlah yang harus ditransfer.
     - Pengguna mengirim foto bukti transfer di chat.
   - **Verifikasi crypto otomatis on-chain (USD)**: setelah pengguna mengirim **TX hash**, bot langsung memeriksa transaksi di blockchain (Solana, Polygon, BNB Chain, Avalanche) — apakah transaksi valid & terkonfirmasi, dikirim ke alamat deposit yang benar, koin sesuai (USDT/USDC), dan jumlahnya ≥ minimum. Jika semua cocok → **saldo otomatis bertambah seketika** dan pengguna diberi tahu, tanpa menunggu admin. Admin tetap menerima notifikasi berisi detail transaksi dengan tombol **Batalkan** jika ingin membatalkan secara manual.
   - Jika pemeriksaan on-chain gagal atau tidak meyakinkan (TX belum ditemukan, jumlah tidak cocok, atau pengguna hanya mengirim screenshot tanpa TX hash) → deposit masuk sebagai "menunggu verifikasi" dan admin memutuskan lewat tombol **Setujui / Tolak**.
   - **Deposit IDR (transfer bank)** selalu diverifikasi manual oleh admin. Setelah disetujui, saldo bertambah otomatis dan pengguna diberi tahu; jika ditolak, pengguna diberi tahu alasannya.
   - Setiap TX hash hanya bisa dipakai satu kali (anti klaim ganda).
4. **Keranjang belanja**: pembeli bisa menambahkan beberapa produk ke keranjang, lihat isi & total (dalam mata uangnya), hapus item, lalu **checkout sekali** — total dipotong dari saldo dan semua produk dikirim otomatis berurutan:
   - Produk file → file dikirim langsung di chat.
   - Produk link/kode lisensi → teks dikirim di chat.
   - Jika saldo kurang → bot memberi tahu kekurangannya dan mengarahkan ke menu Deposit.
   - Beli langsung satu produk (tanpa keranjang) tetap bisa lewat tombol "Beli Sekarang".
5. **Konversi kurs USD↔IDR**:
   - Kurs otomatis diambil dari API kurs publik dan diperbarui berkala; admin bisa menimpa dengan **kurs manual** di dashboard.
   - Harga produk cukup diisi dalam satu mata uang dasar (USD) — harga IDR dihitung otomatis dari kurs; admin tetap bisa menimpa harga IDR secara manual per produk.
   - Saat pengguna **ganti mata uang** di Pengaturan, bot menawarkan **konversi saldo** ke mata uang baru memakai kurs berlaku (pengguna konfirmasi dulu).
6. **/saldo** → cek saldo; **/riwayat** → riwayat deposit dan pembelian.

## Notifikasi Admin via Telegram

- Deposit crypto yang lolos cek on-chain → notifikasi info + tombol **Batalkan**.
- Deposit yang butuh verifikasi manual (IDR / crypto tidak terverifikasi otomatis) → notifikasi dengan bukti + tombol **Setujui / Tolak**.
- Notifikasi juga dikirim saat ada pembelian produk (sebagai info penjualan).

## Dashboard Web Admin

- **Login admin** (email + password).
- **Kelola produk**: nama, deskripsi, **harga USD dan harga IDR** (diisi terpisah, tanpa kurs otomatis), jenis pengiriman (file / link / kode lisensi), upload file atau isi teks, aktif/nonaktif.
- **Kelola deposit**: daftar deposit dengan filter status, lihat bukti bayar/TX hash, setujui/tolak (setujui = saldo pengguna bertambah otomatis).
- **Kelola pengguna**: daftar pengguna, saldo masing-masing, bisa **menyesuaikan saldo manual** (koreksi/bonus), dan tombol **Bekukan / Banned** manual untuk pengguna yang dianggap curang:
  - Pengguna dibekukan → saldo terkunci, tidak bisa deposit, belanja, atau checkout; bot memberi tahu bahwa akunnya dibekukan beserta alasan (opsional).
  - Admin bisa **membuka blokir** kapan saja; semua aksi bekukan/buka tercatat.
- **Pengaturan pembayaran**:
  - Alamat deposit crypto per kombinasi koin × jaringan (USDT/USDC × SOL/POL/BNB BEP-20/Avalanche = 8 slot alamat).
  - Detail rekening bank untuk IDR.
  - Minimum deposit USD ($15, bisa diubah) dan minimum deposit IDR.
  - Telegram ID admin untuk notifikasi.
  - **Kurs USD↔IDR**: mode otomatis (dari API publik) atau manual (angka diisi admin).
- **Ringkasan**: total deposit, total penjualan, saldo beredar, deposit menunggu verifikasi.

## Keputusan & Asumsi (bisa Anda koreksi)

- **Saldo terpisah per mata uang**; saat ganti mata uang, pengguna ditawari konversi saldo memakai kurs berlaku (dengan konfirmasi).
- **Sumber kurs otomatis**: API kurs publik gratis (tanpa API key), diperbarui berkala; admin bisa mengunci kurs manual.
- **Cek on-chain memakai RPC publik** (Solana, Polygon, BNB Chain, Avalanche) — tanpa perlu API key berbayar. Jumlah deposit yang dikreditkan = jumlah nyata yang tertera di transaksi on-chain.
- **Verifikasi manual tetap ada** sebagai lapisan cadangan: deposit IDR, atau deposit crypto yang gagal dicek otomatis.
- **Minimum deposit IDR**: default Rp 50.000, bisa diubah di dashboard.
- **Kode lisensi**: satu teks per produk dikirim ke semua pembeli (stok kode unik per pembelian bisa ditambah nanti).
- Satu checkout bisa berisi banyak produk (keranjang) atau beli langsung satu produk.
- Bahasa bot: Indonesia.

## Yang Dibutuhkan dari Anda

- **Telegram Bot Token** (sudah punya — dikirim saat pembangunan dimulai).
- **Telegram ID Anda** sebagai admin.
- Alamat deposit crypto (8 kombinasi) dan detail rekening bank — diisi sendiri nanti lewat dashboard.

## Di Luar Cakupan (tahap ini)

- Kupon/diskon, stok kode lisensi unik per pembelian, multi-admin.
