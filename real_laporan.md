# Laporan Status Final Closure V3

- Dibuat: 2026-10-11 14:58 WIB
- Worktree: `/tmp/v3-candidate`
- Branch: `candidate/v3-precutover-readonly`
- Base commit sebelum perubahan closure akun legacy: `5479028c83d3f8a6b2f79c3daadde4e4037c7df9`

## Status Saat File Ini Dibuat

Implementasi perubahan acceptance criteria akun web legacy telah divalidasi
lokal dan siap dibekukan. File ini adalah laporan status sebelum freeze
artifact; verdict final hanya dicatat setelah exact commit dan SHA-256
artifact tersedia.

Perubahan yang belum di-commit:

- `backend/legacy_web_reset.py`
- `backend/legacy_customer_adapter.py`
- `backend/candidate_legacy_routes.py`
- `backend/storefront_routes.py`
- `backend/tests/test_legacy_web_reset.py`
- `tools/mark_legacy_web_password_reset.py`
- `frontend/src/pages/Storefront.jsx`

## Implementasi

- Lima akun web legacy dipertahankan tanpa memodifikasi dokumen pelanggan
  sumber; requirement reset disimpan sebagai sidecar tenant-scoped.
- Login lama diblok sebelum verifikasi bcrypt dengan respons
  `PASSWORD_RESET_REQUIRED`; sesi tidak diterbitkan.
- Reset password menggunakan alur reset email yang sudah ada, mengganti hash
  dengan kebijakan V3 dan mencatat completion di sidecar.
- Mode `CANDIDATE_READONLY=1` tetap fail-closed untuk pengiriman/reset yang
  melakukan write.
- UI storefront mengarahkan respons tersebut ke layar reset password.

## Bukti Yang Sudah Direkam Sebelum Pembekuan

- Focused test reset legacy: 8 lulus.
- Suite kandidat (`candidate_readonly`, `legacy_v3_migrator`, dan legacy
  reset): 113 lulus.
- Invarian clone yang sebelumnya diverifikasi: 53 bot user, 5 customer web,
  57 logical wallet, 1 linked alias, Bot IDR 66,287,650, Web IDR 2,410,800,
  combined IDR 68,698,450, USD 0, dan 1,116 inventory.

Hasil di atas harus tetap diperiksa ulang setelah commit final dari perubahan
yang tercantum pada laporan ini.

## Langkah Penutupan Yang Masih Wajib

1. Commit implementasi setelah review diff.
2. Verifikasi worktree bersih dan freeze archive reproducible dari exact final
   HEAD, lalu hitung SHA-256.
3. Tambahkan evidence dan laporan audit final tanpa mengubah atau menghapus
   laporan sebelumnya.

## Lokasi Laporan Sebelumnya

- `docs/audits/v3-precutover-finish-codex9-20261011-0743WIB.md`
- `docs/audits/v3-precutover-independent-final-verification-codex9-20261011-0938WIB.md`
- `docs/audits/v3-precutover-final-closure-codex9-20261011-1020WIB.md`

Laporan-laporan tersebut bersifat historis. `real_laporan.md` ini adalah
penunjuk tunggal untuk status pekerjaan closure yang sedang aktif.
