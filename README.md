# Sevima-Mini

Sistem Informasi Akademik Mini (Sevima-Mini) adalah aplikasi berbasis Object-Oriented Programming (OOP) untuk mengelola aktivitas akademik di sebuah institusi pendidikan, seperti pendaftaran mahasiswa baru, pengisian Kartu Rencana Studi (KRS), penjadwalan kelas, pencatatan nilai, serta dilengkapi dengan **Backend RESTful API** menggunakan **FastAPI** dan **SQLAlchemy**.

## Fitur Utama

### 1. Desain Konseptual & OOP (UML & Arsitektur)
- **Manajemen pengguna (User):** Mahasiswa, Dosen, Admin, dan Calon Mahasiswa dengan sistem autentikasi (login/logout). User dirancang sebagai abstract base class.
- **Manajemen mata kuliah (Course):** Kode, nama, SKS, dan daftar prasyarat.
- **Pendaftaran Mahasiswa Baru (PMB):** Melalui kelas CalonMahasiswa dan PendaftaranPMB, dengan pemisahan proses antara pembayaran dan verifikasi hasil seleksi oleh Admin.
- **Pengisian KRS:** Melalui PendaftaranKRS dan Enrollment yang menghubungkan Mahasiswa dan Course, dilengkapi validasi komprehensif (prasyarat, SKS, jadwal, kapasitas) serta *deferred enrollment* setelah pembayaran lunas.
- **Penjadwalan kuliah (Schedule):** Hari, jam, dan ruangan (berelasi komposit dengan Kelas).
- **Pencatatan nilai (Grade):** Nilai angka, nilai huruf, dan bobot, terkait komposisi dengan Enrollment.
- **Desain berbasis prinsip SOLID** (terutama Open/Closed Principle dan Liskov Substitution Principle).
- **Relasi antar kelas** menggunakan Aggregation (relasi lemah) dan Composition (relasi kuat).

### 2. Implementasi Backend API (FastAPI & Database)
- **Modul PMB (Repository Pattern & Dependency Injection):** Pemisahan akses data (`IPMBRepository` & `SQLitePMBRepository`), registrasi calon mahasiswa, verifikasi/persetujuan kelulusan dengan pembuatan **NIM otomatis** aman *race condition*, serta agregasi statistik pendaftar (`GROUP BY`).
- **Modul KRS & Validasi (*Chain of Responsibility*):** Struktur dua tingkat (`krs` + `krs_detail` serta `krs_log` & `notifikasi`) dengan rantai validator `DuplicateValidator -> SKSValidator -> PrerequisiteValidator -> ConflictValidator` bebas *N+1 query* (maksimal 24 SKS, nilai prasyarat $\ge$ C via bobot numerik, deteksi irisan interval jadwal).
- **State Machine KRS, Transaksi ACID, & Penguncian Ganda:** Siklus hidup `DRAFT -> SUBMITTED -> APPROVED / REVISION` melalui tabel transisi `dict[(KRSStatus, Actor)]`, perlindungan `@validates("status")` agar status hanya berubah lewat `transition()`, unit kerja transaksi ACID (`KRSLog` + `Notifikasi` + `rollback`), serta penguncian ganda *Pessimistic Lock* (`with_for_update()`) dan *Optimistic Lock* (`version_id_col` & `diubah_pada`) untuk mencegah *race condition* dan layar basi.
- **Global Exception Handler & Validasi Pydantic:** Penanganan error terpusat melalui `@app.exception_handler(KRSError)` (`400`, `403`, `409`, `422`) dan `@app.exception_handler(ScheduleError)` secara polimorfik lewat `exc.body()` (`404`, `409` bentrok/kapasitas) beserta validasi skema Pydantic (`datetime.time`, `jam_mulai < jam_selesai` → `422`).
- **Challenge Opsional (+10%) — CSP Backtracking Recommender:** Penyusunan rekomendasi jadwal KRS bebas bentrok (`/api/krs/{nim}/recommend`) dengan prioritas MK wajib > pilihan yang hasil akhirnya wajib lolos `default_validators()`.
- **Modul Jadwal & Ruangan (Minggu 7–8):**
  - **Empat Model Domain & Migrasi (`b2c3d4sch008` & `c3d4e5sch009`):** `Ruangan` (PK `kode` & `kapasitas`), `Dosen` (`nidn` unik), `Kelas` (kelas paralel `kuota` & `semester`), `Jadwal` (multi-pertemuan per minggu dengan indeks gabungan `(hari, ruangan_kode)` dan `(hari, dosen_id)`, serta kolom `sequence` untuk versioning `.ics`), dan `Outbox` (tabel *Transactional Outbox*), pemindahan jam keluar dari `MataKuliah`, serta penambahan `KRSDetail.kelas_id`.
  - **Detektor Bentrok 3D (*Naive* + *Grouping + Sort & Sweep*):** Memodelkan penjadwalan sebagai *Constraint Satisfaction Problem* (*Hard* vs *Soft Constraints*) dengan interval setengah terbuka `[jam_mulai, jam_selesai)` untuk mendeteksi `room_conflict` dan `lecturer_conflict`, plus pengecekan kapasitas `max(kuota, terdaftar) <= kapasitas` (`409 Conflict`).
  - **Scheduling Service & Penguncian Pesimis:** `create_schedule` dan `update_schedule` berbagi metode `_simpan()` dengan urutan ketat kunci baris `Ruangan -> Dosen` (`with_for_update()`), query bentrok langsung di SQL memakai indeks gabungan, cek kapasitas, dan tambah objek ke session paling akhir sebelum `commit()`.
  - **Observer Pattern (`typing.Protocol`), Strategy `LogChannel`, & Transactional Outbox:** `ScheduleSubject` dan `NotificationManager` dirangkai sekali saat startup untuk menyiarkan `ScheduleEvent` (frozen dataclass dengan `event_id`, `before`, `after`, dan `EventType`) ke `StudentObserver`, `LecturerObserver`, dan `AdminObserver` dengan isolasi `try/except` per observer serta `LogChannel` (**Email / SMS / Push**) ber-*idempotency key*. Perubahan/penghapusan jadwal menulis baris `outbox` dalam satu transaksi DB, lalu `OutboxDispatcher` mengirimkannya **setelah `commit()`** dengan `FOR UPDATE SKIP LOCKED` dan retry maks. 5× sebelum `failed`.
  - **AI Rescheduler (`LLMClient` + 4 Saringan), Conflict Resolver UI, & RBAC Admin:** Abstraksi `LLMClient.complete()` (`GeminiLLMClient` JSON mode, `OpenRouterLLMClient`, `OpenAILLMClient`, `FakeLLMClient`) dengan perhitungan slot kosong deterministik oleh backend serta 4 saringan ketat (parsing `[`..`]`, skema Pydantic `AISuggestionItem`, cek eksistensi & kapasitas ruangan di DB, dan uji `detect_conflicts_sweep()` calon ID `-1`). Seluruh endpoint manajemen `/api/schedules/*` dilindungi RBAC JWT `require_admin_akademik` (`POST /api/auth/login`) dan terhubung ke dashboard `/dashboard/conflicts`.
  - **Integrasi KRS (`Actor.SYSTEM`) & Ekspor iCalendar (`.ics`):** Perubahan/penghapusan jadwal otomatis memindahkan KRS `SUBMITTED`/`APPROVED` terdampak ke `REVISION` lewat satu pintu `KRS.transition(..., actor=Actor.SYSTEM)` (membiarkan `DRAFT`/`REVISION` utuh) lengkap dengan `KRSLog` dan `Notifikasi` dalam satu transaksi ACID; tersedia juga ekspor `/api/schedules/export.ics` sesuai RFC 5545 (`CRLF`, `UID` stabil, `DTSTART`/`DTEND` `Asia/Jakarta`, `RRULE` `UNTIL` UTC, dan kenaikan `SEQUENCE`).
