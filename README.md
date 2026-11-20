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
  - **Penjaga Input Nilai 2 Lapis (`GradeService` & `PresensiPort` DIP Stub):** Validasi endpoint idempoten `PUT /api/kelas/{kelas_id}/nilai/{nim}` via `NilaiIn` (`^[A-E]$` $\rightarrow$ `422`), autentikasi JWT `get_current_dosen`, penjaga pertama `is_pengampu(kelas_id, dosen_id)` via tabel `jadwal` (`403 Forbidden`), penguncian baris `KRSDetail` dengan `with_for_update()` (`404`), dan penjaga kedua presensi $\ge 75\%$ melalui protokol `PresensiPort` (`StubPresensiPort` sementara hingga Modul Presensi Minggu 12, `< 75%` $\rightarrow$ `422`).
  - **Audit Trail `grade_history` (Append-Only) & SQL View `riwayat_nilai`:** Perubahan nilai (termasuk input pertama dengan `nilai_lama = NULL`) beserta stempel waktu UTC dan `alasan` wajib (saat ubah nilai) ditulis dalam **satu transaksi atomik** bersama update `krs_detail.nilai`, lalu disajikan lewat SQL View `riwayat_nilai` (`GET /api/mahasiswa/{nim}/riwayat-nilai`).
  - **Kalkulator IPS & IPK Presisi `Decimal` (*Functional Core, Imperative Shell*):** Fungsi murni `rata`, `hitung_ips`, dan `hitung_ipk` memakai `Decimal` dengan pembulatan `ROUND_HALF_UP` (`0.01`) sekali di akhir (`3.125 -> 3.13`, total SKS nol $\rightarrow$ `0.00`, mata kuliah ulang memilih bobot terbaik per `kode_mk` sebelum menyaring `lulus`), didukung `NilaiRepo` & `GPACalculator` (*compute-on-read* dengan respons string 2 desimal) serta pembanding SQL CTE `calculate_ipk_sql` (`ROW_NUMBER()` + `NULLIF`), dan form web dosen `/dashboard/grades`.
