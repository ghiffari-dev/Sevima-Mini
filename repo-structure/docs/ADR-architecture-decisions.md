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


### 3.8 Repository Pattern & Dependency Injection (Prinsip SOLID)
- **Repository Pattern**: Memisahkan lapisan akses data dari logika bisnis menggunakan interface abstrak (`IPMBRepository`) dan implementasi konkret (`SQLitePMBRepository`).
- **Dependency Injection**: Menginjeksikan *repository* ke dalam *service* dan *service* ke dalam *router* FastAPI melalui `Depends` untuk memastikan *loose coupling* dan kemudahan pengujian unit (*mocking*).

### 3.9 Keamanan Konkurensi (`generate_nim`) & Agregasi Statistik
- **Race Condition Safety**: Mekanisme `generate_nim` dirancang aman terhadap konkurensi (race condition) saat pembuatan Nomor Induk Mahasiswa secara otomatis pada proses approval.
- **Aggregated Analytics**: Penyediaan endpoint statistik pendaftaran berbasis pengelompokan (*GROUP BY*) untuk efisiensi kueri analitik dashboard admin.

### 3.10 Struktur Dua Tingkat KRS (`krs` + `krs_detail`) & Satu Pintu `KRSManager`
- **Representasi Dua Tingkat (Header–Detail)**: Pengambilan mata kuliah diwujudkan dalam dua tabel, yaitu `krs` sebagai satu kartu per mahasiswa per semester (`UniqueConstraint("nim", "semester")`) dan `krs_detail` sebagai baris mata kuliah di dalam kartu (`UniqueConstraint("krs_id", "kode_mk")`).
- **Status di Level Kartu**: Atribut `status` (`DRAFT`, `SUBMITTED`, `APPROVED`, `REVISION`) diletakkan pada tabel `krs` (bukan per baris `krs_detail`) untuk menjamin atomisitas persetujuan KRS sehingga tidak ada kondisi KRS yang "setengah disetujui".
- **Satu Pintu Perubahan (`KRSManager`)**: Seluruh operasi penambahan (`add_course`), penghapusan (`remove_course`), pengajuan (`submit_krs`), dan persetujuan (`approve_krs`) dikelola terpusat oleh `KRSManager` yang mengunci baris kartu (`FOR UPDATE`) dan hanya mengizinkan modifikasi mata kuliah saat kartu berstatus `DRAFT` atau `REVISION`.

### 3.11 Chain of Responsibility Pattern & Urutan Validasi KRS
- **Chain of Responsibility (`Validator`)**: Validasi penambahan mata kuliah pada KRS dipecah menjadi empat kelas validator independen yang saling merantai (`set_next`) dan langsung berhenti pada kegagalan pertama, guna mematuhi *Single Responsibility Principle* (SRP) dan *Open/Closed Principle* (OCP) — apabila terdapat aturan baru (misalnya validasi tunggakan SPP), cukup menambahkan class validator baru ke dalam rantai tanpa memodifikasi validator yang sudah ada.
- **Alasan Urutan `Duplicate -> SKS -> Prerequisite -> Conflict`**:
  1. `DuplicateValidator` diletakkan paling depan karena pemeriksaannya paling murah (cukup mengecek daftar mata kuliah di memori) dan memberikan pesan kesalahan paling tepat jika mahasiswa tidak sengaja memilih mata kuliah yang sama.
  2. `SKSValidator` dijalankan kedua karena hanya melakukan penjumlahan aritmatika SKS di memori ($\le 24$ SKS).
  3. `PrerequisiteValidator` dijalankan setelah lolos validasi dasar karena membutuhkan *query* ke database untuk memeriksa riwayat kelulusan mata kuliah prasyarat pada semester sebelumnya dengan perbandingan bobot numerik ($\ge \text{C}$ atau bobot $\ge 2.0$, bukan perbandingan string ASCII).
  4. `ConflictValidator` dijalankan terakhir untuk menguji irisan interval waktu ($\text{mulai}_A < \text{selesai}_B \land \text{mulai}_B < \text{selesai}_A$ pada hari yang sama) terhadap mata kuliah yang sudah valid di dalam kartu.

### 3.12 State Machine KRS: Tabel Transisi Sendiri (`dict[(state, aktor)]`) vs Library Eksternal
- **Pilihan Arsitektur**: Menggunakan **tabel transisi buatan sendiri** (`TRANSITIONS: dict[tuple[KRSStatus, Actor], set[KRSStatus]]`) beserta method satu pintu `KRS.transition()` dan `@validates("status")`, dibandingkan menggunakan library pihak ketiga seperti `python-statemachine` atau `transitions`.
- **Alasan Pemilihan**:
  1. **Tanpa Dependensi Tambahan**: Tidak menambah paket eksternal (`+0` paket) sehingga proyek tetap ringan dan bebas risiko ketidakcocokan versi ORM SQLAlchemy 2.0.
  2. **Proporsional untuk 4 State (`DRAFT`, `SUBMITTED`, `REVISION`, `APPROVED`)**: Untuk siklus hidup KRS yang terdiri dari 4 state dan 4 panah transisi berbasis peran (`Actor.MAHASISWA` dan `Actor.DOSEN_PA`), tabel `dict[(state, aktor)]` sudah sangat **cukup** dan ekspresif, sedangkan library state machine eksternal bersifat berlebihan (*overkill*).
  3. **Kemudahan Penjelasan Saat Viva / Evaluasi**: Seluruh mekanisme *guard* (pengecekan KRS kosong, validasi kepemilikan `dosen_pa_id`, kewajiban `catatan_revisi`, serta pemisahan HTTP `403 Forbidden` vs `409 Conflict`) tertulis secara eksplisit dan transparan tanpa tersembunyi di balik *magic/metaclass* internal library.

