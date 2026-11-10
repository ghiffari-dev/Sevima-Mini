# AI USAGE LOG

## Log 01 — Desain Skema Database PMB dan Migrasi SQLAlchemy 2.0

### Tujuan
Merancang dan mengimplementasikan skema database Penerimaan Mahasiswa Baru (PMB) untuk sistem akademik menggunakan SQLAlchemy 2.0 (`Mapped` & `mapped_column`), Alembic migration (`upgrade()` dan `downgrade()`), lengkap dengan tabel relasional (`calon_mahasiswa`, `program_studi`, `jalur_masuk`), kolom `nim` (nullable + unique), serta penjelasan penegakan *constraint* (di level Database vs Aplikasi).

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
- Pembuatan model SQLAlchemy 2.0 untuk `ProgramStudi`, `JalurMasuk`, dan `CalonMahasiswa` menggunakan syntax `Mapped` dan `mapped_column`.
- Pembuatan skrip migrasi Alembic dengan fungsi `upgrade()` dan `downgrade()` secara lengkap.
- Penambahan kolom `nim` yang bersifat nullable dan unique pada tabel `calon_mahasiswa`.
- Validasi email dan format nomor telepon Indonesia (`^(\+62|62|0)[0-9]{9,12}$`).
- Dokumentasi dan pemetaan penegakan constraint (Database level seperti `UNIQUE`, `FOREIGN KEY`, `NOT NULL`, vs Aplikasi level seperti format validasi regex phone & email).

### Evaluasi (Objektif)
- **Kelebihan**: Struktur database menjadi sangat modular, normalisasi data terjaga dengan adanya tabel terpisah untuk `jalur_masuk` dan `program_studi`, penerapan standar modern SQLAlchemy 2.0, serta migrasi yang aman dengan rollback (`downgrade`).
- **Kekurangan / Kompleksitas Tambahan**: Penggunaan migrasi Alembic dan validasi multi-layer (DB + Pydantic/Aplikasi) memerlukan kedisiplinan dalam sinkronisasi skema model dan migrasi fisik database.

