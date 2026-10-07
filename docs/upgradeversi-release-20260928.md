# Rilis upgradeversi — saldo admin, identitas Telegram, campaign marketing

Status: deployed pada 28 September 2026. Frontend `main.86a3cfa3.js`,
`main.e7a9b64a.css`; systemd sellerbottel aktif. Endpoint admin direktori, campaign,
options dan stats merespons 200 dengan auth; tanpa auth ditolak 401.

## Implementasi

- Users: adjust WEB/BOT/linked, ADD/SUBTRACT, IDR/USD, catatan, request ID,
  saldo before/after, actor, riwayat manual dan pencarian ID internal.
- Ledger balance_adjustments tetap dipakai. Mongo standalone: balance + receipt
  embedded dicatat dalam satu operasi CAS atomik. Proyeksi ledger dapat dipulihkan
  worker; retry tidak menambah/mengurangi saldo dua kali. Endpoint lama bot tetap ada.
- Broadcast pembelian nyata: helper masking dari mapping order/user asli, tanpa
  perubahan nilai ID/username di DB. Fallback aman untuk nilai invalid/tidak tersedia.
- Broadcast promo: campaign dan event persisten pada broadcasts, interval randint
  min/max setelah setiap pesan, variasi produk, lease worker, pause/resume/stop,
  log/progres, tujuan memakai konfigurasi lama. Pesan jelas berlabel PROMO IDSE.
- Inventory: atomic available → marketing_allocated; audit embedded dan proyeksi
  stock_events. Sold, purchase, revenue, saldo tidak ditulis oleh campaign. Retry
  memakai alokasi awal. Restore idempoten menjadi available, satu atau semua item.
- Manual stock cap ikut dikurangi marketing. Inventory reserved/terjual dilindungi.
  Produk jasa/tanpa inventory tidak eligible untuk alokasi unit nyata.
- Timeout/crash setelah send tidak dapat dibuktikan terkirim atau gagal oleh Bot API:
  event unknown memerlukan verifikasi admin/ID pesan atau Stop, tidak auto-resend.
- Audit stok berstatus recorded dipisahkan dari antrean notifikasi stok pending;
  endpoint retry notifikasi menolak ledger marketing. Penghapusan inventory yang
  sudah direstore memastikan proyeksi audit tersimpan dahulu.

## Database

Tidak ada koleksi wallet/ledger paralel. Additive fields: receipt admin_balance_audit
pada akun; marketing/marketing_audit pada inventory; campaign kind/events/progress
di broadcasts. Dua index tambahan: marketing_event_unique (partial unique string
marketing.event_id) dan marketing_schedule (kind/status/next_scheduled_at).
Tidak ada reset, restore ke production, migrasi destruktif, atau perubahan ID lama.

Snapshot `/tmp/idse-upgrade-before.json` dan `/tmp/idse-upgrade-after.json`: seluruh
hash dokumen identik, tidak ada ID hilang/berubah/bertambah selama deployment.
37 produk, 1.058 inventory, 53 purchases, 15 deposits, 25 bot_users, 3 store_customers.
Agregat saldo, purchases, deposits, dan stats_reset_at identik.
Tidak membuat campaign production, menyesuaikan saldo sungguhan, atau mengirim pesan
Telegram untuk tes. Pengiriman nyata baru terjadi saat admin mengaktifkan campaign.

## Validasi yang dijalankan

PASS — 51 tes backend, satu warning deprecation python_multipart yang sudah ada:

```bash
cd /opt/sellerbottel/backend
./venv/bin/python run_offline_tests.py tests/test_upgradeversi.py tests/test_master_revision.py tests/test_catalog_delivery_flow.py tests/test_broadcast_reports.py tests/test_broadcast_composer_stock.py tests/test_direct_checkout.py -q
```

PASS — production build (project tidak menyediakan script typecheck terpisah):

```bash
cd /opt/sellerbottel/frontend
BUILD_PATH=/tmp/idse-upgrade-build npm run build
```

PASS — browser lokal/API sintetis, tanpa browser errors:

```bash
cd /opt/sellerbottel
/opt/AntWork/.venv/bin/python scripts/verify_upgrade_ui.py --build /tmp/idse-upgrade-build --chrome /home/ubuntu/.cache/ms-playwright/chromium-1181/chrome-linux/chrome
git diff --check
```

Covered: WEB add, BOT subtract, riwayat audit dan sumber pengguna; campaign create
5–70 menit, Pause persisten setelah reload, Resume, Stop. Tes backend juga memeriksa
request retry, saldo kurang, USD, audit projection repair, masking, kegagalan
broadcast tidak membatalkan order, interval deterministik bervariasi, no-stock,
alokasi/retry/recovery restart/restore ganda, stok manual dan prioritas reservasi
customer. Statistik penjualan/checkout memakai jalur lama, campaign tidak menyisipkan
record purchases atau deposits.

## File revisi ini

Backend baru: balance_admin.py, telegram_identity.py, marketing_campaigns.py,
tests/test_upgradeversi.py. Integrasi: admin_routes.py, admin_user_routes.py,
services.py, checkout.py, stock_monitor.py, db.py, server.py.
Frontend: components/BalanceAdjustment.jsx, components/MarketingCampaigns.jsx,
pages/Users.jsx, pages/Broadcasts.jsx, pages/Inventory.jsx.
Pendukung: scripts/verify_upgrade_ui.py, AGENT_HANDOVER.md, laporan ini.
Working tree juga memuat rilis sebelumnya; jangan menganggap seluruh git diff
sebagai perubahan hanya pada upgradeversi ini.

Backup sebelum revisi sudah tersedia di backups/handover-20260928T175340Z.
Backup kondisi sesudah rilis ditunjuk backups/LATEST setelah verifikasi selesai.
Arsip privat/diabaikan Git; source dan dokumen tidak memuat token/kredensial/dump.