- **Modul Nilai & Transkrip Bagian 1 (Minggu 9):**
  - **Single Source of Truth (`krs_detail.nilai`), `skala_nilai`, & Migrasi (`d4e5f6grd010`):** Nilai per mahasiswa per kelas disimpan di `krs_detail.nilai` dengan *Foreign Key* ke `skala_nilai.huruf` (`A=4.00, B=3.00, C=2.00, D=1.00, E=0.00` bertipe `NUMERIC(3,2)` / `Decimal` dan kolom `lulus BOOLEAN` berbasis data). Ambiguitas dokumen tugas (`>= D (2.0)`) didokumentasikan pada [`repo-structure/docs/stakeholder-questions-minggu-9.md`](repo-structure/docs/stakeholder-questions-minggu-9.md) dengan asumsi sementara minimal `C` lulus (`A/B/C = True`, `D/E = False`) yang juga dibaca oleh `PrerequisiteValidator`.
  - **Penjaga Input Nilai 2 Lapis (`GradeService` & `DatabasePresensiPort` DIP):** Validasi endpoint idempoten `PUT /api/kelas/{kelas_id}/nilai/{nim}` via `NilaiIn` (`^[A-E]$` $\rightarrow$ `422`), autentikasi JWT `get_current_dosen`, penjaga pertama `is_pengampu(kelas_id, dosen_id)` via tabel `jadwal` (`403 Forbidden`), penguncian baris `KRSDetail` dengan `with_for_update()` (`404`), dan penjaga kedua presensi $\ge 75\%$ melalui protokol `PresensiPort` (terhubung ke `DatabasePresensiPort` Modul Presensi Minggu 12 dengan fallback `StubPresensiPort`, `< 75%` $\rightarrow$ `422`).
  - **Audit Trail `grade_history` (Append-Only) & SQL View `riwayat_nilai`:** Perubahan nilai (termasuk input pertama dengan `nilai_lama = NULL`) beserta stempel waktu UTC dan `alasan` wajib (saat ubah nilai) ditulis dalam **satu transaksi atomik** bersama update `krs_detail.nilai`, lalu disajikan lewat SQL View `riwayat_nilai` (`GET /api/mahasiswa/{nim}/riwayat-nilai`).
  - **Kalkulator IPS & IPK Presisi `Decimal` (*Functional Core, Imperative Shell*):** Fungsi murni `rata`, `hitung_ips`, dan `hitung_ipk` memakai `Decimal` dengan pembulatan `ROUND_HALF_UP` (`0.01`) sekali di akhir (`3.125 -> 3.13`, total SKS nol $\rightarrow$ `0.00`, mata kuliah ulang memilih bobot terbaik per `kode_mk` sebelum menyaring `lulus`), didukung `NilaiRepo` & `GPACalculator` (*compute-on-read* dengan respons string 2 desimal) serta pembanding SQL CTE `calculate_ipk_sql` (`ROW_NUMBER()` + `NULLIF`), dan form web dosen `/dashboard/grades`.
- **Database & Migrasi:** SQLite dengan SQLAlchemy 2.0 ORM (`Mapped` & `mapped_column`), Alembic migrations (`f6g7h8att012 (head)`), dan skrip inisialisasi database.
- **Modul Keuangan / SPP (Minggu 11):**
  - **Payment Schema & Migrasi (`e5f6g7fin011`):** Tabel `payment_method` (`VA_BCA`, `VA_BNI`, `QRIS`, `BANK_TRANSFER`, `MANUAL_CASH`), `billing` (`unpaid`, `partial`, `paid`, `overdue`, `UniqueConstraint(nim, semester)`), `payment` (`transaction_id` unik), serta kolom `program_studi.biaya_spp` bertipe `NUMERIC(14, 2)` / `Decimal` (ROUND_HALF_UP). Ambiguitas spesifikasi dicatat di [`repo-structure/docs/stakeholder-questions-minggu-11.md`](repo-structure/docs/stakeholder-questions-minggu-11.md).
  - **Billing Service & Pemblokiran KRS (`BillingGuardPort` & `TunggakanValidator`):** `generate_billing()` untuk mahasiswa aktif (Teknik Rp 5.000.000, Ekonomi Rp 4.000.000, jatuh tempo `+14` hari, idempoten), `process_payment()` atomik dengan `.with_for_update()` dan logika **cicilan kumulatif** (`amount_paid + amount` vs `amount + late_fee`), perhitungan denda terkonfigurasi (`2%` per 30 hari, cap `10%`, `grace_days=0`), serta **blokir KRS** (`403 KRSBillingBlockedError`) di `add_course`, `remove_course`, dan `submit_krs` selama mahasiswa memiliki tagihan `unpaid`/`partial`/`overdue` (terbuka otomatis saat `paid`).
  - **Payment Webhook Simulation & Receipt Email:** Endpoint `POST /api/finance/webhook` dengan verifikasi `HMAC-SHA256` (`X-Webhook-Signature`), idempotensi `transaction_id`, penanganan status non-sukses (`failed`/`pending`), dan simulasi kwitansi email via `LogChannel("EMAIL")` + tabel `notifikasi`.
  - **APScheduler Cron Jobs, Dashboard Keuangan, & AI Financial Insights:** `FinanceSchedulerManager` (`generate_semester_billing` & `daily_overdue_and_reminder`) yang dikelola via `lifespan` FastAPI, endpoint agregasi real-time `/api/finance/dashboard` & UI `/dashboard/finance` (ringkasan mahasiswa, *collection rate* per prodi, grafik pembayaran bulanan), serta `/api/finance/ai-report` dan `/api/finance/ai-report/csv` dengan agregasi deterministik (`total_revenue_bulan_ini`, *collection rate*, top 10 tunggakan, rekomendasi reminder `Z` mahasiswa tunggakan `>2` bulan) + narasi AI tervalidasi Pydantic & *fallback* deterministik.
