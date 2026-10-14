OPEN THIS FIRST

SellerBottel V3 — DEVELOPMENT / TEST, 9 Oktober 2026. Siap untuk owner manual UAT V1. Ini bukan deployment production. Semua data produk dan transaksi UAT adalah demo.

## Buka dari Android

| Keperluan | URL |
|---|---|
| Landing / registrasi | https://idseconnect.my.id / https://idseconnect.my.id/daftar |
| Platform login | https://idseconnect.my.id/login |
| Platform Control / fee IDSE | https://idseconnect.my.id/platform-control |
| Login tenant umum | https://idsestock.my.id |
| Fashion Demo — panel | https://fashion-demo.idsestock.my.id |
| Fashion Demo — customer/shop | https://fashion-demo.idseconnect.my.id |
| Digital Demo — panel | https://digital-demo.idsestock.my.id |
| Digital Demo — customer/shop | https://digital-demo.idseconnect.my.id |
| Callback Kasera | https://pay.idsepos.my.id/api/payments/webhooks/kasera |

DNS wildcard sudah benar di nameserver otoritatif, Google DNS dan Cloudflare DNS. Resolver bawaan VPS sempat menyimpan NXDOMAIN lama khusus fashion-demo.idsestock.my.id. HTTPS host tersebut sudah diuji dengan verifikasi sertifikat ke IP 16.78.106.9. Jika perangkat masih memakai cache lama, tunggu propagasi resolver; tidak perlu membuat staging.idsepos.my.id.

## Akun

| Peran | Username/email |
|---|---|
| Platform Owner | owner-uat@idseconnect.my.id |
| Tenant A / Fashion | idsegwork+uat-fashion@gmail.com |
| Tenant B / Digital | idsegwork+uat-digital@gmail.com |
| Customer A, hanya Fashion | idsegwork+uat-customer-a@gmail.com |
| Customer B, hanya Digital | idsegwork+uat-customer-b@gmail.com |

Password hanya di `/home/sellerbottelv2/.uat-private/credentials.txt`, mode 0600; ambil melalui akses lokal/SSH pribadi. Tidak tersedia sebagai URL publik dan tidak masuk Git. Akun tenant harus login di panel tenant, bukan form login Platform Owner. Customer login di toko yang sesuai. Panel tenant menyimpan sesi di memori: reload mengharuskan login kembali.

Tenant fresh hasil uji SMTP: `owner-fresh-uat`, email `idsegwork+uat-fresh@gmail.com`, credential terpisah di `.uat-private/fresh-registration.json`. OTP dikirim melalui SMTP asli; harness memasukkan kode dari DB UAT, bukan membaca inbox. Penerimaan inbox pada run ini belum dikonfirmasi owner. Untuk registrasi manual baru, gunakan Gmail/alias lain milik sendiri yang belum terdaftar.

## Urutan UAT yang disarankan

1. Login Platform Owner, lalu buka `/platform-control`. Periksa dua tenant dan pengaturan **Fee gateway IDSE**. Default tetap Rp250; contoh tier Rp10.000–20.000 →250 dan Rp20.001–50.000 →500. Batas inklusif, batas akhir kosong berarti tanpa batas. Perubahan hanya memengaruhi checkout baru.
2. Daftar tenant baru melalui `/daftar`: terima OTP, verifikasi, selesaikan provisioning, login. Storefront otomatis `<slug>.idseconnect.my.id`, panel otomatis `<slug>.idsestock.my.id`. Payment tenant baru perlu dipilih **Settlement IDSE / Kasera** di Payments sebelum checkout gateway.
3. Login Fashion Demo. Di Produk, buka Hoodie Demo: Black/White × M/L, SKU FASH-BLK-M, FASH-BLK-L, FASH-WHT-M, FASH-WHT-L. Uji edit, upload gambar, receive, adjustment, damage dan ledger. Stok awal 20 per varian; riwayat transaksi/retur UAT tetap tersedia untuk diperiksa.
4. Buka shop Fashion sebagai Customer A. Tambahkan Hoodie, Gemini AI Demo, VPS Setup Demo dalam satu keranjang. Isi alamat manual: nama, telepon, alamat, kecamatan, kota/kabupaten, provinsi, kode pos. Ongkir manual demo Rp10.000. Coba kupon **UAT10**: 10%, maksimum Rp10.000, kuota demo 100, maksimal 10 per customer.
5. Pilih **Kasera QRIS TEST**. Periksa harga setelah diskon + ongkir, biaya Kasera dan buyer total. Buka halaman checkout provider. Gunakan simulasi pembayaran berhasil yang tersedia pada halaman TEST; jangan memakai aplikasi bank untuk transfer sungguhan. Jika tombol simulasi provider tidak muncul, catat untuk UAT-fix; endpoint provider yang sudah diverifikasi adalah `POST /api/v1/checkout/<checkout-token>/simulate-payment` dengan `{"outcome":"succeeded"}`. Token checkout adalah privat, jangan kirim ke laporan publik.
6. Tunggu callback asli. Detail order menunjukkan pembayaran dan tiga fulfillment terpisah. Digital inventory berisi akun **sintetis** `example.test`, bukan akun Gemini sungguhan. Selesaikan jasa dari Order, lalu fisik: packing → ready_to_ship → shipped (carrier/resi demo) → delivered. Customer melihat tracking dan delivery digitalnya.
7. Di Payments, periksa transaksi dan lima komponen settlement: gross, Kasera persen, Kasera tetap, SellerBottel fee, net settlement. Pembeli menanggung Kasera 0,7% + Rp250. Fee SellerBottel ditanggung tenant pengguna IDSE; self gateway tidak dikenai fee SellerBottel.
8. Dari customer, ajukan return barang delivered. Di panel: reviewing → approved → received → inspected, pilih restock atau damaged → resolved. Pengajuan refund Kasera TEST saat ini **manual_refund_required**, tidak mentransfer uang. Partial/full amount dapat diajukan selama tidak melewati total yang belum dicadangkan; refund manual tetap mencadangkan jumlahnya. Jangan menganggap status ini refund provider berhasil.
9. Ulangi di Digital Demo dengan Customer B. Bot development untuk Digital Demo: https://t.me/GrizzlySMS_notifbot. Uji `/start`, katalog, quantity, coupon/history/help dan delivery. Checkout fisik bot harus ditolak sebelum charge dan diarahkan ke webshop. Bot Fashion belum dipasang karena hanya satu token development aktif.
10. Branding mendukung platform/co_branded/tenant_only untuk dua demo. Uji shop, checkout, receipt, tracking dan greeting. Uji suspend/disabled/reactivate satu tenant dari Platform Control; tenant lain harus tetap berfungsi dan data tenant yang diaktifkan kembali tetap ada.
11. Isi [OWNER_UAT_CHECKLIST.md](OWNER_UAT_CHECKLIST.md). Catat URL, langkah, hasil yang diharapkan/aktual, waktu, order ID dan screenshot tanpa password/token. Temuan owner menjadi sprint UAT-fix terpisah.