| Aspek Perbandingan | Tabel Sendiri (`dict[(state, aktor)]`) | Library (`python-statemachine` / `transitions`) |
| :--- | :--- | :--- |
| **Dependensi** | Tidak ada | +1 paket eksternal |
| **Skala 4 State KRS** | **Cukup** dan ringkas | Berlebihan (*over-engineering*) |
| **State Banyak + Callback Kompleks** | Mulai repot | **Layak** dipertimbangkan |
| **Dijelaskan Saat Viva** | **Mudah** dan transparan | Harus memahami internal library |

### 3.13 Unit Kerja Transaksi ACID & Strategi Penguncian Ganda (Pessimistic + Optimistic Lock) pada KRS
- **Periksa Semuanya Baru Pindah State (`submit_krs`)**: Pengajuan KRS menjalankan penguncian baris (`FOR UPDATE`), pengecekan transisi (`cek_transisi`), pengecekan KRS tidak kosong, dan validasi menyeluruh semua mata kuliah (`validate_krs`) **sebelum** memanggil `krs.transition(KRSStatus.SUBMITTED)`. Modifikasi mata kuliah (`add_course` / `remove_course`) saat status bukan `DRAFT`/`REVISION` ditolak dengan `KRSLockedError` (`409 Conflict`).
- **Satu Unit Kerja ACID (`approve_krs` & `revise_krs`)**: Persetujuan maupun permintaan revisi oleh Dosen PA mengeksekusi perubahan status KRS, pencatatan waktu (`approved_at`), penambahan baris audit `KRSLog`, dan penyimpanan baris `Notifikasi` di dalam satu blok transaksi `try ... db.commit() / except ... db.rollback()` agar memenuhi sifat *Atomicity, Consistency, Isolation, Durability* (semua berhasil atau batal semua).
- **Pessimistic Lock + Optimistic Lock (Pencegahan *Race Condition* & Layar Basi)**:
  1. *Pessimistic Lock*: Seluruh operasi pada `KRSManager` (`add_course`, `remove_course`, `submit_krs`, `approve_krs`, `revise_krs`) mengambil baris kartu lewat `_krs_terkunci()` yang menggunakan `.with_for_update()` dan memeriksa status setelah kunci diperoleh.
  2. *Optimistic Lock*: Model `KRS` dilengkapi kolom `version` (`__mapper_args__ = {"version_id_col": version}`) dan `diubah_pada`. Setiap penambahan/penghapusan `krs_detail` menyentuh `krs.diubah_pada` agar `version` pada baris `krs` selalu naik, sehingga persetujuan dari layar Dosen PA yang "basi" (versi lama) otomatis ditolak dengan `409 Conflict` (*"KRS sudah berubah, muat ulang"*).

### 3.14 Modul Jadwal & Ruangan: Interval Tree & Deteksi Bentrok 3 Dimensi
- **Pemodelan Terhubung (`ruangan` + `jadwal_kuliah`)**: Menambahkan model `Ruangan` dan `JadwalKuliah` pada `backend/app/models/schedule.py` yang berelasi langsung ke `matakuliah.kode_mk` (tanpa membongkar model legacy `Schedule` di `course.py`), sehingga setiap perubahan jadwal langsung mengetahui daftar KRS mahasiswa yang mengambil mata kuliah terkait serta memvalidasi batasan kapasitas ruangan (`enrolled_count <= kapasitas`).
- **Interval Tree untuk Irisan Waktu**: Pengecekan tumpang tindih jam menggunakan struktur data *Augmented Binary Search Tree* (`IntervalTree` dengan atribut `max_end` dan interval half-open `[start, end)`) per hari sehingga jadwal bersebelahan (`08:00-10:00` vs `10:00-12:00`) tidak dianggap bentrok, serta mengklasifikasikan konflik menjadi `room_conflict` (ruangan sama), `lecturer_conflict` (dosen sama), dan `time_overlap` (mahasiswa/MK sama atau irisan umum).

