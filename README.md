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
- **Global Exception Handler & Validasi Pydantic:** Penanganan error terpusat melalui `@app.exception_handler(KRSError)` (`400`, `403`, `409`, `422`) dan `@app.exception_handler(ScheduleError)` (`400`, `404`, `409`) beserta skema Pydantic request/response yang tervalidasi.
- **Challenge Opsional (+10%) — CSP Backtracking Recommender:** Penyusunan rekomendasi jadwal KRS bebas bentrok (`/api/krs/{nim}/recommend`) dengan prioritas MK wajib > pilihan yang hasil akhirnya wajib lolos `default_validators()`.
- **Modul Jadwal & Ruangan (Minggu 7–8):**
  - **Scheduling Service & Interval Tree:** CRUD jadwal & master ruangan (`Ruangan` + `JadwalKuliah` + migrasi Alembic `a1b2c3sch007`), validasi kapasitas ruangan (`enrolled <= kapasitas`), serta algoritma `detect_schedule_conflict()` berbasis *Interval Tree* untuk mendeteksi `room_conflict`, `lecturer_conflict`, dan `time_overlap`.
  - **Observer Pattern (`ScheduleSubject` & `NotificationManager`):** Penyiaran otomatis event perubahan jadwal (`SCHEDULE_CREATED`, `SCHEDULE_CHANGED`, `SCHEDULE_DELETED`, `CONFLICT_DETECTED`) ke `StudentObserver`, `LecturerObserver`, dan `AdminObserver` dengan simulasi medium **Email / SMS / Push** via log.
  - **Conflict Resolver UI & Hybrid AI Rescheduler:** Dashboard web admin di `/dashboard/conflicts` untuk memantau bentrok, meminta 3 rekomendasi jadwal alternatif (`[{hari, jam, ruangan, reason}]`) via LLM API (jika key tersedia di `.env`) atau *rule-based fallback* dengan *guardrail* bebas bentrok, dan menerapkannya dalam satu klik.
  - **Integrasi KRS (`REVISION`):** Perubahan/penghapusan jadwal otomatis memindahkan KRS terdampak (`SUBMITTED`/`APPROVED`) kembali ke status `REVISION` (`KRS.invalidate_by_schedule_change()`) lengkap dengan `KRSLog` dan `Notifikasi` dalam satu transaksi ACID.
- **Database & Migrasi:** SQLite dengan SQLAlchemy 2.0 ORM (`Mapped` & `mapped_column`), Alembic migrations, dan skrip inisialisasi database.
- **Automated Testing (95 Passed):** Piramida pengujian lengkap menggunakan `pytest` dan `hypothesis` mencakup unit test validator & state machine, integrasi `KRSManager` + DB, *Property-Based Testing* (**2×1000 contoh acak** untuk batas SKS $\le$ 24 & bebas bentrok, **28 kombinasi transisi ilegal**, **200 contoh CSP**, **250 contoh** ekuivalensi *Interval Tree* vs *brute-force*), pengujian *Observer Pattern*, *Hybrid AI Rescheduler*, invalidasi KRS, serta API integration test via `TestClient` untuk PMB, KRS, & Schedule.

## Ringkasan Endpoint API & Alur State Machine KRS

### Daftar Endpoint Utama

| Modul | Method & Endpoint | Body Utama | Status HTTP | Keterangan |
| :--- | :--- | :--- | :--- | :--- |
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
| **Schedule** | `GET / POST /api/schedules/rooms` | Data ruangan (`kode_ruangan`, `kapasitas`) | `200`, `201`, `409` | Daftar & tambah master ruangan |
| **Schedule** | `GET / POST /api/schedules` | Data jadwal (`kode_mk`, `ruangan_kode`, `dosen`, `hari`, `jam_mulai`, `jam_selesai`) | `200`, `201`, `400`, `409` | Daftar & buat jadwal (cek kapasitas & bentrok 3D) |
| **Schedule** | `PUT / DELETE /api/schedules/{id}` | Perubahan jadwal (`hari`, `jam_mulai`, `jam_selesai`, `ruangan_kode`) | `200`, `400`, `404`, `409` | Ubah/hapus jadwal, invalidasi KRS -> `REVISION`, & notify Observer |
| **Schedule** | `GET /api/schedules/conflicts` | — | `200` | Deteksi semua bentrok aktif via *Interval Tree* |
| **Schedule** | `POST /api/schedules/detect` | `schedules[]` | `200` | Deteksi bentrok 3D stateless |
| **Schedule** | `POST /api/schedules/{id}/suggest-alternatives` | — | `200`, `404` | 3 saran jadwal alternatif (Hybrid AI + guardrail) |
| **Schedule** | `GET /api/schedules/notifications` | — | `200` | Log simulasi notifikasi Observer (Email/SMS/Push) |
| **UI** | `GET /dashboard/conflicts` | — | `200` | Halaman **Conflict Resolver UI** untuk Admin Akademik |

### Alur Transisi Sah State Machine KRS

