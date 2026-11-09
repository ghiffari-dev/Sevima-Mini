# ADR-001: Keputusan Arsitektur Sistem Akademik SEVIMA-Mini

## 1. Status
Disetujui

## 2. Konteks
Sistem informasi akademik mini (SEVIMA-Mini) membutuhkan desain kelas UML yang mencakup manajemen pengguna, mata kuliah, KRS, jadwal, nilai, dan pembayaran. Diagram kelas awal dihasilkan oleh AI (Gemini 1.5 Flash) melalui prompt engineering, kemudian direvisi manual berdasarkan validasi aturan UML (video PBO Minggu 01: "Jangan percaya, periksa").

## 3. Keputusan

### 3.1 Hierarki Pengguna (Inheritance)
`User` dirancang sebagai **abstract base class** dengan subclass konkret: `Mahasiswa`, `Dosen`, `Admin`, dan `CalonMahasiswa`.
- **Alasan:** Semua tipe pengguna berbagi atribut identitas dasar (`id`, `nama`, `email`) dan perilaku autentikasi (`login`, `logout`).
- **Prinsip SOLID:** Open/Closed Principle (OCP) — tipe pengguna baru dapat ditambahkan tanpa mengubah `User`; Liskov Substitution Principle (LSP) — semua subclass dapat diperlakukan sebagai `User`.

### 3.2 Relasi Enrollment ↔ Grade
Digunakan **composition** (`*--`).
- **Alasan:** Grade adalah objek bagian yang tidak dapat berdiri sendiri tanpa Enrollment sebagai objek induk. Satu enrollment dapat memiliki nol atau satu grade.
- **Multiplicity:** `Enrollment "1" *-- "0..1" Grade` — satu enrollment mungkin belum memiliki nilai, satu nilai milik satu enrollment.

### 3.3 Relasi Course ↔ Schedule
Digunakan **aggregation** (`o--`).
- **Alasan:** Jadwal dapat eksis secara konsep terpisah dari course (mis. jadwal kosong belum diisi course), dan satu schedule tidak dimiliki secara eksklusif oleh satu course seumur hidup.
- **Multiplicity:** `Course "1" o-- "*" Schedule` — satu course memiliki banyak jadwal.

### 3.4 Relasi Course ↔ Course (Prasyarat)
Digunakan **self-referensi aggregation** dengan role name.
- **Alasan:** Sebuah course dapat memiliki banyak prasyarat, dan sebuah course dapat menjadi prasyarat bagi banyak course lain.
- **Role name:** `prasyaratUntuk` (course yang membutuhkan prasyarat) dan `prasyaratDari` (course yang menjadi prasyarat) untuk menghindari ambigu.
- **Multiplicity:** `Course "1" o-- "*" Course : prasyaratUntuk` dan `Course "*" o-- "1" Course : prasyaratDari`.

### 3.5 Class Payment
Ditambahkan sebagai class mandiri dengan atribut: `idPayment`, `jumlah`, `tanggalBayar`, `statusBayar`; dan method: `verifyPayment()`, `generateReceipt()`.
- **Relasi:** `Mahasiswa "1" --> "*" Payment`, `CalonMahasiswa "1" --> "*" Payment`, `Payment "1" --> "1" Enrollment`.
- **Alasan:** Pembayaran terkait KRS (mahasiswa) dan pendaftaran PMB (calon mahasiswa). Setiap pembayaran harus terkait minimal satu enrollment.

### 3.6 Visibility Modifier
Semua atribut diberi visibilitas `-` (private), semua method diberi `+` (public), dan atribut di `User` (abstract) diberi `#` (protected).
- **Alasan:** Enkapsulasi — atribut tidak boleh diakses langsung dari luar class; method merupakan antarmuka publik.

## 4. Trade-off yang Dipertimbangkan

| Keputusan | Trade-off | Alasan Dipilih |
|-----------|-----------|----------------|
| Association untuk Enrollment–Grade (bukan composition) | Grade tidak otomatis dihapus saat Enrollment dihapus | Nilai akademik bersifat permanen; menghindari kehilangan data historis |
| Aggregation untuk Course–Schedule (bukan composition) | Schedule tidak dihapus otomatis saat Course dihapus | Jadwal memiliki siklus hidup yang lebih fleksibel |
| Self-referensi Course untuk prasyarat | Memerlukan role name agar tidak ambigu | Menghindari class terpisah untuk tabel relasi prasyarat, tetap sederhana |
| Payment terpisah dari Enrollment | Perlu relasi tambahan ke Enrollment | Memisahkan concern pembayaran dari proses enrollment (SRP) |

## 5. Pattern yang Diterapkan
- **Inheritance / Polymorphism:** Hierarki `User` untuk berbagai jenis pengguna.
- **Aggregation:** Relasi lemah antara Course–Schedule dan Course–Course (prasyarat).
- **Association:** Relasi Enrollment–Grade, Mahasiswa–Enrollment, Course–Enrollment, Dosen–Course, Payment–Enrollment.

## 6. Dampak
- Diagram kelas sekarang mencakup 9 class dengan visibility lengkap dan multiplicity pada semua relasi.
- Tidak ada circular dependency yang terdeteksi.
- Semua relasi sudah diverifikasi terhadap konsep UML (inheritance, aggregation, association) tanpa composition yang tidak tepat.
- Semua 6 poin analisis revisi (Prompt Ke-3 / Log 03) telah diterapkan: Grade sebagai association, relasi Dosen–Course/Schedule, relasi CalonMahasiswa–Payment, kardinalitas Payment 1→1, role name self-referensi Course, dan visibility lengkap.
- Siap untuk dilanjutkan ke Use Case Diagram dan Sequence Diagram (tahap berikutnya).

---