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
- **RESTful Endpoints:** Endpoint pendaftaran calon mahasiswa, verifikasi/persetujuan kelulusan dengan pembuatan **NIM otomatis**.
- **Database & ORM:** SQLite dengan SQLAlchemy ORM dan skrip inisialisasi/seeding database.
- **Validasi Data:** Pydantic Schemas untuk request dan response yang aman dan tervalidasi.
- **Automated Testing:** Unit testing komprehensif menggunakan pytest (mencakup registrasi sukses, duplikasi email, validasi telepon, dan idempotensi persetujuan).

## Struktur Proyek

```text
.github/
└── PULL_REQUEST_TEMPLATE.md     # Template Pull Request (Fitur, Prompt, Risiko, OPAR)

repo-structure/
├── diagrams/
│   ├── class-diagram.mmd        # Diagram kelas UML (Mermaid)
│   ├── usecase-diagram.puml     # Diagram use case UML (PlantUML)
│   ├── sequence-krs.mmd         # Diagram sekuens KRS (Mermaid)
│   └── sequence-pmb.mmd         # Diagram sekuens PMB (Mermaid)
├── docs/
│   └── ADR-architecture-decisions.md  # Keputusan Arsitektur Sistem (ADR-001)
└── prompts/
    └── ai-usage-log.md          # Catatan penggunaan AI & refleksi OPAR

backend/
├── alembic/                     # Migrasi database Alembic
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       ├── 3f3403fad0b5_tabel_pmb.py
│       ├── 8b2104krs005_tabel_krs.py
│       └── 9c3205krs006_krs_state_columns.py
├── alembic.ini                  # Konfigurasi Alembic
├── app/
│   ├── core/                    # Konfigurasi, Koneksi DB, & Keamanan JWT
│   ├── models/                  # Model SQLAlchemy 2.0 ORM (PMB, KRS, User, dll.)
│   ├── repositories/            # Repository Pattern (IPMBRepository & SQLite)
│   ├── routers/                 # Endpoint FastAPI (pmb.py & krs.py)
│   ├── schemas/                 # Skema Validasi Pydantic
│   ├── services/                # Business Logic (pmb_service, krs_manager, krs_validator, krs_recommender)
│   └── main.py                  # Entry Point FastAPI & Global Exception Handler
├── tests/
│   ├── test_krs_api.py          # API Integration Testing KRS (TestClient)
│   └── test_krs_property.py     # Property-Based Testing (Hypothesis) & 28 Transisi Ilegal
├── init_db.py                   # Skrip Inisialisasi & Seeding Database
├── test_models_and_schemas.py   # Unit & Integration Test Model, Validator, & State Machine KRS
├── test_pmb.py                  # API Integration Testing PMB (Pytest)
├── requirements.txt             # Daftar Dependensi Python
└── ai-usage-log.md              # Catatan penggunaan AI pengembangan backend
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
3. **Inisialisasi Database:**
   ```bash
   python backend/init_db.py
   ```
4. **Menjalankan Seluruh Test Suite:**
   ```bash
   PYTHONPATH=backend pytest backend/test_models_and_schemas.py backend/test_pmb.py backend/tests/test_krs_property.py backend/tests/test_krs_api.py -v
   ```
5. **Menjalankan Server Backend:**
   ```bash
   uvicorn backend.app.main:app --reload
   ```
   * Akses dokumentasi API interaktif (Swagger UI) di: http://127.0.0.1:8000/docs

## Lisensi

Tidak ada lisensi tertentu.