- **Modul Presensi QR Code (Minggu 12):**
  - **Skema Presensi (`f6g7h8att012`) & Rotasi QR Otomatis Anti-Replay:** Tabel `attendance_session` (`secret` 128-bit per sesi, koordinat geofence `latitude`/`longitude`/`radius_m`, `UniqueConstraint(kelas_id, tanggal, jam_mulai)`) dan `attendance_record` (`UniqueConstraint(session_id, nim)`, waktu scan UTC, `qr_window`, jarak GPS). Fungsi `generate_attendance_qr()` & endpoint `GET /api/attendance/qr/{schedule_id}` (serta alias `/attendance/qr/{schedule_id}`) memutar token JWT HS256 otomatis setiap `120` detik (`qr_nonce` HMAC-SHA256 + `grace_windows=1`) selama sesi terbuka (`30` menit), menyelesaikan kontradiksi waktu QR 15 menit vs status terlambat 30 menit ([`repo-structure/docs/stakeholder-questions-minggu-12.md`](repo-structure/docs/stakeholder-questions-minggu-12.md)).
  - **Validasi Scan 6 Lapis, Geofencing Haversine, & Rate Limiting (`POST /api/attendance/scan`):** Menegakkan *sliding-window rate limiter* (`ScanRateLimiter`, `5` scan/menit per NIM $\rightarrow$ `429`), verifikasi JWT & rotasi window (`400`/`410`), anti-spoofing NIM saat menggunakan JWT mahasiswa (`403`), validasi jadwal kuliah hari ini di zona waktu `Asia/Jakarta` (`422`), validasi enrollment `KRSStatus.APPROVED` (`403`), anti-duplikat scan (`409`), validasi geolokasi *Haversine* ($\le 100\text{ m}$ default, akurasi GPS $\le 150\text{ m}$ $\rightarrow$ `403`/`422`), dan kalkulasi status `hadir` ($\le 15$ menit) vs `terlambat` ($15\text{–}30$ menit).
  - **Attendance Report (`< 75%` Warning), Ekspor Excel (`.xlsx`), & Integrasi `DatabasePresensiPort`:** Rekap kehadiran per mahasiswa (`/api/attendance/reports/student/{nim}`) dan per kelas (`/api/attendance/reports/class/{kelas_id}`), ekspor Excel 3 sheet (`/api/attendance/reports/class/{kelas_id}/export.xlsx` menggunakan `openpyxl`), serta penyuntikan `DatabasePresensiPort` ke `GradeService` agar penjaga input nilai `< 75%` membaca data presensi QR nyata.
  - **AI Attendance Insights & Dashboard Presensi (`/dashboard/attendance`):** Endpoint `POST /api/attendance/ai-insights` (analisis JSON array `attendance_records`) dan `GET /api/attendance/ai-insights` (analisis langsung dari DB) mendeteksi mahasiswa berisiko `< 75%` (*early warning*), pola absen hari/waktu per mahasiswa (*"Mahasiswa X sering absent Senin pagi -> hubungi untuk konseling"*), dan kelas dengan tingkat absen tinggi (*"Kelas Y di jam 07:00 absen rate 40% -> pertimbangkan reschedule"*) secara deterministik + pengayaan opsional `LLMClient`.
- **Automated Testing (206 Passed):** Piramida pengujian lengkap menggunakan `pytest` dan `hypothesis` mencakup unit test validator & state machine (`40`), *Property-Based Testing* KRS (`48`: **2×1000 contoh acak** SKS & bentrok, **42 transisi ilegal** dari 48 kombinasi, **200 contoh CSP**), integrasi PMB (`8`), API KRS (`6`), Modul Jadwal (`24`: 7 kasus bug AI, 2×300 properti & differential test `Sort & Sweep` vs `Naive`, 4 tes Minggu 8, RBAC, & `.ics`), Modul Nilai Minggu 9 (`23` di `test_grade.py`), Modul Keuangan Minggu 11 (`31` di `test_finance.py`), serta Modul Presensi Minggu 12 (`26` di `test_attendance.py`: unit test terparameterisasi waktu/rotasi/persentase, **2×200 properti `Hypothesis`** persentase & *Haversine*, siklus rotasi QR anti-replay, geofencing GPS, *rate limiter* `429`, integrasi `DatabasePresensiPort` ke `GradeService`, ekspor Excel `.xlsx`, AI Attendance Analyzer + guardrail `FakeLLMClient`, & UI `/dashboard/attendance`).

## Ringkasan Endpoint API, State Machine KRS, & Alur Penjadwalan

### Daftar Endpoint Utama