### 3.15 Observer Pattern (`ScheduleSubject` & `NotificationManager`)
- **Publisher–Subscriber Terpisah**: `ScheduleSubject` dan turunannya `NotificationManager` mengelola daftar subscriber secara dinamis lewat `attach()`, `detach()`, dan `notify(event_type, schedule_data)`.
- **Multi-Stakeholder & Simulasi Medium**: Disediakan tiga observer konkret — `StudentObserver` (simulasi Email & Push), `LecturerObserver` (simulasi Email & SMS), serta `AdminObserver` (simulasi Email, SMS, & Push) — yang menuliskan log ke logger `schedule.notifications` dan menyimpan riwayat ringkas di memori untuk ditampilkan di Conflict Resolver UI.

### 3.16 Hybrid AI-Powered Rescheduler dengan Guardrail Deterministik
- **Mode Hybrid (`AI + Rule-Based Fallback`)**: `suggest_alternative_schedules` dapat memanggil Gemini/OpenAI API via `httpx` ketika `GEMINI_API_KEY` atau `OPENAI_API_KEY` tersedia di `.env`, dan otomatis beralih ke mesin skor CSP/aturan lokal ketika API key tidak diisi, kuota habis, atau saat pengujian offline.
- **Guardrail Anti-Halusinasi**: Setiap rekomendasi JSON dari LLM (`{hari, jam, ruangan, reason}`) wajib lolos verifikasi ulang deterministik terhadap kapasitas ruangan (`kapasitas >= enrolled`), bebas bentrok ruangan, dan bebas bentrok dosen sebelum dikirim ke Admin UI.

### 3.17 Sinkronisasi Jadwal ke KRS (`invalidate_by_schedule_change -> REVISION`)
- **Pemeliharaan Invarian State Machine KRS**: Alih-alih menambah status/aktor baru yang melanggar ruang kombinasi state machine KRS (`4 status x 2 aktor`), perubahan atau penghapusan jadwal pada `SchedulingService` memanggil method khusus `KRS.invalidate_by_schedule_change(reason)` dalam satu transaksi ACID.
- **Kembali ke `REVISION`**: KRS yang berstatus `SUBMITTED`, `APPROVED`, maupun `REVISION` otomatis dikembalikan ke status `REVISION` (`approved_at = None`, `catatan_revisi` diisi keterangan perubahan jadwal, `diubah_pada` diperbarui agar `version` naik), disertai pencatatan `KRSLog` dan `Notifikasi` agar mahasiswa langsung mengetahui alasan dan dapat mengajukan ulang lewat `KRSManager`.

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
5. **Repository Pattern & Dependency Injection**
   - *Kelebihan*: Mematuhi prinsip *Dependency Inversion Principle* (DIP) dan *Single Responsibility Principle* (SRP), memudahkan unit testing secara terisolasi (*mocking*), serta memperlonggar keterikatan antar lapisan.
   - *Kekurangan*: Menambah jumlah file interface (`IPMBRepository`) dan boilerplate kode tambahan.
6. **Chain of Responsibility Pattern & Pemisahan `KRSManager` pada Modul KRS**
   - *Kelebihan*: Mematuhi *Open/Closed Principle* (OCP) dan *Single Responsibility Principle* (SRP) karena `KRSManager` hanya mengatur alur transaksi tanpa mengetahui detail angka batas SKS atau rumus jadwal, sementara setiap `Validator` fokus pada satu aturan bisnis yang dapat diuji dan disusun ulang secara independen (`Duplicate -> SKS -> Prerequisite -> Conflict`).
   - *Kekurangan*: Menambah jumlah class objek (`Validator`, `KRSContext`, `ValidationResult`) dibandingkan menulis percabangan `if-else` monolitik di dalam satu fungsi.
7. **Tabel Transisi State Machine Sendiri vs Library State Machine Eksternal**
   - *Kelebihan*: Tanpa dependensi tambahan, terintegrasi langsung dengan validator ORM SQLAlchemy (`@validates("status")`), sangat mudah diuji dan dijelaskan saat viva untuk domain 4 state KRS.
   - *Kekurangan*: Fitur otomatisasi seperti pembuatan diagram visual otomatis atau *hook on_enter/on_exit* deklaratif harus ditulis secara eksplisit di dalam method `transition()` dan `KRSManager`.
8. **Hybrid AI Rescheduler + Guardrail Deterministik vs Ketergantungan Penuh pada LLM**
   - *Kelebihan*: Tetap menghasilkan 3 rekomendasi valid secara offline dan deterministik saat pengujian maupun tanpa API key, serta melindungi Admin dari saran jadwal bentrok akibat halusinasi LLM.
   - *Kekurangan*: Penjelasan (`reason`) pada mode fallback lebih terstruktur/templat dibandingkan kalimat bebas dari LLM.
9. **Invalidasi KRS ke Status `REVISION` vs Status Terpisah `INVALIDATED`**
   - *Kelebihan*: Mahasiswa dapat langsung memperbarui dan mengajukan ulang KRS melalui alur `KRSManager` (`REVISION -> SUBMITTED`) tanpa memperbesar tabel transisi state machine maupun merusak pengujian 28 transisi ilegal.
   - *Kekurangan*: Pembedaan antara revisi oleh Dosen PA dan revisi akibat perubahan jadwal bergantung pada `catatan_revisi` serta riwayat `KRSLog` (`invalidate_schedule_change`).

