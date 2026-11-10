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

```
repo-structure/
├── diagrams/
│   ├── class-diagram.mmd        # Diagram kelas UML (Mermaid)
│   ├── usecase-diagram.puml     # Diagram use case UML (PlantUML)
│   ├── sequence-krs.mmd         # Diagram sekuens KRS (Mermaid)
│   └── sequence-pmb.mmd         # Diagram sekuens PMB (Mermaid)
├── docs/
│   ├── ADR-architecture-decisions.md # Keputusan Arsitektur Sistem (ADR-001)
│   ├── ADR-architecture-decisions.pdf
│   └── Final-UML-diagram.pdf
└── prompts/
    └── ai-usage-log.md          # Catatan penggunaan AI selama perancangan

backend/
├── alembic/                     # Migrasi database Alembic
├── app/
│   ├── core/                    # Konfigurasi & Koneksi Database
│   ├── models/                  # Model SQLAlchemy ORM
│   ├── schemas/                 # Skema Validasi Pydantic
│   └── main.py                  # Entry Point FastAPI & Endpoints
├── init_db.py                   # Skrip Inisialisasi & Seeding Database
├── test_pmb.py                  # Unit Testing (Pytest)
├── requirements.txt             # Daftar Dependensi Python
└── AI_USAGE_LOG.md
```

## Teknologi & Tools

- **Bahasa Pemrograman:** Python
- **Backend Framework:** FastAPI, Uvicorn
- **ORM & Database:** SQLAlchemy, SQLite
- **Validasi & Pengujian:** Pydantic, Pytest
- **Diagrams:** Mermaid (.mmd) untuk Class Diagram & Sequence Diagram, PlantUML (.puml) untuk Use Case Diagram
- **Dokumentasi & Arsitektur:** Markdown, PDF, Architecture Decision Records (ADR)

## Cara Menjalankan & Melihat

1. **Diagram UML:** Dapat dilihat menggunakan renderer Mermaid (.mmd) dan PlantUML (.puml) di VS Code (PlantUML/Mermaid Preview) atau GitHub.
2. **Instalasi Dependensi Backend:**
   `ash
   pip install -r backend/requirements.txt
   `
3. **Inisialisasi Database:**
   `ash
   python backend/init_db.py
   `
4. **Menjalankan Unit Test:**
   `ash
   pytest backend/test_pmb.py -v
   `
5. **Menjalankan Server Backend:**
   `ash
   uvicorn backend.app.main:app --reload
   `
   * Akses dokumentasi API interaktif (Swagger UI) di: http://127.0.0.1:8000/docs

## Lisensi

Tidak ada lisensi tertentu.