| Modul | Method & Endpoint | Body Utama | Status HTTP | Keterangan |
| :--- | :--- | :--- | :--- | :--- |
| **Auth** | `POST /api/auth/login` | `email`, `password` | `200`, `401`, `422` | Autentikasi & penerbitan JWT Bearer token |
| **PMB** | `POST /api/pmb/register` | Data calon mahasiswa | `201`, `409`, `422` | Registrasi pendaftar baru |
| **PMB** | `GET /api/pmb/status/{id}` | — | `200`, `404` | Cek status pendaftaran |
| **PMB** | `PUT /api/pmb/approve/{id}` | — | `200`, `404`, `409` | Approval & generate NIM otomatis |
| **PMB** | `GET /api/pmb/stats` | — | `200` | Statistik pendaftar (`GROUP BY`) |
| **KRS** | `POST /api/krs/{nim}/courses` | `kode_mk` | `201`, `400`, `409` | Tambah MK (saat `DRAFT`/`REVISION`) |
| **KRS** | `DELETE /api/krs/{nim}/courses/{kode_mk}` | — | `200`, `400`, `409` | Hapus MK (saat `DRAFT`/`REVISION`) |
| **KRS** | `POST /api/krs/{nim}/submit` | — | `200`, `400`, `409` | Validasi penuh & ajukan KRS |
| **KRS** | `POST /api/krs/{nim}/approve` | `dosen_pa_id`, `version` | `200`, `403`, `409` | Setujui KRS (satu unit kerja ACID) |
| **KRS** | `POST /api/krs/{nim}/revise` | `dosen_pa_id`, `catatan`, `version` | `200`, `403`, `409`, `422` | Minta revisi KRS dengan catatan wajib |
| **KRS** | `POST /api/krs/{nim}/recommend` | `wajib_codes`, `pilihan_codes`, `max_sks` | `200` | Rekomendasi jadwal CSP tervalidasi |
| **Schedule** | `GET /api/schedules/export.ics` | Query `semester`, `nim` (opsional) | `200` | Ekspor iCalendar `.ics` publik/mahasiswa (RFC 5545) |
| **Schedule** | `GET / POST /api/schedules/rooms` | Data ruangan (`kode`, `kapasitas`) | `200`, `201`, `401`, `403`, `409` | Daftar & tambah master ruangan (RBAC Admin) |
| **Schedule** | `GET / POST /api/schedules/lecturers` | Data dosen (`nidn`, `nama`) | `200`, `201`, `401`, `403`, `409` | Daftar & tambah master dosen (RBAC Admin) |
| **Schedule** | `GET / POST /api/schedules/classes` | Data kelas (`kode_mk`, `nama_kelas`, `kuota`) | `200`, `201`, `401`, `403`, `404`, `409` | Daftar & tambah kelas paralel (RBAC Admin) |
| **Schedule** | `GET /api/schedules/courses` | — | `200`, `401`, `403` | Katalog mata kuliah (RBAC Admin) |
| **Schedule** | `GET / POST /api/schedules` | Data jadwal (`kelas_id`, `ruangan_kode`, `dosen_id`, `hari`, `jam_mulai`, `jam_selesai`) | `200`, `201`, `401`, `403`, `404`, `409`, `422` | Daftar & buat jadwal (lock, cek bentrok SQL, kapasitas `409`, RBAC Admin) |
| **Schedule** | `GET /api/schedules/{id}` | — | `200`, `401`, `403`, `404` | Detail satu jadwal kuliah (RBAC Admin) |
| **Schedule** | `PUT / DELETE /api/schedules/{id}` | Perubahan jadwal (`hari`, `jam_mulai`, `jam_selesai`, `ruangan_kode`) | `200`, `401`, `403`, `404`, `409`, `422` | Ubah/hapus jadwal, invalidasi KRS -> `REVISION`, tulis Outbox, & dispatch setelah komit |
| **Schedule** | `GET /api/schedules/conflicts` | — | `200`, `401`, `403` | Deteksi bentrok aktif via *Grouping + Sort & Sweep* (RBAC Admin) |
| **Schedule** | `POST /api/schedules/detect` | `schedules[]` | `200`, `401`, `403`, `422` | Deteksi bentrok ruangan & dosen stateless (RBAC Admin) |
| **Schedule** | `POST /api/schedules/{id}/suggest-alternatives` | — | `200`, `401`, `403`, `404` | 3 saran jadwal alternatif (`LLMClient` + 4 saringan, RBAC Admin) |
| **Schedule** | `GET /api/schedules/notifications` | — | `200`, `401`, `403` | Log simulasi notifikasi Observer (Email/SMS/Push, RBAC Admin) |
| **Schedule** | `GET /api/schedules/outbox` | — | `200`, `401`, `403` | Daftar baris Transactional Outbox (`pending`/`sent`/`failed`, RBAC Admin) |
| **Schedule** | `POST /api/schedules/outbox/dispatch` | — | `200`, `401`, `403` | Proses ulang baris Outbox `pending` (RBAC Admin) |
| **Schedule** | `POST /api/schedules/seed-demo` | — | `200`, `401`, `403` | Muat skenario data demo bentrok & akun Admin demo (RBAC Admin) |
| **Grades** | `GET /api/kelas/pengampu` | — | `200`, `401`, `403` | Daftar kelas yang diampu oleh dosen login (`get_current_dosen`) |
| **Grades** | `GET /api/kelas/{kelas_id}/peserta` | — | `200`, `401`, `403`, `404` | Daftar peserta kelas beserta persentase presensi & kelayakan input nilai |
| **Grades** | `PUT /api/kelas/{kelas_id}/nilai/{nim}` | `huruf` (`A..E`), `alasan` (wajib saat ubah) | `200`, `401`, `403`, `404`, `422` | Input/ubah nilai oleh dosen pengampu (`>= 75%` presensi) + audit `grade_history` atomik |
| **Grades** | `GET /api/mahasiswa/{nim}/ips/{semester}` | — | `200` | Hitung IPS semester (semua MK termasuk D/E, string 2 desimal `ROUND_HALF_UP`) |
| **Grades** | `GET /api/mahasiswa/{nim}/ipk` | — | `200` | Hitung IPK kumulatif (*compute-on-read*, nilai terbaik per MK lulus, string 2 desimal) |
| **Grades** | `GET /api/mahasiswa/{nim}/riwayat-nilai` | — | `200` | Riwayat perubahan nilai mahasiswa dari SQL View `riwayat_nilai` |
| **Grades** | `POST /api/grades/seed-demo` | — | `200` | Muat skenario data dummy `Rina` (presensi 90%) & `Budi` (presensi 70%) |
| **Finance** | `GET /api/finance/payment-methods` | — | `200` | Daftar metode pembayaran SPP aktif (`VA_BCA`, `VA_BNI`, `QRIS`, dll.) |
| **Finance** | `POST /api/finance/billings/generate` | `semester`, `semester_start` (opsional) | `200`, `401`, `403`, `422` | Generate tagihan SPP semester mahasiswa aktif (RBAC Admin) |
| **Finance** | `POST /api/finance/billings/refresh-overdue` | `as_of`, `reminder_before_days` | `200`, `401`, `403` | Hitung denda keterlambatan, update `overdue`, & kirim reminder (RBAC Admin) |
| **Finance** | `GET /api/finance/billings` | Query `nim`, `semester`, `status` | `200`, `401`, `403` | Daftar tagihan SPP beserta filter (RBAC Admin) |
| **Finance** | `POST /api/finance/payments` | `billing_id`, `amount`, `method_code` | `201`, `401`, `403`, `404`, `409`, `422` | Catat pembayaran manual atomik & update status kumulatif (RBAC Admin) |
| **Finance** | `POST /api/finance/webhook` | Payload gateway + header `X-Webhook-Signature` | `200`, `401`, `404`, `422` | Terima webhook gateway terverifikasi HMAC-SHA256 (idempoten) & kirim receipt |
| **Finance** | `POST /api/finance/webhook/sign` | `billing_id`, `transaction_id`, `amount`, `status` | `200`, `401`, `403` | Helper signing HMAC-SHA256 & contoh perintah `curl` (RBAC Admin) |
| **Finance** | `GET /api/finance/dashboard` | Query `semester` (opsional) | `200`, `401`, `403` | Data real-time per mahasiswa, collection rate prodi, & grafik bulanan (RBAC Admin) |
| **Finance** | `GET /api/finance/students/{nim}/summary` | Query `semester` (opsional) | `200` | Ringkasan tagihan, terbayar, sisa, & status blokir KRS mahasiswa |
| **Finance** | `GET /api/finance/ai-report` & `POST .../csv` | Query `as_of` / body `csv_data` | `200`, `401`, `403`, `422` | Laporan AI Financial Insights JSON dari DB atau CSV (RBAC Admin) |
| **Finance** | `GET /api/finance/scheduler/jobs` & `.../receipts` | — | `200`, `401`, `403` | Status cron job `APScheduler` & log simulasi receipt email (RBAC Admin) |
| **Finance** | `POST /api/finance/seed-demo` | Query `semester` | `200`, `401`, `403` | Muat skenario demo tagihan Teknik/Ekonomi, cicilan, & `overdue` (RBAC Admin) |
| **Attendance** | `GET /api/attendance/qr/{schedule_id}` | Query `latitude`, `longitude`, `radius_m` (opsional) | `200`, `403`, `404`, `410` | Generate gambar QR PNG berotasi otomatis (`120s`, `HMAC-SHA256`) + alias `/attendance/qr/{id}` |
| **Attendance** | `GET /api/attendance/qr/{schedule_id}/info` | Query `latitude`, `longitude`, `radius_m` (opsional) | `200`, `403`, `404` | Metadata JSON sesi presensi, token QR aktif, `qr_window`, & *countdown* rotasi |
| **Attendance** | `POST /api/attendance/sessions` | `schedule_id`, `tanggal`, `pertemuan_ke`, `latitude`, `longitude`, `radius_m` | `201`, `403`, `404`, `409`, `422` | Buka sesi presensi baru untuk pertemuan kuliah tertentu |
| **Attendance** | `POST /api/attendance/sessions/{id}/close` | — | `200`, `403`, `404` | Tutup sesi presensi secara eksplisit |
| **Attendance** | `POST /api/attendance/scan` | `token`, `nim` (opsional bila pakai JWT Mhs), `latitude`, `longitude`, `accuracy_m` | `200`, `400`, `403`, `409`, `410`, `422`, `429` | Scan QR mahasiswa (validasi JWT/rotasi, jadwal, KRS, duplikat, GPS *Haversine*, *rate limit*) + alias `/attendance/scan` |
| **Attendance** | `GET /api/attendance/reports/student/{nim}` | — | `200`, `404` | Rekap persentase kehadiran per MK untuk seorang mahasiswa |
| **Attendance** | `GET /api/attendance/reports/class/{kelas_id}` | — | `200`, `404` | Rekap presensi kelas & daftar mahasiswa warning `< 75%` |
| **Attendance** | `GET /api/attendance/reports/class/{kelas_id}/export.xlsx` | — | `200`, `404` | Ekspor laporan presensi kelas ke Excel (`.xlsx` 3 sheet) untuk dosen |
| **Attendance** | `GET / POST /api/attendance/ai-insights` | Query `kelas_id`, `semester` / body `attendance_records[]` | `200`, `422` | Analisis pola kehadiran, *early warning* `< 75%`, & rekomendasi (`insights` + `actions`) |
| **Attendance** | `POST /api/attendance/seed-demo` | — | `200` | Muat skenario demo Kelas `IF301-A`, 5 mahasiswa, 4 sesi historis Senin 07:00, & jadwal aktif hari ini |
| **UI** | `GET /dashboard/conflicts` | — | `200` | Halaman **Conflict Resolver UI** (dengan bilah login Admin JWT) |
| **UI** | `GET /dashboard/grades` | — | `200` | Halaman **Form Input Nilai Dosen & Audit Trail** (dengan bilah login Dosen JWT) |
| **UI** | `GET /dashboard/finance` | — | `200` | Halaman **Dashboard Keuangan (SPP), Webhook Simulator, & AI Insights** |
| **UI** | `GET /dashboard/attendance` | — | `200` | Halaman **Dashboard Presensi QR Berotasi, Scanner GPS, Rekap Excel, & AI Insights** |

