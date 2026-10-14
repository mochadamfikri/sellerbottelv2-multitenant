# Owner manual UAT — Android

Semua checkbox di bawah adalah pekerjaan manual owner, bukan klaim sudah diuji owner. Baca [OPEN THIS FIRST](UAT_HANDOFF.md) untuk akun, URL, data awal dan batasan TEST.

## Platform
- [ ] Login owner, buka Platform Control dan lihat kedua tenant.
- [ ] Ubah default fee/tier, cek overlap ditolak, rentang inklusif dan batas akhir kosong.
- [ ] Kembalikan kebijakan yang diinginkan setelah uji.

## Registration
- [ ] Registrasi Gmail baru, OTP diterima di inbox, verifikasi berhasil.
- [ ] Provisioning active, owner dapat login, subdomain shop/panel benar.
- [ ] Pilih Settlement IDSE/Kasera pada tenant baru sebelum payment test.

## Tenant Panel
- [ ] Tenant A/B login, katalog/produk/orders/customers terpisah.
- [ ] Create/edit/upload gambar/aktif-nonaktif produk.
- [ ] Catat gap editor kupon, analytics dan bot settings existing; jangan memakai akses platform sebagai pengganti scope tenant.

## Bot
- [ ] Digital Demo @GrizzlySMS_notifbot: start, branding, katalog, detail, quantity, coupon UAT10, history/help.
- [ ] Digital/jasa bekerja; fisik ditolak sebelum charge dan diarahkan webshop.
- [ ] Bot kedua: NOT RUN, token kedua dinonaktifkan owner.
- [ ] Join-gate: NOT RUN tanpa channel aman.
- [ ] Broadcast: NOT RUN tanpa recipient set aman.

## Webshop
- [ ] Login Customer A/B di shop masing-masing.
- [ ] Signup customer baru via OTP, browse, detail, cart/qty, coupon UAT10.
- [ ] Mixed digital + service + physical, satu payment tiga fulfillment.

## Digital
- [ ] Inventory sintetis dikirim setelah paid; tidak bocor ke customer/tenant lain.
- [ ] Order history/detail memperlihatkan delivery.

## Service
- [ ] Order masuk queue; owner menyelesaikan jasa secara terpisah.
- [ ] Status customer berubah dengan benar.

## Physical
- [ ] Hoodie 4 varian/SKU, pilih ukuran/warna.
- [ ] Packing → ready_to_ship → shipped → delivered.

## Stock
- [ ] Receive, adjustment, damage, on_hand/reserved/available dan ledger.
- [ ] Checkout/payment memperbarui stok; return restock/damaged tidak menggandakan stok.

## Payment
- [ ] Kasera TEST saja, biaya buyer terlihat sebelum checkout.
- [ ] Simulasi provider, callback genuine, paid dan fulfillment diperbarui.
- [ ] Fee SellerBottel sesuai tier; checkout lama tidak berubah setelah policy diubah.

## Settlement
- [ ] Lima komponen fee/net, pending → clearing → available terlihat.
- [ ] Kasera sandbox payout diberi penjelasan dan kontrol dinonaktifkan; tidak ada transfer bank.

## Shipping
- [ ] Alamat manual, kecamatan/kota/provinsi/kode pos dan ongkir.
- [ ] Carrier/resi demo tampil pada tracking customer.
- [ ] Integrated shipping/Biteship deferred.

## Return/Refund
- [ ] Return hanya item eligible; approve, receive, inspect/restock atau damaged, resolve.
- [ ] Partial/full refund intent dalam batas yang valid; manual_refund_required jelas, tidak diklaim paid.

## Branding
- [ ] Platform, co_branded, tenant_only untuk demo.
- [ ] Shop/checkout/receipt/tracking/email/greeting konsisten; A tidak muncul di B.

## Lifecycle/Isolation
- [ ] Suspend/disabled A menolak operasi A, B tetap berjalan.
- [ ] Reactivate A memulihkan akses tanpa menghapus data.
- [ ] Customer/owner A tidak dapat membaca/mengubah order B.

Hasil owner: belum dijalankan. Tanggal/perangkat/temuan: isi setelah UAT.