1. `DRAFT -> SUBMITTED` — dilakukan oleh **Mahasiswa** pemilik KRS (minimal 1 MK & lolos seluruh validator).
2. `SUBMITTED -> APPROVED` — dilakukan oleh **Dosen PA** mahasiswa tersebut (`krs.dosen_pa_id`).
3. `SUBMITTED -> REVISION` — dilakukan oleh **Dosen PA** mahasiswa tersebut dengan `catatan_revisi` wajib diisi.
4. `REVISION -> SUBMITTED` — dilakukan oleh **Mahasiswa** setelah memperbaiki isi KRS.

> **Catatan keamanan model:** Penulisan langsung `krs.status = ...` di luar `KRS.transition()` diblokir otomatis oleh `@validates("status")` (`TransitionError` / HTTP `409`).

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
│   └── ADR-architecture-decisions.md  # Keputusan Arsitektur Sistem (ADR-001)
└── prompts/
    └── ai-usage-log.md          # Catatan penggunaan AI selama perancangan UML & arsitektur (Log 01–15)

backend/
├── alembic/                     # Migrasi database Alembic
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       ├── 3f3403fad0b5_tabel_pmb.py
│       ├── 8b2104krs005_tabel_krs.py
│       ├── 9c3205krs006_krs_state_columns.py
│       └── a1b2c3sch007_tabel_jadwal_ruangan.py
├── alembic.ini                  # Konfigurasi Alembic
├── app/
│   ├── core/                    # Konfigurasi, Koneksi DB, & Keamanan JWT
│   ├── models/                  # Model SQLAlchemy 2.0 ORM (PMB, KRS, Schedule/Ruangan, User, dll.)
│   ├── repositories/            # Repository Pattern (IPMBRepository & SQLite)
│   ├── routers/                 # Endpoint FastAPI (pmb.py, krs.py, & schedule.py)
│   ├── schemas/                 # Skema Validasi Pydantic
│   ├── services/                # Business Logic (PMB, KRS, IntervalTree, ConflictDetector, Observer, AI Rescheduler)
│   ├── static/                  # Conflict Resolver Admin UI (conflict_resolver.html)
│   └── main.py                  # Entry Point FastAPI, Exception Handler, & Dashboard UI
├── tests/
│   ├── test_krs_api.py          # API Integration Testing KRS (TestClient)
│   ├── test_krs_property.py     # Property-Based Testing (Hypothesis) & 28 Transisi Ilegal
│   └── test_schedule.py         # Unit, Property, Observer, AI Rescheduler, KRS Invalidation, & API/UI Tests (Minggu 7–8)
├── init_db.py                   # Skrip Inisialisasi & Seeding Database
├── test_models_and_schemas.py   # Unit & Integration Test Model, Validator, & State Machine KRS
├── test_pmb.py                  # API Integration Testing PMB (Pytest)
├── requirements.txt             # Daftar Dependensi Python
└── ai-usage-log.md              # Catatan penggunaan AI pengembangan backend & refleksi OPAR (Minggu 6–8)
```

## Teknologi & Tools

- **Bahasa Pemrograman:** Python
- **Backend Framework:** FastAPI, Uvicorn
- **ORM, Migrasi, & Database:** SQLAlchemy 2.0, Alembic, SQLite
- **Validasi & Pengujian:** Pydantic, Pytest, Hypothesis
- **Diagrams:** Mermaid (.mmd) untuk Class Diagram & Sequence Diagram, PlantUML (.puml) untuk Use Case Diagram
- **Dokumentasi & Arsitektur:** Markdown, Architecture Decision Records (ADR), OPAR

## Cara Menjalankan & Melihat

1. **Diagram UML:** Dapat dilihat menggunakan renderer Mermaid (.mmd) dan PlantUML (.puml) di VS Code (PlantUML/Mermaid Preview) atau GitHub.
2. **Instalasi Dependensi Backend:**
   ```bash
   pip install -r backend/requirements.txt
   ```
3. **Inisialisasi Database & Migrasi Alembic:**
   ```bash
   python backend/init_db.py
   cd backend && alembic upgrade head
   ```
4. **Menjalankan Seluruh Test Suite (Lintas OS — Windows PowerShell & Linux/macOS):**
   ```bash
   pytest -o pythonpath=backend backend/test_models_and_schemas.py backend/test_pmb.py backend/tests/test_krs_property.py backend/tests/test_krs_api.py backend/tests/test_schedule.py -v
   ```
5. **Menjalankan Server Backend (dari folder `backend/` agar terhubung ke `backend/pmb.db` hasil migrasi Alembic):**
   ```bash
   cd backend && uvicorn app.main:app --reload
   ```
   * Akses dokumentasi API interaktif (Swagger UI) di: http://127.0.0.1:8000/docs
   * Akses **Conflict Resolver Admin UI** di: http://127.0.0.1:8000/dashboard/conflicts

## Lisensi

Tidak ada lisensi tertentu.