- **Database & Migrasi:** SQLite dengan SQLAlchemy 2.0 ORM (`Mapped` & `mapped_column`), Alembic migrations (`d4e5f6grd010 (head)`), dan skrip inisialisasi database.
- **Automated Testing (149 Passed):** Piramida pengujian lengkap menggunakan `pytest` dan `hypothesis` mencakup unit test validator & state machine (`40`), *Property-Based Testing* KRS (`48`: **2×1000 contoh acak** SKS & bentrok, **42 transisi ilegal** dari 48 kombinasi, **200 contoh CSP**), integrasi PMB (`8`), API KRS (`6`), Modul Jadwal (`24`: 7 kasus bug AI, 2×300 properti & differential test `Sort & Sweep` vs `Naive`, 4 tes Minggu 8, RBAC, & `.ics`), serta Modul Nilai Minggu 9 (`23` di `test_grade.py`: **11 kasus IPK** berparameter, **3 kasus IPS**, **1 tes tukar skala `D` lulus**, **3×300 properti `Hypothesis`** IPK $\in [0,4]$ / tambah `A` monotonik / invarian permutasi, differential test SQL CTE, `GradeService` atomik/403/404/422/FK/view, dan API + UI `/dashboard/grades`).

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
| **UI** | `GET /dashboard/conflicts` | — | `200` | Halaman **Conflict Resolver UI** (dengan bilah login Admin JWT) |
| **UI** | `GET /dashboard/grades` | — | `200` | Halaman **Form Input Nilai Dosen & Audit Trail** (dengan bilah login Dosen JWT) |

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
│   └── stakeholder-questions-minggu-9.md  # Klarifikasi kontradiksi spesifikasi >= D (2.0) ke stakeholder
└── prompts/
    └── ai-usage-log.md          # Catatan penggunaan AI selama perancangan UML & arsitektur (Log 01–16)

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
│       └── d4e5f6grd010_skala_nilai_grade_history.py
├── alembic.ini                  # Konfigurasi Alembic
├── app/
│   ├── core/                    # Konfigurasi (DB, Security JWT Admin & get_current_dosen, env AI)
│   ├── models/                  # Model SQLAlchemy 2.0 ORM
│   │   ├── grade.py             # SkalaNilai, GradeHistory, RIWAYAT_NILAI_VIEW_SQL, GradeError, & Grade legacy
│   │   ├── schedule.py          # Model Ruangan, Dosen, Kelas, Jadwal (sequence), Outbox, & ScheduleError (Minggu 7–8)
│   │   └── ...                  # Model PMB, KRS (KRSDetail FK skala_nilai), User, Course, Enrollment, Payment
│   ├── repositories/            # Repository Pattern (IPMBRepository & SQLite)
│   ├── routers/                 # Endpoint FastAPI
│   │   ├── auth.py              # Endpoint Login JWT Admin & Dosen (/api/auth/login)
│   │   ├── grade.py             # Endpoint Input Nilai, IPS/IPK, Riwayat, & Seed Demo (/api/kelas/*/nilai/*, /api/mahasiswa/*)
│   │   ├── pmb.py               # Endpoint PMB (/api/pmb)
│   │   ├── krs.py               # Endpoint KRS & CSP Recommender (/api/krs)
│   │   └── schedule.py          # Endpoint Jadwal, Outbox, Conflict, AI, .ics, & Logs (/api/schedules)
│   ├── schemas/                 # Skema Validasi Pydantic (termasuk schedule.py & grade.py NilaiIn/NilaiOut)
│   ├── services/                # Business Logic Layer
│   │   ├── calendar_exporter.py # Ekspor iCalendar RFC 5545 (.ics) dengan CRLF, UID, RRULE UTC, & SEQUENCE
│   │   ├── conflict_detector.py # Detektor bentrok Naive & Grouping + Sort & Sweep + cek_kapasitas
│   │   ├── gpa_calculator.py    # Pure core Decimal (rata, hitung_ips, hitung_ipk), NilaiRepo, GPACalculator, & SQL CTE
│   │   ├── grade_service.py     # PresensiPort + StubPresensiPort & GradeService (403, FOR UPDATE, audit trail 1 transaksi)
│   │   ├── schedule_observer.py # Observer Protocol, LogChannel (idempotency key), & OutboxDispatcher
│   │   ├── schedule_recommender.py # LLMClient + 4 Saringan Pydantic/Kapasitas/Bentrok + Rule-Based Fallback
│   │   ├── scheduling_service.py   # Layanan Penjadwalan (locking pesimis, SQL conflict, Outbox & KRS ACID)
│   │   └── ...                  # pmb_service, krs_manager, krs_validator, krs_recommender
│   ├── static/                  # Dashboard & Form Web UI
│   │   ├── conflict_resolver.html
│   │   └── grade_input.html     # Form web input nilai dosen pengampu & audit trail (/dashboard/grades)
│   └── main.py                  # Entry Point FastAPI, Exception Handler, & Dashboard UI
├── tests/
│   ├── test_grade.py            # Unit (11 IPK + 3 IPS + tukar skala), 3 Properti Hypothesis, Integration, & API/UI (Minggu 9)
│   ├── test_krs_api.py          # API Integration Testing KRS (TestClient)
│   ├── test_krs_property.py     # Property-Based Testing (Hypothesis) & 42 Transisi Ilegal (48 Kombinasi)
│   └── test_schedule.py         # Unit, Property, 4 Tes Minggu 8, RBAC, Ekspor .ics, & API/UI Tests
├── init_db.py                   # Skrip Inisialisasi & Seeding Database
├── test_models_and_schemas.py   # Unit & Integration Test Model, Validator, & State Machine KRS
├── test_pmb.py                  # API Integration Testing PMB (Pytest)
├── requirements.txt             # Daftar Dependensi Python
└── ai-usage-log.md              # Catatan penggunaan AI pengembangan backend & refleksi OPAR (Minggu 6–9)
```

## Teknologi & Tools

- **Bahasa Pemrograman:** Python
- **Backend Framework:** FastAPI, Uvicorn
- **ORM, Migrasi, & Database:** SQLAlchemy 2.0, Alembic, SQLite
- **Validasi, HTTP Client, & Pengujian:** Pydantic, `httpx` (integrasi opsional LLM API), Pytest, Hypothesis
- **Frontend Admin UI:** HTML5, CSS3, Vanilla JavaScript (`/dashboard/conflicts`)
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
   pytest -o pythonpath=backend backend/test_models_and_schemas.py backend/test_pmb.py backend/tests/test_krs_property.py backend/tests/test_krs_api.py backend/tests/test_schedule.py backend/tests/test_grade.py -v
   ```
6. **Menjalankan Server Backend (dari folder `backend/` agar terhubung ke `backend/pmb.db` hasil migrasi Alembic):**
   ```bash
   cd backend && uvicorn app.main:app --reload
   ```
   * Akses dokumentasi API interaktif (Swagger UI) di: http://127.0.0.1:8000/docs
   * Akses **Conflict Resolver Admin UI** di: http://127.0.0.1:8000/dashboard/conflicts (klik **Login Admin** dengan akun demo `admin.akademik@sevima.ac.id` / `admin123`, lalu klik **Muat Data Demo Bentrok**).
   * Akses **Form Input Nilai Dosen & Audit Trail** di: http://127.0.0.1:8000/dashboard/grades (klik **Muat Data Demo (Rina 90% & Budi 70%)**, lalu klik **Login Dosen Pengampu** dengan akun demo `dosen.pengampu@sevima.ac.id` / `dosen123`).
   * Unduh jadwal kuliah dalam format **iCalendar (.ics)** di: http://127.0.0.1:8000/api/schedules/export.ics (opsional `?semester=20251&nim=2025001-0001`).

## Lisensi

Tidak ada lisensi tertentu.