### Alur Transisi Sah State Machine KRS

1. `DRAFT -> SUBMITTED` — dilakukan oleh **Mahasiswa** pemilik KRS (minimal 1 MK & lolos seluruh validator).
2. `SUBMITTED -> APPROVED` — dilakukan oleh **Dosen PA** mahasiswa tersebut (`krs.dosen_pa_id`).
3. `SUBMITTED -> REVISION` — dilakukan oleh **Dosen PA** mahasiswa tersebut dengan `catatan_revisi` wajib diisi.
4. `REVISION -> SUBMITTED` — dilakukan oleh **Mahasiswa** setelah memperbaiki isi KRS.
5. `SUBMITTED -> REVISION` — dilakukan oleh **Sistem** (`Actor.SYSTEM`) saat jadwal kelas yang diambil berubah atau dihapus.
6. `APPROVED -> REVISION` — dilakukan oleh **Sistem** (`Actor.SYSTEM`) saat jadwal kelas yang diambil berubah atau dihapus (mengosongkan `approved_at`).

> **Catatan keamanan model:** Penulisan langsung `krs.status = ...` di luar `KRS.transition()` diblokir otomatis oleh `@validates("status")` (`TransitionError` / HTTP `409`). Method `KRS.invalidate_by_schedule_change()` mendelegasikan langsung ke `KRS.transition(KRSStatus.REVISION, actor=Actor.SYSTEM, catatan=reason)` dalam transaksi ACID milik `SchedulingService` (KRS `DRAFT` dan `REVISION` tidak disentuh), disertai pencatatan `KRSLog` dan `Notifikasi`.

### Alur Modul Jadwal & Ruangan (Minggu 7–8)

1. **Deteksi Bentrok 3D (*Grouping + Sort & Sweep*):** `GET /api/schedules/conflicts` mengelompokkan jadwal per `(hari, ruangan_kode)` dan `(hari, dosen_id)` pada interval setengah terbuka `[jam_mulai, jam_selesai)` untuk mendeteksi `room_conflict` dan `lecturer_conflict` secara deterministik (diverifikasi identik terhadap versi *Naive* `itertools.combinations`).
2. **Saran Alternatif AI (`LLMClient` + 4 Saringan):** Admin login lalu memilih jadwal bentrok pada `/dashboard/conflicts` dan memanggil `POST /api/schedules/{id}/suggest-alternatives` untuk memperoleh maks. 3 opsi `[{hari, jam, ruangan, reason}]` yang lolos 4 saringan (parsing `[`..`]`, skema Pydantic, kapasitas ruang DB, dan `detect_conflicts_sweep` calon ID `-1`).
3. **Satu Transaksi ACID (`PUT /api/schedules/{id}`):** Mengunci baris `Ruangan -> Dosen`, memvalidasi bentrok di SQL dan kapasitas (`409`), memperbarui tabel `jadwal` dan menaikkan `sequence`, memindahkan KRS `SUBMITTED`/`APPROVED` terdampak ke `REVISION` via `Actor.SYSTEM`, serta menulis baris `Outbox` (`pending`) sebelum **`COMMIT`**.
4. **Dispatcher & Ekspor `.ics`:** Setelah `COMMIT`, `OutboxDispatcher.run()` mengunci baris `pending` (`SKIP LOCKED`) dan memanggil `ScheduleSubject.notify()` (`try/except` per observer, kunci idempotensi di `LogChannel`, retry maks. 5× $\rightarrow$ `failed`); mahasiswa dapat mengunduh jadwal terbaru melalui `GET /api/schedules/export.ics`.

