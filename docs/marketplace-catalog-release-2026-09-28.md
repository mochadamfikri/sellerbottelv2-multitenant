# IDSE Marketplace — katalog, inventory, broadcast, dan frontstore

Versi ini dipasang pada 28 September 2026. Backend dimulai ulang pada 13:54:11 UTC;
build aktif menggunakan `main.4265f943.js` dan `main.bee67b1d.css`.

## Penggunaan

| Area | Perubahan dan lokasi |
| --- | --- |
| Bot utama | Menu **Katalog Produk** → katalog → varian; maksimal 8 pilihan per halaman. Tombol stok juga membuka katalog. ID produk tetap, sehingga pilihan tidak berubah ketika stok produk lain habis. |
| Bot kedua | Alur katalog dan status jasa diperbarui. Konfigurasi instalasi ini tidak mengaktifkan bot kedua dan tidak menyediakan token/secret-nya. |
| Admin `/catalogs` | Buat, ubah nama, pindahkan produk secara massal, dan hapus katalog. Penghapusan katalog memindahkan produk ke Produk Lainnya; ID, harga, inventory, dan riwayat pesanan tetap. |
| Admin `/products` | Katalog, pencarian/filter, skema inventory, preview gambar otomatis, upload gambar sendiri, dan impor XLSX/CSV/TXT atau teks yang ditempel. |
| Admin `/inventory` | Pilihan produk dikelompokkan per katalog; upload/manual, preview, template sesuai kolom, paging, edit dan hapus satu item tersedia, serta ganti file session. Item terjual/dipesan tidak dapat diedit atau dihapus. |
| Admin `/broadcasts`, `/central-broadcasts` | Pratinjau, pilihan produk/katalog, tujuan channel/grup/pengguna, judul poster, gambar otomatis atau teks saja, unduh poster, riwayat dan pembatalan sisa antrean. |
| Admin `/settings` | Tujuan broadcast umum, transaksi berhasil, dan rekap dapat diatur terpisah. Pengaturan yang sudah ada menjadi fallback jika tujuan khusus kosong. |
| Admin `/bot-moderation` | Mode OFF atau auto-kick channel + silent block setelah pesanan selesai; pengecualian ID Telegram, reseller, katalog, dan produk. Tindakan manual tetap terpisah. |
| Frontstore `/store/products` | Katalog terlebih dahulu, kemudian varian; filter/pencarian dan paging. Tema Auto/Terang/Gelap disimpan di browser. Judul tab dan logo IDSE Marketplace. |
| Keranjang dan checkout | Tombol tambah berputar 5 detik; pemberitahuan setelah item masuk; popup memproses dengan gambar produk berputar; centang hanya pada status selesai, tutup otomatis 10 detik atau tombol X. QRIS menunggu verifikasi/status selesai. |
| Pesanan/transaksi | Detail akun milik pelanggan, unduhan TXT, dan unduhan file session. Endpoint memeriksa kepemilikan dan status selesai; respons rahasia menggunakan `Cache-Control: no-store`. |

Format wajib produk:

```text
katalog|product|jenis (inventory/jasa)|Harga
Claude Pro|Claude Pro 1 bulan|inventory|100000
Claude Pro|Claude Pro 3 bulan|inventory|275000
Layanan|Jasa Payment|jasa|50000
```

Harga dalam IDR. Empat kolom yang sama digunakan dalam template XLSX dan CSV.
Header lama tetap didukung. Untuk inventory, gunakan template produk yang dipilih;
contohnya `email|password|recovery|2fa`. Jangan memasukkan kolom katalog ke baris akun.

Gambar otomatis menggunakan logo lokal untuk Claude, ChatGPT/OpenAI, AWS, Telegram,
Gmail, Netflix, dan YouTube. Nama produk menentukan PRO/TRIAL/PLUS/PREMIUM/MAX dan
durasi. Merek lain memakai inisial katalog. Foto upload menggantikan gambar otomatis;
menghapus foto upload mengembalikan gambar otomatis. Aset logo dan asalnya tercatat
di `backend/assets/brands/README.md`.

Auto-followup tetap **OFF** saat rilis. Aktifkan dari Tindak Lanjut Bot, isi channel,
dan tentukan pengecualian. Bot perlu izin admin untuk mengeluarkan anggota channel.
Pesanan jasa harus selesai lebih dulu; pesanan lain yang masih berjalan menunda
tindak lanjut. Mengubah nama atau menghapus katalog mempertahankan pengecualiannya.

## Verifikasi

- 47 tes backend lulus melalui `backend/run_offline_tests.py`: database tiruan
  dipasang sebelum import aplikasi dan seluruh socket keluar dinonaktifkan.
- 3 tes pengelompokan katalog frontend lulus; build produksi berhasil.
- Browser Chromium menguji katalog, tema tersimpan dan otomatis, loading 5 detik,
  popup proses, sukses dan tutup 10 detik, QRIS menunggu penyelesaian, tombol X,
  detail akun, TXT, menu ponsel tanpa overflow, dan halaman admin katalog.
- Skenario browser memakai respons API sintetis; tidak melakukan pembayaran,
  mengirim email/broadcast, atau mengeluarkan pengguna sungguhan.
- Pemeriksaan API aktif: 19 produk aktif, 9 katalog, 4 varian Claude; gambar produk
  dan katalog merespons; endpoint admin/detail rahasia menolak akses tanpa login.
- Layanan aktif dan webhook bot utama berhasil terdaftar. Log startup tanpa traceback.
- Snapshot sebelum/sesudah pemasangan: 37 produk total, 1.058 inventory, 301 terjual,
  49 pesanan; hash seluruh dokumen pada produk, inventory, pesanan, pengguna, deposit,
  pelanggan web, dan pembayaran identik selama pemasangan.

Laporan/screenshot browser: `/tmp/idse-ui-checks/report.json` dan direktori yang sama.
Log backend: `/tmp/sellerbottel-offline-checks.log`.

## Cadangan dan insiden pengujian sebelumnya

Sebelum rilis, pemanggilan tes lama sempat memakai database produksi dan mengganti
koleksi produk/inventory dengan fixture tes. Layanan dihentikan selama pemulihan.
Produk dan inventory dipulihkan dari cadangan ke database terpisah, lalu direkonsiliasi
dengan data sebelum insiden dan satu penjualan sah setelah cadangan. Data pesanan,
pengguna, saldo/deposit, dan pembayaran tidak berubah dalam pemulihan. Dua produk
TEST lama dipertahankan sebagai nonaktif karena metadata lengkapnya tidak tersedia.
Waktu reservasi/penjualan satu item direkonstruksi dari waktu pesanan/pembayaran;
metadata waktu asli item itu tidak tersedia. Ikatan item ke pesanan dipertahankan.

Laporan pemulihan: `/tmp/sellerbottel-catalog-recovery-report.json`.
Pengujian sekarang wajib memakai runner offline untuk mencegah kejadian berulang.

Cadangan tepat sebelum pemasangan rilis:

- `/tmp/sellerbottel-pre-marketplace-deploy-20260928.archive.gz`
- `/tmp/sellerbottel-frontend-before-marketplace-20260928.tar.gz`
- Snapshot sidik dokumen: `/tmp/sellerbottel-release-before-20260928.json` dan
  `/tmp/sellerbottel-release-after-20260928.json`.

Pemasangan frontend mempertahankan aset build sebelumnya untuk browser yang masih
membuka halaman lama; `index.html` diganti setelah aset baru disalin.
