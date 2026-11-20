## Deskripsi Fitur
<!-- Jelaskan fitur atau perubahan yang diimplementasikan pada PR ini -->

## Isu Terkait
<!-- Cantumkan nomor/link issue, misal: Closes #... -->

## Apa yang Dibantu AI
<!-- Jelaskan bagian kode/test/dokumentasi apa saja yang dibantu AI dan apa yang direvisi secara manual -->

## 3 Prompt Kunci
1. <!-- Prompt kunci 1 -->
2. <!-- Prompt kunci 2 -->
3. <!-- Prompt kunci 3 -->

## Risiko & Limitasi
- **Integrasi `DatabasePresensiPort` & Fallback `StubPresensiPort` (Minggu 9 -> Minggu 12)**: `GradeService` kini membaca persentase kehadiran nyata dari tabel `attendance_session` dan `attendance_record` melalui `DatabasePresensiPort`, dengan fallback ke `StubPresensiPort` apabila suatu kelas belum memiliki sesi presensi di database (agar skenario uji terisolasi Minggu 9 tetap berjalan deterministik).
- **Rate Limiter In-Memory & Geofencing GPS Klien (Minggu 12)**: `ScanRateLimiter` (`5` request/menit per NIM) menggunakan sliding-window in-memory untuk proses tunggal (perlu dipindahkan ke Redis pada deployment multi-worker). Koordinat GPS pada `/api/attendance/scan` berasal dari perangkat klien dan divalidasi dengan jarak *Haversine* ($\le 100\text{ m}$ default) + batas akurasi sinyal ($\le 150\text{ m}$) yang dikombinasikan dengan rotasi QR otomatis setiap `120` detik ([`repo-structure/docs/stakeholder-questions-minggu-12.md`](repo-structure/docs/stakeholder-questions-minggu-12.md)).
- **Asumsi Sementara Kelulusan MK (`>= C` / `2.00`)**: Dokumen tugas memuat kontradiksi *"nilai >= D (2.0)"* padahal `D = 1.00` dan `2.00 = C`. Sambil menunggu jawaban tertulis stakeholder ([`repo-structure/docs/stakeholder-questions-minggu-9.md`](repo-structure/docs/stakeholder-questions-minggu-9.md)), `skala_nilai.lulus` diset sementara `True` untuk `A/B/C` dan `False` untuk `D/E` (dapat diubah lewat 1 baris data di DB tanpa mengubah kode).
- **Konfigurasi Default Denda & Simulasi Email Modul Keuangan (Minggu 11)**: Rumus denda keterlambatan (`2%` per 30 hari, maksimal `10%`, `grace_days=0`) dan secret webhook default (`PAYMENT_WEBHOOK_SECRET`) dapat diubah lewat `.env` sambil menunggu konfirmasi stakeholder ([`repo-structure/docs/stakeholder-questions-minggu-11.md`](repo-structure/docs/stakeholder-questions-minggu-11.md)). Pengiriman kwitansi dan reminder email masih disimulasikan melalui `LogChannel("EMAIL")` + tabel `notifikasi`, dan cron `APScheduler` berjalan *in-process* (cocok untuk worker tunggal).
- **Otorisasi Endpoint KRS**: Parameter `dosen_pa_id` pada endpoint `/api/krs/{nim}/approve` dan `/api/krs/{nim}/revise` saat ini masih dikirim melalui *request body* karena modul autentikasi/JWT baru dipasang di endpoint `/api/schedules/*`, `/api/kelas/*/nilai/*`, `/api/finance/*`, dan `/api/attendance/*`.
- **Limitasi Database SQLite (`FOR UPDATE`)**: Uji *pessimistic row lock* (`SELECT ... FOR UPDATE` / `.with_for_update()`) pada modul KRS, Penjadwalan (`Ruangan -> Dosen`), Nilai (`KRSDetail`), dan Keuangan (`Billing`) tidak membuktikan *row-level locking* konkuren secara fisik di SQLite karena SQLite mengabaikan `FOR UPDATE` (harus diverifikasi lanjut pada MySQL atau PostgreSQL).
- **Filter Semester Aktif & Kapasitas Sisi Mahasiswa**: Validasi kapasitas saat mahasiswa mengambil kelas pada `KRSManager` serta pembatasan semester aktif pada seluruh endpoint penjadwalan masih menggunakan nilai default `"20251"` / parameter query dan perlu diperketat pada integrasi akhir.

## Cara Uji
Jalankan seluruh test suite (Unit, Integration, Property-Based Testing, dan API TestClient):
```powershell
$env:PYTHONPATH = "backend"
.\venv\Scripts\pytest.exe backend/test_models_and_schemas.py backend/test_pmb.py backend/tests/test_krs_property.py backend/tests/test_krs_api.py backend/tests/test_schedule.py backend/tests/test_grade.py backend/tests/test_finance.py backend/tests/test_attendance.py -v
```

## AI Usage Log & OPAR
- [x] Entri AI Usage Log dan refleksi **OPAR** (*Observe, Plan, Act, Reflect*) telah diperbarui di [`backend/ai-usage-log.md`](backend/ai-usage-log.md) dan [`repo-structure/prompts/ai-usage-log.md`](repo-structure/prompts/ai-usage-log.md).
- [x] Keputusan arsitektur telah dicatat di [`repo-structure/docs/ADR-architecture-decisions.md`](repo-structure/docs/ADR-architecture-decisions.md).
- [x] Pertanyaan tertulis ke stakeholder atas ambiguitas spesifikasi telah dicatat di [`repo-structure/docs/stakeholder-questions-minggu-9.md`](repo-structure/docs/stakeholder-questions-minggu-9.md), [`repo-structure/docs/stakeholder-questions-minggu-11.md`](repo-structure/docs/stakeholder-questions-minggu-11.md), dan [`repo-structure/docs/stakeholder-questions-minggu-12.md`](repo-structure/docs/stakeholder-questions-minggu-12.md).