### Alur Modul Nilai & Transkrip Bagian 1 (Minggu 9)

1. **Penjaga 2 Lapis (`PUT /api/kelas/{kelas_id}/nilai/{nim}`):** Skema Pydantic `NilaiIn` memvalidasi huruf tunggal `^[A-E]$` (`422`), `get_current_dosen` mengambil identitas dosen dari token JWT (`401`/`403`), `GradeService` memeriksa `is_pengampu(kelas_id, dosen_id)` (`403`) sebelum menyentuh data mahasiswa, mengunci `KRSDetail` via `.with_for_update()` (`404`), dan mengecek presensi $\ge 75\%$ lewat `PresensiPort` (`StubPresensiPort` hingga Minggu 12).
2. **Audit Trail Atomik (`grade_history` & `riwayat_nilai`):** Jika nilai sama, endpoint bersifat idempoten (*no-op*); jika mengubah nilai lama, `alasan` wajib diisi (`422`). Penambahan baris `grade_history` (`nilai_lama` nullable untuk input pertama, UTC) dan pembaruan `krs_detail.nilai` dikomit dalam satu transaksi DB, lalu terbaca melalui SQL View `riwayat_nilai`.
3. **IPS & IPK Presisi `Decimal` (*Compute-on-Read*):** `GPACalculator` membaca `records(nim)` (`nilai IS NOT NULL`) dan `skala_nilai` dari `NilaiRepo` lalu menyerahkannya ke fungsi murni `hitung_ips` dan `hitung_ipk` (`Decimal` + `ROUND_HALF_UP` sekali di akhir, bobot terbaik per `kode_mk` lebih dulu baru menyaring `lulus == True`). Nilai dikirim ke API sebagai string 2 desimal agar tidak terkonversi ke `float`.

### Alur Modul Keuangan / SPP (Minggu 11)

1. **Generator Tagihan & Penjadwalan `APScheduler`:** `BillingService.generate_billing()` membuat tagihan awal semester secara idempoten (`UniqueConstraint(nim, semester)`) bagi seluruh mahasiswa berstatus `approved` dengan jatuh tempo `+14` hari dan tarif dari `program_studi.biaya_spp` / fallback konfigurasi (`Teknik = 5jt`, `Ekonomi = 4jt`). `FinanceSchedulerManager` menjalankan cron awal semester (`generate_semester_billing`) dan cek harian pukul 07:00 (`daily_overdue_and_reminder`) untuk memperbarui denda/status `overdue` serta mengirim reminder otomatis.
2. **Pemrosesan Pembayaran Kumulatif, Webhook HMAC, & Receipt:** `process_payment()` mengunci baris `Billing` (`.with_for_update()`), mengevaluasi **total terbayar kumulatif** (`amount_paid + amount` vs `amount + late_fee`), mencatat `PaymentTransaction` (`transaction_id` unik) dan `Notifikasi` dalam satu transaksi ACID, lalu mengirim simulasi receipt email via `LogChannel("EMAIL")`. Endpoint `POST /api/finance/webhook` memverifikasi signature `HMAC-SHA256` sebelum memproses transaksi secara idempoten.
3. **Blokir KRS & AI Financial Insights:** `KRSManager` (via `BillingGuardPort`) menolak `add_course`, `remove_course`, dan `submit_krs` dengan HTTP `403` (`KRSBillingBlockedError`) bila mahasiswa memiliki tagihan `unpaid`/`partial`/`overdue` dan langsung membuka akses begitu status menjadi `paid`. Endpoint `/api/finance/ai-report` dan `/api/finance/ai-report/csv` menghitung angka revenue, *collection rate*, top 10 tunggakan, dan rekomendasi tunggakan `>2` bulan secara deterministik sebelum meminta narasi teranonimasi dari `LLMClient`.

### Alur Modul Presensi QR Code (Minggu 12)

1. **Sesi Presensi & Rotasi QR Otomatis (`GET /api/attendance/qr/{schedule_id}`):** Dosen membuka/meminta QR untuk jadwal kuliah hari ini (opsional menyertakan koordinat ruang kuliah `latitude`, `longitude`, `radius_m`). Sesi dibuka selama `30` menit, sedangkan token JWT HS256 berotasi otomatis setiap `120` detik (`window_index` + `qr_nonce` HMAC-SHA256 dengan `grace_windows=1`) agar foto QR lama langsung kedaluwarsa (`410 Gone`).
2. **Validasi Scan 6 Lapis & Geofencing Haversine (`POST /api/attendance/scan`):** Memeriksa *sliding-window rate limiter* (`5` scan/menit per NIM $\rightarrow$ `429`), mendekode JWT & rotasi window, mencegah spoofing NIM jika mahasiswa login, memastikan jadwal berlangsung hari ini (`Asia/Jakarta`), memverifikasi mahasiswa terdaftar di kelas pada KRS `APPROVED` (`403`), menolak scan duplikat (`409`), memvalidasi jarak GPS *Haversine* $\le 100\text{ m}$ & akurasi $\le 150\text{ m}$ (`403`/`422`), lalu mencatat status `hadir` ($\le 15$ menit) atau `terlambat` ($15\text{–}30$ menit).
3. **Rekap, Ekspor Excel, Integrasi `DatabasePresensiPort`, & AI Analyzer:** `DatabasePresensiPort` langsung menyuplai persentase kehadiran nyata ke `GradeService` (menolak input nilai `< 75%` dengan `422 PresensiKurangError`). Dosen dapat mengunduh rekap `.xlsx` 3 sheet (`/api/attendance/reports/class/{kelas_id}/export.xlsx`) dan menjalankan `AI Attendance Analyzer` (`/api/attendance/ai-insights`) untuk mendeteksi pola absen hari/jam serta *early warning* mahasiswa berisiko `< 75%`.

## Struktur Proyek