## Batasan yang terlihat

- Kasera TEST: callback genuine berhasil untuk kedua mixed order. Tidak ada live charge/payout.
- Payout sandbox belum didukung; kontrol simulasi dinonaktifkan untuk dana Kasera sandbox. Simulasi payout mock tidak menggunakan saldo Kasera. Refund API Kasera belum tersedia; pengajuan manual tetap dapat diperiksa.
- Kupon UAT10 disiapkan untuk uji customer/bot. Editor kupon tenant dan halaman analytics/bot settings lengkap belum tersedia dalam panel tenant existing; jangan memakai panel platform untuk mengelola data tenant secara silang.
- Bot kedua dinonaktifkan owner. Join-gate/broadcast tidak dijalankan karena channel/recipient aman belum disediakan. Jangan broadcast ke pengguna lama.
- Signup customer baru dan interaksi Telegram manual tetap checklist owner; login kedua customer telah diuji. Kuota/stock berkurang sesuai checkout dan pengujian yang tercatat.
- Midtrans, Stripe, integrated shipping/Biteship, live settlement/payout tetap deferred.

## Layanan, restart dan log

```bash
sudo systemctl status sellerbottel-uat-backend sellerbottel-uat-frontend sellerbottel-uat-dispatcher
sudo systemctl restart sellerbottel-uat-backend sellerbottel-uat-frontend sellerbottel-uat-dispatcher
sudo journalctl -u sellerbottel-uat-backend -u sellerbottel-uat-frontend -u sellerbottel-uat-dispatcher -f
```

Backend localhost:8010, frontend localhost:3010, Mongo localhost:27020. Semua akses publik lewat Caddy. Platform DB `sellerbottel_uat_platform`; database demo terpisah dari Mongo audit 27019. Runtime/storage di `.uat-runtime`, config di `.uat-private/runtime.json`. Jangan menjalankan kembali dispatcher audit lama bersamaan dengan UAT: token bot development yang sama telah dipindahkan ke Digital Demo.

Payment existing tetap memakai service `sellerbottel-kasera-sandbox`, localhost:8007. Caddy site `pay.idsepos.my.id` identik dengan sebelum UAT. Runtime meneruskan raw callback dengan reference `uat-` ke backend UAT; signature tetap diverifikasi di namespace UAT. Callback release lama tetap di namespace lama. `GET /health` sukses; root payment 404 adalah perilaku yang diharapkan.

## Reset demo — opsional, destruktif hanya untuk dua demo

Default tooling hanya dry-run:

```bash
cd /home/sellerbottelv2
.uat-runtime/venv/bin/python tools/reset_owner_uat.py
```

Reset aktual **belum dijalankan**. Bila owner memang ingin menghapus order, inventory, stock history dan customer tambahan kedua demo lalu mengisi ulang seed:

```bash
sudo systemctl stop sellerbottel-uat-backend sellerbottel-uat-dispatcher
.uat-runtime/venv/bin/python tools/reset_owner_uat.py --execute --confirm 'RESET SELLERBOTTEL UAT DEMOS'
sudo systemctl start sellerbottel-uat-backend sellerbottel-uat-dispatcher
```

Guard memeriksa environment development/UAT, Mongo27020, platform DB, dua slug tetap, DB name dan tenant ID dari manifest privat, serta service yang berhenti. Fresh tenant lain tidak dihapus. Identitas owner/domain/gateway tetap. Backup data demo yang ingin disimpan terlebih dahulu. Tool ini bukan endpoint HTTP dan tidak menerima arbitrary tenant/db.

Production pada machine lain: **UNTOUCHED**.
