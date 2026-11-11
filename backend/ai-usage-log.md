# AI USAGE LOG

## Log 01 — Desain Skema Database PMB dan Migrasi SQLAlchemy 2.0

### Tujuan
Merancang dan mengimplementasikan skema database Penerimaan Mahasiswa Baru (PMB) untuk sistem akademik menggunakan SQLAlchemy 2.0 (Mapped & mapped_column), Alembic migration (upgrade() dan downgrade()), lengkap dengan tabel relasional (calon_mahasiswa, program_studi, jalur_masuk), kolom 
im (nullable + unique), serta penjelasan penegakan *constraint* (di level Database vs Aplikasi).

### Perintah (Prompt)
Desain skema database PMB untuk sistem akademik:
Tabel calon_mahasiswa: id, nama_lengkap, email (unique), phone, tanggal_lahir, alamat, program_studi_id, jalur_masuk (SNBP/SNBT/Mandiri), status (pending/approved/rejected), created_at, approved_at.
Tabel program_studi: id, kode (3 char), nama, fakultas.
Buat SQLAlchemy model + Alembic migration script.
Tambahkan constraint phone format Indonesia dan email validation.

Lima tambahan dari saya:
1. Tabel jalur_masuk (id, nama unik) + FK jalur_masuk_id
2. Gunakan SQLAlchemy 2.0: Mapped & mapped_column
3. Migrasi dengan upgrade() dan downgrade()
4. Kolom nim nullable + unique (persiapan Minggu 4)
5. Jelaskan tiap constraint ditegakkan di DB atau aplikasi

### Hasil (Hasil Implementasi)
- Pembuatan model SQLAlchemy 2.0 untuk ProgramStudi, JalurMasuk, dan CalonMahasiswa menggunakan syntax Mapped dan mapped_column.
- Pembuatan skrip migrasi Alembic dengan fungsi upgrade() dan downgrade() secara lengkap.
- Penambahan kolom 
im yang bersifat nullable dan unique pada tabel calon_mahasiswa.
- Validasi email dan format nomor telepon Indonesia (^(\+62|62|0)[0-9]{9,12}$).
- Dokumentasi dan pemetaan penegakan constraint (Database level seperti UNIQUE, FOREIGN KEY, NOT NULL, vs Aplikasi level seperti format validasi regex phone & email).

### Evaluasi (Objektif)
- **Kelebihan**: Struktur database menjadi sangat modular, normalisasi data terjaga dengan adanya tabel terpisah untuk jalur_masuk dan program_studi, penerapan standar modern SQLAlchemy 2.0, serta migrasi yang aman dengan rollback (downgrade).
- **Kekurangan / Kompleksitas Tambahan**: Penggunaan migrasi Alembic dan validasi multi-layer (DB + Pydantic/Aplikasi) memerlukan kedisiplinan dalam sinkronisasi skema model dan migrasi fisik database.


## Log 02 — Perluasan Skema Database, Model SQLAlchemy 2.0, Pydantic Schemas, dan Core Security untuk SEVIMA-Mini (PMB & KRS)

### Tujuan
Melengkapi arsitektur backend SEVIMA-Mini secara komprehensif berdasarkan diagram perancangan (*Class Diagram*, *Use Case Diagram*, & *Sequence Diagrams*) dengan mengimplementasikan modul Autentikasi/Security, Hierarki User (Mahasiswa, Dosen, Admin), Katalog Akademik & Prasyarat Mata Kuliah, Pendaftaran KRS & Enrollment, Penilaian (*Grade*), serta Pembayaran PMB & KRS.

### Perintah (Prompt)
Analisis folder diagram (class-diagram, sequence-krs, sequence-pmb, usecase-diagram) dan lengkapi folder backend/app/schemas, models, dan core untuk seluruh sistem SEVIMA-Mini secara utuh (Auth, User hierarchy, Course, Kelas, Schedule, PendaftaranKRS, Enrollment, Grade, Payment).