```text
.github/
└── PULL_REQUEST_TEMPLATE.md     # Template Pull Request (Fitur, Prompt, Risiko, OPAR)

repo-structure/
├── diagrams/
│   ├── class-diagram.mmd        # Diagram kelas UML (Mermaid)
│   ├── usecase-diagram.puml     # Diagram use case UML (PlantUML)
│   ├── sequence-krs.mmd         # Diagram sekuens KRS (Mermaid)
│   ├── sequence-pmb.mmd         # Diagram sekuens PMB (Mermaid)
│   └── sequence-schedule-observer.mmd  # Diagram sekuens Observer Pattern & Jadwal (Mermaid)
├── docs/
│   ├── ADR-architecture-decisions.md  # Keputusan Arsitektur Sistem (ADR-001)
│   ├── stakeholder-questions-minggu-9.md   # Klarifikasi kontradiksi spesifikasi >= D (2.0) ke stakeholder
│   ├── stakeholder-questions-minggu-11.md  # Klarifikasi celah & asumsi konfigurasi Modul Keuangan (Minggu 11)
│   └── stakeholder-questions-minggu-12.md  # Klarifikasi kontradiksi waktu QR & geofencing Modul Presensi (Minggu 12)
└── prompts/
    └── ai-usage-log.md          # Catatan penggunaan AI selama perancangan UML & arsitektur (Log 01–18)

backend/
├── alembic/                     # Migrasi database Alembic
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       ├── 3f3403fad0b5_tabel_pmb.py
│       ├── 8b2104krs005_tabel_krs.py
│       ├── 9c3205krs006_krs_state_columns.py
│       ├── a1b2c3sch007_tabel_jadwal_ruangan.py
│       ├── b2c3d4sch008_refactor_domain_jadwal.py
│       ├── c3d4e5sch009_outbox_dan_sequence_jadwal.py
│       ├── d4e5f6grd010_skala_nilai_grade_history.py
│       ├── e5f6g7fin011_tabel_keuangan_spp.py
│       └── f6g7h8att012_tabel_presensi_qr.py
├── alembic.ini                  # Konfigurasi Alembic
├── app/
│   ├── core/                    # Konfigurasi (DB, Security JWT Admin/Dosen/Mahasiswa, env AI, Keuangan, & Presensi)
│   ├── models/                  # Model SQLAlchemy 2.0 ORM
│   │   ├── attendance.py        # AttendanceSession, AttendanceRecord, AttendanceStatus, & AttendanceError (Minggu 12)
│   │   ├── finance.py           # Billing, PaymentTransaction, PaymentMethod, BillingStatus, & FinanceError (Minggu 11)
│   │   ├── grade.py             # SkalaNilai, GradeHistory, RIWAYAT_NILAI_VIEW_SQL, GradeError, & Grade legacy
│   │   ├── schedule.py          # Model Ruangan, Dosen, Kelas, Jadwal (sequence), Outbox, & ScheduleError (Minggu 7–8)
│   │   └── ...                  # Model PMB, KRS (KRSBillingBlockedError & FK skala_nilai), User, Course, Enrollment, Payment
│   ├── repositories/            # Repository Pattern (IPMBRepository & SQLite)
│   ├── routers/                 # Endpoint FastAPI
│   │   ├── attendance.py        # Endpoint QR Presensi Berotasi, Scan GPS, Laporan Excel, & AI Insights (/api/attendance)
│   │   ├── auth.py              # Endpoint Login JWT Admin, Dosen, & Mahasiswa (/api/auth/login)
│   │   ├── finance.py           # Endpoint Tagihan SPP, Webhook HMAC, Dashboard, Scheduler, & AI Report (/api/finance)
│   │   ├── grade.py             # Endpoint Input Nilai, IPS/IPK, Riwayat, & Seed Demo (/api/kelas/*/nilai/*, /api/mahasiswa/*)
│   │   ├── pmb.py               # Endpoint PMB (/api/pmb)
│   │   ├── krs.py               # Endpoint KRS & CSP Recommender (/api/krs)
│   │   └── schedule.py          # Endpoint Jadwal, Outbox, Conflict, AI, .ics, & Logs (/api/schedules)
│   ├── schemas/                 # Skema Validasi Pydantic (termasuk schedule.py, grade.py, finance.py, & attendance.py)
│   ├── services/                # Business Logic Layer
│   │   ├── attendance_ai_analyzer.py # AI Attendance Analyzer JSON (pola absen hari/jam, early warning <75%, & guardrail LLM)
│   │   ├── attendance_rules.py  # Pure core presensi (status hadir/terlambat, rotasi window HMAC, Haversine, & persentase Decimal)
│   │   ├── attendance_service.py # AttendanceService, ScanRateLimiter, generate_attendance_qr, DatabasePresensiPort, & Excel export
│   │   ├── billing_service.py   # BillingService, BillingGuardPort, Webhook HMAC, Email Receipt, & Dashboard (Minggu 11)
│   │   ├── calendar_exporter.py # Ekspor iCalendar RFC 5545 (.ics) dengan CRLF, UID, RRULE UTC, & SEQUENCE
│   │   ├── conflict_detector.py # Detektor bentrok Naive & Grouping + Sort & Sweep + cek_kapasitas
│   │   ├── finance_ai_report.py # AI Financial Insights JSON (deterministik + LLMClient + fallback)
│   │   ├── finance_calculator.py # Pure core Decimal (denda, status tagihan, tarif SPP, HMAC, & parser CSV)
│   │   ├── finance_scheduler.py # Penjadwalan otomatis APScheduler (generate semester & reminder harian)
│   │   ├── gpa_calculator.py    # Pure core Decimal (rata, hitung_ips, hitung_ipk), NilaiRepo, GPACalculator, & SQL CTE
│   │   ├── grade_service.py     # PresensiPort + StubPresensiPort & GradeService (403, FOR UPDATE, audit trail 1 transaksi)
│   │   ├── schedule_observer.py # Observer Protocol, LogChannel (idempotency key), & OutboxDispatcher
│   │   ├── schedule_recommender.py # LLMClient + 4 Saringan Pydantic/Kapasitas/Bentrok + Rule-Based Fallback
│   │   ├── scheduling_service.py   # Layanan Penjadwalan (locking pesimis, SQL conflict, Outbox & KRS ACID)
│   │   └── ...                  # pmb_service, krs_manager, krs_validator (TunggakanValidator), krs_recommender
│   ├── static/                  # Dashboard & Form Web UI
│   │   ├── attendance_dashboard.html # Dashboard Presensi QR Berotasi, Scanner GPS, Rekap Excel, & AI Insights (/dashboard/attendance)
│   │   ├── conflict_resolver.html
│   │   ├── finance_dashboard.html # Dashboard Keuangan SPP, Simulator Webhook, & AI Insights (/dashboard/finance)
│   │   └── grade_input.html     # Form web input nilai dosen pengampu & audit trail (/dashboard/grades)
│   └── main.py                  # Entry Point FastAPI, Lifespan Scheduler, Exception Handler, & Dashboard UI
├── tests/
│   ├── test_attendance.py       # Unit, 2 Properti Hypothesis, Rotasi QR, Geofencing GPS, Rate Limit, Excel, & AI Insights (Minggu 12)
│   ├── test_finance.py          # Unit, 2 Properti Hypothesis, Webhook HMAC, Blokir KRS, APScheduler, AI Report, & UI (Minggu 11)
│   ├── test_grade.py            # Unit (11 IPK + 3 IPS + tukar skala), 3 Properti Hypothesis, Integration, & API/UI (Minggu 9)
│   ├── test_krs_api.py          # API Integration Testing KRS (TestClient)
│   ├── test_krs_property.py     # Property-Based Testing (Hypothesis) & 42 Transisi Ilegal (48 Kombinasi)
│   └── test_schedule.py         # Unit, Property, 4 Tes Minggu 8, RBAC, Ekspor .ics, & API/UI Tests
├── init_db.py                   # Skrip Inisialisasi & Seeding Database
├── test_models_and_schemas.py   # Unit & Integration Test Model, Validator, & State Machine KRS
├── test_pmb.py                  # API Integration Testing PMB (Pytest)
├── requirements.txt             # Daftar Dependensi Python
└── ai-usage-log.md              # Catatan penggunaan AI pengembangan backend & refleksi OPAR (Minggu 6–12)
```

