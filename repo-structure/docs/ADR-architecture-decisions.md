# ADR-001: Keputusan Arsitektur Sistem Akademik SEVIMA-Mini

## 1. Status
Disetujui

## 2. Konteks
Sistem informasi akademik mini (SEVIMA-Mini) membutuhkan desain kelas UML dan implementasi backend RESTful API (FastAPI & SQLAlchemy) yang mencakup manajemen pengguna, katalog mata kuliah, penawaran kelas per semester, KRS, jadwal, nilai, serta pembayaran. Desain dikembangkan secara iteratif melalui analisis arsitektur berorientasi objek (OOP) dan prinsip SOLID.

## 3. Keputusan Arsitektur

### 3.1 Hierarki Pengguna (Inheritance & Polymorphism)
- `User` dirancang sebagai *abstract base class* dengan subclass konkret: `Mahasiswa`, `Dosen`, `Admin`, dan `CalonMahasiswa`.
- Polimorfisme: Method `getInfo()` didefinisikan sebagai method abstrak di `User` dan di-override di setiap subclass.
- CalonMahasiswa: Bertindak sebagai calon pengguna yang dapat bertransformasi menjadi `Mahasiswa` setelah proses PMB selesai.

### 3.2 Katalog vs Penawaran Kelas (Course & Kelas)
- `Course` bertindak sebagai katalog mata kuliah murni (kode, nama, SKS, prasyarat).
- `Kelas` bertindak sebagai instansiasi penawaran mata kuliah di semester tertentu (idKelas, namaKelas, semester, kapasitas). Course berelasi agresi ke Kelas (`Course "1" o-- "*" Kelas`).

### 3.3 Relasi Pendaftaran & Pembayaran (PendaftaranPMB & PendaftaranKRS)
- Pendaftaran dipecah menjadi `PendaftaranPMB` (untuk calon mahasiswa) dan `PendaftaranKRS` (untuk mahasiswa aktif mengisi KRS), mewarisi kelas abstrak `Pendaftaran`.
- Kardinalitas `PendaftaranKRS` ke `Enrollment` diatur 1 ke 1..* (satu pengisian KRS menghasilkan banyak mata kuliah yang diambil).
- Pembayaran dipecah menjadi `PembayaranPMB` dan `PembayaranKRS` mewarisi kelas abstrak `Payment`.

### 3.4 Relasi Course (Prasyarat)
- Prasyarat mata kuliah menggunakan asosiasi dua arah simetris: `Course "*" -- "*" Course : prasyarat`.

### 3.5 Relasi Kelas & Jadwal (Schedule)
- Kelas berelasi komposit (`*--`) ke `Schedule` karena jadwal perkuliahan terikat mutlak dan tidak berdiri sendiri terlepas dari kelas penawarannya.

### 3.6 Perancangan Use Case & Batasan Sistem (System Boundary)
- Aktor Utama: Sistem membedakan secara tegas antara `CalonMahasiswa`, `Mahasiswa`, `Dosen`, dan `Admin` untuk menjaga prinsip pemisahan wewenang (*separation of concerns*).
- Subsistem Akademik: Use case dikelompokkan ke dalam fungsionalitas inti (Autentikasi, PMB, KRS, Perkuliahan/Nilai, dan Manajemen Admin).

### 3.7 Alur Interaksi & Proses Bisnis (Sequence Diagrams: PMB & KRS)
- **Pemisahan Verifikasi Pembayaran & Seleksi PMB**: Proses pembayaran biaya pendaftaran (`PembayaranPMB`) dan verifikasi hasil seleksi akademis dipisahkan. Pengaktifan akun mahasiswa dan pembuatan NIM otomatis dilakukan oleh `Admin` setelah pembayaran diverifikasi lunas dan seleksi disetujui.
- **Validasi Komprehensif & Deferred Enrollment pada KRS**: Pengisian KRS (`PendaftaranKRS`) melalui tahap validasi ketat (prasyarat, SKS, bentrok jadwal, kapasitas kelas) serta penyimpanan pilihan sementara. Objek `Enrollment` dibuat secara resmi (*deferred creation*) **setelah** pembayaran KRS divalidasi lunas oleh `PembayaranKRS`.

## 4. Trade-off yang Dipertimbangkan
1. **Inheritance & Polymorphism vs Flat Database Models**
   - *Kelebihan*: Menerapkan *Open/Closed Principle* dan *Liskov Substitution Principle* secara ketat pada domain OOP.
   - *Kekurangan*: Kompleksitas pemetaan ORM lebih tinggi dibandingkan tabel datar sederhana.
2. **Deferred Enrollment pada KRS**
   - *Kelebihan*: Mencegah inkonsistensi data, mahasiswa tidak bisa menempati kuota kelas sebelum pembayaran KRS divalidasi lunas.
   - *Kekurangan*: Membutuhkan pengelolaan state sementara (`PendaftaranKRS` vs `Enrollment`).
3. **Pemisahan Pembayaran & Verifikasi Admin pada PMB**
   - *Kelebihan*: Menjamin tata kelola akademik yang valid (pembayaran sukses tidak otomatis meluluskan calon mahasiswa tanpa review admin).
   - *Kekurangan*: Membutuhkan langkah manual tambahan oleh Admin sebelum akun mahasiswa dan NIM diaktifkan.
4. **SQLite & SQLAlchemy ORM**
   - *Kelebihan*: Ringan, mudah diinisialisasi untuk pengembangan lokal dan pengujian unit (`pytest`), serta menyediakan abstraksi database yang kuat.
   - *Kekurangan*: Kurang optimal untuk skalabilitas perusahaan skala besar dibandingkan database enterprise seperti PostgreSQL.