### Hasil (Hasil Implementasi)
- Pembuatan ackend/app/core/security.py untuk *password hashing* (crypt) dan pembuatan token JWT (create_access_token).
- Pembuatan model SQLAlchemy 2.0 untuk hierarki User (User, Mahasiswa, Dosen, Admin) menggunakan *polymorphic inheritance*.
- Pembuatan model akademik (Course, Kelas, Schedule) serta relasi *self-referential many-to-many* untuk prasyarat mata kuliah (course_prerequisites).
- Pembuatan model pendaftaran & pembayaran polimorfik (Pendaftaran, PendaftaranPMB, PendaftaranKRS, Payment, PembayaranPMB, PembayaranKRS).
- Pembuatan model Enrollment dan Grade untuk pengelolaan perkuliahan dan pencatatan nilai mahasiswa.
- Pembuatan dan pelengkapan seluruh skema Pydantic di ackend/app/schemas/ (uth.py, user.py, course.py, krs.py, grade.py, payment.py).
- Penambahan dan eksekusi unit test komprehensif dengan hasil **12 passed**.

### Evaluasi (Objektif)
- **Kelebihan**: Backend sistem *SEVIMA-Mini* kini memiliki fondasi data dan skema yang lengkap, modular, dan taat asas pada prinsip OOP serta diagram perancangan sistem akademik. Seluruh komponen teruji dengan test suite.
- **Kekurangan / Kompleksitas Tambahan**: Kompleksitas relasi antar tabel (polymorphic mapping & self-referential) menuntut pemahaman mendalam tentang ORM relationship configuration di SQLAlchemy 2.0.


## Log 03 — Refaktorisasi Arsitektur Backend Berbasis Prinsip SOLID (Repository Pattern & Dependency Injection)

### Tujuan
Menerapkan prinsip SOLID secara ketat pada modul PMB (Penerimaan Mahasiswa Baru) melalui pemisahan lapisan data access menggunakan *Repository Pattern* (`IPMBRepository` & `SQLitePMBRepository`), pemisahan *Business Logic* di *Service*, serta penerapan *Dependency Injection* pada *FastAPI Routers*.

### Perintah (Prompt)
Refaktorisasi kode backend SEVIMA-Mini agar sepenuhnya menerapkan prinsip SOLID (Single Responsibility, Open/Closed, Liskov Substitution, Interface Segregation, Dependency Inversion), khususnya pada modul *PMB* dengan memisahkan interaksi database ke dalam *Repository* dan menyuntikkannya ke *Service* serta *Router*. Jalankan test suite untuk memastikan semuanya berjalan baik.

### Hasil (Hasil Implementasi)
- Pembuatan interface abstrak `IPMBRepository` di `backend/app/repositories/pmb_repository.py`.
- Pembuatan implementasi konkret `SQLitePMBRepository` di `backend/app/repositories/sqlite_pmb_repository.py`.
- Pembaruan `PMBService` (`backend/app/services/pmb_service.py`) agar menerima *repository* melalui *constructor* (Dependency Injection) dan fokus murni pada logika bisnis.
- Pembaruan `backend/app/routers/pmb.py` untuk menginjeksikan *service* melalui FastAPI `Depends`.
- Menjalankan unit test dengan hasil **12 passed** (`pytest`).

### Evaluasi (Objektif)
- **Kelebihan**: Arsitektur menjadi jauh lebih bersih, modular, dan mematuhi prinsip *Dependency Inversion* serta *Single Responsibility*. Kode kini sangat mudah di-*mock* dan di-*unit test* secara terisolasi tanpa ketergantungan langsung ke implementasi SQLite mentah.
- **Kekurangan / Kompleksitas Tambahan**: Bertambahnya jumlah file (pemisahan folder `repositories/`) yang memerlukan manajemen impor yang cermat.


## Log 04 — Pengamanan Konfigurasi Secret Key (Environment Variable Support)