## Teknologi & Tools

- **Bahasa Pemrograman:** Python
- **Backend Framework & Scheduler:** FastAPI, Uvicorn, APScheduler
- **ORM, Migrasi, & Database:** SQLAlchemy 2.0, Alembic, SQLite
- **Validasi, HTTP Client, & Pengujian:** Pydantic, `httpx` (integrasi opsional LLM API), Pytest, Hypothesis
- **Frontend Admin UI:** HTML5, CSS3, Vanilla JavaScript (`/dashboard/conflicts`, `/dashboard/grades`, `/dashboard/finance`, `/dashboard/attendance`)
- **Diagrams:** Mermaid (.mmd) untuk Class Diagram & Sequence Diagram, PlantUML (.puml) untuk Use Case Diagram
- **Dokumentasi & Arsitektur:** Markdown, Architecture Decision Records (ADR), OPAR

## Cara Menjalankan & Melihat

1. **Diagram UML:** Dapat dilihat menggunakan renderer Mermaid (.mmd) dan PlantUML (.puml) di VS Code (PlantUML/Mermaid Preview) atau GitHub.
2. **Instalasi Dependensi Backend:**
   ```bash
   pip install -r backend/requirements.txt
   ```
3. **Konfigurasi AI Opsional (`.env`):**
   - Tambahkan `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, atau `OPENAI_API_KEY` (serta `AI_MODEL` jika ingin menentukan model) di `.env` untuk memakai LLM sungguhan pada fitur rekomendasi rescheduling.
   - Jika tidak diisi, sistem otomatis memakai *rule-based fallback* yang tetap bebas bentrok dan aman kapasitas.
4. **Inisialisasi Database & Migrasi Alembic:**
   ```bash
   python backend/init_db.py
   cd backend && alembic upgrade head
   ```
5. **Menjalankan Seluruh Test Suite (Lintas OS — Windows PowerShell & Linux/macOS):**
   ```bash
   pytest -o pythonpath=backend backend/test_models_and_schemas.py backend/test_pmb.py backend/tests/test_krs_property.py backend/tests/test_krs_api.py backend/tests/test_schedule.py backend/tests/test_grade.py backend/tests/test_finance.py backend/tests/test_attendance.py -v
   ```
6. **Menjalankan Server Backend (dapat dijalankan dari root repositori maupun dari folder `backend/` karena `DATABASE_URL` default otomatis menunjuk ke `backend/pmb.db`):**
   ```powershell
   $env:PYTHONPATH = "backend"
   .\backend\venv\Scripts\uvicorn.exe app.main:app --reload --port 8000
   ```
   *(atau `cd backend && uvicorn app.main:app --reload` jika `venv` sudah diaktifkan)*
   * Akses dokumentasi API interaktif (Swagger UI) di: http://127.0.0.1:8000/docs
   * Akses **Conflict Resolver Admin UI** di: http://127.0.0.1:8000/dashboard/conflicts (klik **Login Admin** dengan akun demo `admin.akademik@sevima.ac.id` / `admin123`, lalu klik **Muat Data Demo Bentrok**).
   * Akses **Form Input Nilai Dosen & Audit Trail** di: http://127.0.0.1:8000/dashboard/grades (klik **Muat Data Demo (Rina 90% & Budi 70%)**, lalu klik **Login Dosen Pengampu** dengan akun demo `dosen.pengampu@sevima.ac.id` / `dosen123`).
   * Akses **Dashboard Keuangan (SPP)** di: http://127.0.0.1:8000/dashboard/finance (login Admin `admin.akademik@sevima.ac.id` / `admin123`, lalu klik **Muat Data Demo** untuk menguji tagihan Teknik/Ekonomi, blokir KRS, simulasi webhook + cURL, serta AI Financial Insights).
   * Akses **Dashboard Presensi QR Code & AI Insights (Minggu 12)** di: http://127.0.0.1:8000/dashboard/attendance (klik **1. Muat Data Demo Presensi** untuk menampilkan QR berotasi otomatis 120 detik, menguji simulasi scan mahasiswa di dalam/luar radius GPS *Haversine*, mengunduh rekap `.xlsx`, dan melihat *early warning* AI Attendance Insights).
   * Unduh jadwal kuliah dalam format **iCalendar (.ics)** di: http://127.0.0.1:8000/api/schedules/export.ics (opsional `?semester=20251&nim=2025001-0001`).
   * **Simulasi Uji Webhook Payment Gateway (`curl`):** hasilkan payload & signature valid melalui `POST /api/finance/webhook/sign` (atau tombol *Simulasi Webhook* di `/dashboard/finance`), lalu kirim ke:
     ```bash
     curl -X POST http://127.0.0.1:8000/api/finance/webhook \
       -H "Content-Type: application/json" \
       -H "X-Webhook-Signature: <HMAC_SHA256_SIGNATURE>" \
       -d '{"transaction_id":"GW-TEST-001","amount":"5000000.00","status":"paid","payment_method":"VA_BCA","billing_id":1}'
     ```

## Lisensi

Tidak ada lisensi tertentu.
