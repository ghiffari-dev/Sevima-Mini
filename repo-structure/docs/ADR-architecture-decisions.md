# ADR-001: Keputusan Arsitektur Sistem Akademik SEVIMA-Mini

## 1. Status
Disetujui

## 2. Konteks
Sistem informasi akademik mini (SEVIMA-Mini) membutuhkan desain kelas UML yang mencakup manajemen pengguna, katalog mata kuliah, penawaran kelas per semester, KRS, jadwal, nilai, dan pembayaran. Desain dikembangkan secara iteratif melalui analisis arsitektur berorientasi objek (OOP) dan prinsip SOLID.

## 3. Keputusan

### 3.1 Hierarki Pengguna (Inheritance & Polymorphism)
User dirancang sebagai abstract base class dengan subclass konkret: Mahasiswa, Dosen, Admin, dan CalonMahasiswa.
- Polimorfisme: Method getInfo() didefinisikan sebagai method abstrak di User dan di-override di setiap subclass.
- Visibilitas: Atribut dasar menggunakan visibilitas # (protected) untuk kelas abstrak, dan - (private) untuk atribut spesifik subclass.
- CalonMahasiswa: Bertindak sebagai calon pengguna yang dapat bertransformasi menjadi Mahasiswa setelah proses PMB selesai.

### 3.2 Katalog vs Penawaran Kelas (Course & Kelas)
- Course bertindak sebagai katalog mata kuliah murni (kode, nama, SKS, prasyarat).
- Kelas bertindak sebagai instansiasi penawaran mata kuliah di semester tertentu (idKelas, namaKelas, semester, kapasitas). Course berelasi agresi ke Kelas (Course "1" o-- "*" Kelas).

### 3.3 Relasi Pendaftaran & Pembayaran (PendaftaranPMB & PendaftaranKRS)
- Pendaftaran dipecah menjadi PendaftaranPMB (untuk calon mahasiswa) dan PendaftaranKRS (untuk mahasiswa aktif mengisi KRS), mewarisi kelas abstrak Pendaftaran.
- Kardinalitas PendaftaranKRS ke Enrollment diatur 1 ke 1..* (satu pengisian KRS menghasilkan banyak mata kuliah yang diambil), tanpa atribut idEnrollment yang redundan.
- Pembayaran dipecah menjadi PembayaranPMB dan PembayaranKRS mewarisi kelas abstrak Payment. Atribut yang redundan dihilangkan dengan memanfaatkan superclass.

### 3.4 Relasi Course (Prasyarat)
- Prasyarat mata kuliah menggunakan asosiasi dua arah simetris: Course "*" -- "*" Course : prasyarat.

### 3.5 Relasi Kelas & Jadwal (Schedule)
- Kelas berelasi komposit (*--) ke Schedule karena jadwal perkuliahan terikat mutlak dan tidak berdiri sendiri terlepas dari kelas penawarannya.



### 3.7 Alur Interaksi & Proses Bisnis (Sequence Diagrams: PMB & KRS)
- **Pemisahan Verifikasi Pembayaran & Seleksi PMB**: Proses pembayaran biaya pendaftaran (`PembayaranPMB`) dan verifikasi hasil seleksi akademis dipisahkan secara tegas. Status "Diterima" dan pengaktifan akun mahasiswa tidak otomatis terjadi hanya karena pembayaran berhasil, melainkan memerlukan peninjauan dan verifikasi oleh `Admin`.
- **Validasi Komprehensif & Deferred Enrollment pada KRS**: Pengisian KRS (`PendaftaranKRS`) melalui tahap validasi ketat (prasyarat mata kuliah, batas SKS, bentrok jadwal, dan kapasitas kelas) serta penyimpanan pilihan sementara. Pembuatan objek `Enrollment` ditunda (*deferred creation*) dan baru dieksekusi secara resmi **setelah** pembayaran KRS divalidasi lunas oleh `PembayaranKRS`, guna mencegah inkonsistensi data pendaftaran kelas.

## 4. Trade-off yang Dipertimbangkan


### 3.6 Perancangan Use Case & Batasan Sistem (System Boundary)
- Aktor Utama: Sistem membedakan secara tegas antara CalonMahasiswa, Mahasiswa, Dosen, dan Admin untuk menjaga prinsip pemisahan wewenang (*separation of concerns*).
- Subsistem Akademik: Use case dikelompokkan ke dalam fungsionalitas inti (Autentikasi, PMB, KRS, Perkuliahan/Nilai, dan Manajemen Admin) yang langsung merefleksikan relasi objek pada Class Diagram.