### Tujuan
Meningkatkan keamanan penanganan *secret key* JWT (`SECRET_KEY`) di `backend/app/core/security.py` agar tidak di-*hardcode* secara mutlak, melainkan mendukung *Environment Variable* (`os.getenv`) dengan nilai *fallback* yang aman untuk pengembangan lokal dan pengujian.

### Perintah (Prompt)
Periksa apakah ada kunci rahasia atau informasi sensitif yang terekspos ke publik di repository. Perbarui penanganan `SECRET_KEY` di `security.py` agar mendukung environment variable.

### Hasil (Hasil Implementasi)
- Memperbarui `backend/app/core/security.py` menggunakan `os.getenv("SECRET_KEY", "sevima-mini-secret-key-very-secure")`.
- Memastikan seluruh unit test tetap berjalan sukses dengan hasil **12 passed** (`pytest`).
- Konfirmasi bahwa file sensitif seperti `.env` dan database SQLite sudah masuk ke `.gitignore` sehingga aman dari eksposur publik di GitHub.

### Evaluasi (Objektif)
- **Kelebihan**: Aplikasi kini siap untuk di-deploy ke lingkungan *production* menggunakan *Environment Variable* tanpa modifikasi kode, sekaligus tetap mudah dijalankan di *local development* berkat *fallback value*.
- **Kekurangan / Kompleksitas Tambahan**: Tidak ada.



## Log 05 — Implementasi Endpoint PMB Lanjutan, Generasi NIM Aman Race Condition, dan Unit Testing Komprehensif

### Tujuan
Mengimplementasikan endpoint PUT untuk approval/rejection pendaftaran PMB dengan penanganan error lengkap (404, 400, 409), mekanisme `generate_nim` yang aman dari *race condition*, endpoint GET untuk status & statistik pendaftaran berbasis pengelompokan (*GROUP BY*), serta penyusunan unit test komprehensif dengan cakupan kode $\ge 80\%$ dan dokumentasi API di Swagger.

### Perintah (Prompt)
Lengkapi fitur PMB pada backend dengan ketentuan:
1. Endpoint PUT untuk approval dan rejection pendaftaran dengan penanganan HTTP status code 404, 400, dan 409 secara tepat.
2. Mekanisme `generate_nim` yang aman terhadap *race condition*.
3. Endpoint GET untuk mengambil status dan statistik pendaftaran menggunakan agregasi (*GROUP BY*).
4. Pembuatan minimal 5 unit test mencakup skenario approval tidak valid dengan target *code coverage* $\ge 80\%$.
5. Penyediaan dokumentasi Swagger / OpenAPI dan format penomoran NIM pada README.

### Hasil (Hasil Implementasi)
- Pembuatan endpoint PUT untuk proses *approve* dan *reject* pendaftaran PMB lengkap dengan penanganan kode error HTTP (404 Not Found, 400 Bad Request, 409 Conflict).
- Implementasi logika penomoran NIM otomatis yang aman dari *race condition* saat proses persetujuan calon mahasiswa.
- Penambahan endpoint GET statistik dan status pendaftaran menggunakan fungsi agregasi database (*GROUP BY*).
- Penambahan skrip unit test komprehensif pada `backend/test_pmb.py` mencakup pengujian validasi, approval, dan statistik dengan hasil seluruh test **passed**.
- Pemutakhiran dokumentasi API via Swagger/OpenAPI serta penjelasan format penomoran NIM.

### Evaluasi (Objektif)
- **Kelebihan**: Modul PMB kini memiliki fitur operasional yang lengkap, aman dari konkurensi data (*race condition*), serta memiliki cakupan pengujian unit test yang andal dan terdokumentasi dengan baik di Swagger.
- **Kekurangan / Kompleksitas Tambahan**: Penanganan konkurensi pada pembuatan NIM memerlukan penanganan *transaction locking* yang teliti pada level database/repository.

