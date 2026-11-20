# ADR-001: Keputusan Arsitektur Sistem Akademik SEVIMA-Mini

## 1. Status
Disetujui

## 2. Konteks
Sistem informasi akademik mini (SEVIMA-Mini) membutuhkan desain kelas UML dan implementasi backend RESTful API (FastAPI & SQLAlchemy) yang mencakup manajemen pengguna, katalog mata kuliah, penawaran kelas per semester, KRS, modul penjadwalan kuliah & ruangan (4 entitas domain `Ruangan`, `Dosen`, `Kelas`, `Jadwal`, deteksi bentrok 3 dimensi dengan *Grouping + Sort & Sweep* dan *Naive* sebagai acuan, penguncian pesimis `FOR UPDATE`, validasi kapasitas `409 Conflict`, notifikasi berbasis *Observer Pattern*, saran penjadwalan ulang *AI-Powered* beserta *Conflict Resolver UI*, serta sinkronisasi invalidasi KRS), pencatatan nilai, serta pembayaran. Desain dikembangkan secara iteratif melalui analisis arsitektur berorientasi objek (OOP) dan prinsip SOLID.

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

### 3.14 Modul Jadwal & Ruangan (Minggu 7): Empat Model Domain, CSP, Sort & Sweep vs Interval Tree, Locking Pesimis, & Polimorfisme Error
- **Pemodelan 4 Entitas Domain & Migrasi (`b2c3d4sch008`)**:
  - Domain penjadwalan dipecah menjadi empat tabel eksplisit di `backend/app/models/schedule.py`: `Ruangan` (`kode` sebagai PK alami + `kapasitas`), `Dosen` (`nidn` unik + `nama`), `Kelas` (`kode_mk` FK `matakuliah.kode_mk`, `nama_kelas` paralel mis. `A`/`B`, `kuota`, `semester`), dan `Jadwal` (`kelas_id`, `ruangan_kode`, `dosen_id`, `hari` 1..6, `jam_mulai` & `jam_selesai` bertipe `Time`).
  - Pemisahan `Jadwal` dari `Kelas` memungkinkan satu kelas memiliki lebih dari satu pertemuan mingguan (misalnya kuliah teori hari Senin di ruang kelas dan praktikum hari Kamis di laboratorium).
  - Lewat migrasi Alembic `b2c3d4sch008`, kolom `hari`, `jam_mulai`, `jam_selesai` dihapus dari tabel `matakuliah` (karena jam bukan lagi milik mata kuliah tunggal) dan kolom `kelas_id` ditambahkan ke `krs_detail`.
  - **Indeks Gabungan Berbasis Query**: Tabel `jadwal` mendefinisikan `Index("ix_jadwal_hari_ruangan", "hari", "ruangan_kode")` dan `Index("ix_jadwal_hari_dosen", "hari", "dosen_id")` karena query tersering adalah memeriksa jadwal di ruangan atau dosen tertentu pada hari tertentu, disertai `CheckConstraint` (`hari BETWEEN 1 AND 6` dan `jam_mulai < jam_selesai`).
- **Penjadwalan sebagai *Constraint Satisfaction Problem* (CSP)**:
  - *Variabel*: setiap pertemuan kelas yang perlu dijadwalkan; *Domain*: kombinasi hari, slot jam, dan ruangan; *Hard Constraints*: bebas bentrok ruangan, bebas bentrok dosen, dan kebutuhan kursi $\le$ kapasitas ruangan; *Soft Constraints*: preferensi waktu pagi/siang dan minimal gangguan jadwal mahasiswa (ditangani pada saran penjadwalan ulang).
- **Aturan Interval Setengah Terbuka & Dua Tipe Konflik**:
  - Setiap jadwal diperlakukan sebagai interval setengah terbuka $[\text{jam\_mulai}, \text{jam\_selesai})$ ($\text{mulai}_1 < \text{selesai}_2 \land \text{mulai}_2 < \text{selesai}_1$) sehingga kuliah bersambung (misalnya `08:00–09:40` dan `09:40–11:20`) tidak bentrok.
  - Detektor hanya mengembalikan 2 tipe konflik (`ConflictType = Literal["room_conflict", "lecturer_conflict"]`) dalam `@dataclass(frozen=True) class Conflict` (*hashable* untuk `set`/`Counter`, dengan ID pasangan diurutkan lewat `pasangan(a, b)`). Irisan waktu saja tanpa kesamaan ruang atau dosen bukan konflik.
- **Keputusan Menunda *Interval Tree* & Memilih *Grouping + Sort & Sweep* (Berbasis Pengukuran)**:
  - `backend/app/services/conflict_detector.py` mempertahankan **Versi Naive** (`detect_conflicts_naive`, $O(n^2)$ memakai `itertools.combinations`) sebagai *oracle* acuan kebenaran dan menggunakan **Versi Grouping + Sort & Sweep** (`detect_conflicts_sweep`, $O(n \log n + k)$ dengan kamus `ATURAN_KELOMPOK`) untuk produksi.
  - Berdasarkan hasil benchmark nyata pada **600 jadwal** (179.700 pasangan):
    - **Dataset kampus tersebar** (600 jadwal, 18 ruang × 5 hari $\approx 6,7$ jadwal/ruang/hari, 439 konflik): `Naive = 5,22 ms` vs `Sort & Sweep = 0,60 ms` (~8,7× lebih cepat).
    - **Dataset padat** (600 jadwal, 7.410 konflik): `Naive = 7,80 ms` vs `Sort & Sweep = 4,53 ms`.
  - Karena rata-rata beban per ruang per hari di kampus hanya 6–8 jadwal, waktu eksekusi *Grouping + Sort & Sweep* sudah sub-milidetik (`0,60 ms`). Penambahan struktur data *Interval Tree* sengaja **ditunda** agar tidak menambah kompleksitas kode dan dependensi tanpa keuntungan terukur; *Interval Tree* baru layak bila sistem berkembang ke peminjaman ruang lintas tahun atau *CSP solver* yang menguji ribuan kandidat jadwal per detik.
- **Penguncian Pesimis Anti-*Deadlock*, Capacity Check `409`, Validasi `422`, & Polimorfisme Error**:
  - `SchedulingService._simpan()` menyatukan alur `create_schedule` dan `update_schedule` dalam satu transaksi: validasi `Kelas` & jam $\rightarrow$ kunci baris `Ruangan` terlebih dahulu lalu `Dosen` via `.with_for_update()` (urutan tetap mencegah *deadlock*; dipilih karena MySQL tidak memiliki *exclusion constraint* seperti PostgreSQL) $\rightarrow$ query bentrok langsung di SQL memakai indeks gabungan (mengecualikan `id` sendiri saat `update`) $\rightarrow$ `cek_kapasitas()` dengan `max(kelas.kuota, jumlah_terdaftar_krs) <= ruangan.kapasitas` (`409 Conflict`, sehingga kelas berkuota 50 tetap ditolak di ruang berkapasitas 40 meski mahasiswa KRS masih 0) $\rightarrow$ `db.add(jadwal)` diletakkan paling akhir sebelum `commit()` agar *autoflush* SQLAlchemy tidak memicu query bentrok terhadap jadwal yang belum tervalidasi.
  - Validasi format jam (`datetime.time`) dan `jam_mulai < jam_selesai` ditegakkan di pintu API melalui Pydantic (`422 Unprocessable Entity`), sementara `ScheduleError.body()` dan `ScheduleConflictError.body()` ditangani secara polimorfik oleh `@app.exception_handler(ScheduleError)` di `main.py` (`404` tidak ditemukan, `409` bentrok/kapasitas).

| Aspek Perbandingan | Grouping + Sort & Sweep ($O(n \log n + k)$) | Naive Pairwise ($O(n^2)$) | Interval Tree *(Ditunda)* |
| :--- | :--- | :--- | :--- |
| **Performa 600 Jadwal Kampus** | **0,60 ms** (dataset tersebar), **4,53 ms** (padat) | 5,22 ms (tersebar), 7,80 ms (padat) | Overhead tree untuk 6–8 jadwal/ruang/hari tidak signifikan |
| **Kompleksitas & Dependensi** | Ringkas (~25 baris, +0 dependensi) | Paling sederhana (**dipertahankan sebagai *oracle* tes**) | Struktur BST tambahan (`max_end`) / paket eksternal |
| **Kesesuaian Skala** | **Optimal** untuk penjadwalan semester (~600 jadwal) | Memadai untuk acuan pengujian & verifikasi properti | Layak untuk *solver* ribuan kandidat/detik atau histori multi-tahun |

### 3.15 Observer Pattern (`ScheduleSubject` & `NotificationManager`)
- **Publisher–Subscriber Terpisah**: `ScheduleSubject` dan turunannya `NotificationManager` (`backend/app/services/schedule_observer.py`) mengelola daftar subscriber secara dinamis lewat `attach()`, `detach()`, dan `notify(event_type, schedule_data)` untuk empat tipe event (`SCHEDULE_CREATED`, `SCHEDULE_CHANGED`, `SCHEDULE_DELETED`, `CONFLICT_DETECTED`). Alur interaksi lengkap didokumentasikan pada `repo-structure/diagrams/sequence-schedule-observer.mmd`.
- **Multi-Stakeholder & Simulasi Medium**:

| Subscriber (Observer) | Target Penerima | Medium Simulasi | Tujuan Notifikasi |
| :--- | :--- | :--- | :--- |
| `StudentObserver` | Seluruh NIM terdampak (`affected_nims`) | `EMAIL`, `PUSH` | Menginformasikan perubahan/penghapusan jadwal dan pengajuan ulang KRS |
| `LecturerObserver` | Dosen pengampu baru & lama (`dosen`, `old_dosen`) | `EMAIL`, `SMS` | Memberitahu perubahan hari, jam, atau ruangan mengajar |
| `AdminObserver` | `admin.akademik@sevima.ac.id` | `EMAIL`, `SMS`, `PUSH` | Audit perubahan jadwal, jumlah KRS direvisi, dan bentrok terdeteksi |

### 3.16 Hybrid AI-Powered Rescheduler & Conflict Resolver UI
- **Tiga Constraint Penjadwalan Ulang & Kontrak JSON**: `suggest_alternative_schedules()` (`backend/app/services/schedule_recommender.py`) menghasilkan hingga **3 alternatif jadwal** dengan format `[{hari, jam, ruangan, reason}]` yang wajib memenuhi: (1) `kapasitas >= enrolled`, (2) nol bentrok ruangan maupun jadwal dosen pengampu, serta (3) disrupsi minimal bagi mahasiswa (memprioritaskan slot pagi `07:00–12:00` dan siang `12:00–15:00` serta menghindari jadwal bentrok KRS mahasiswa terkait).
- **Mode Hybrid (`AI + Rule-Based Fallback`) & Konfigurasi `.env`**: Jika `GEMINI_API_KEY` atau `OPENAI_API_KEY` (beserta `AI_MODEL` opsional) tersedia di `.env`, backend memanggil LLM API via `httpx`; bila key kosong, offline, atau gagal, sistem otomatis beralih ke mesin skor deterministik lokal. Setiap output JSON dari LLM tetap melewati *guardrail* deterministik untuk menolak slot halusinasi yang melanggar kapasitas atau bentrok.
- **Embedded Conflict Resolver UI (`/dashboard/conflicts`)**: Antarmuka admin disajikan langsung oleh FastAPI (`FileResponse` ke `backend/app/static/conflict_resolver.html`) menggunakan HTML5, CSS3, dan Vanilla JavaScript tanpa pipeline Node.js/React/Vite terpisah, sehingga ringan, nol langkah build tambahan, dan langsung terhubung ke endpoint `/api/schedules/*` serta `/api/schedules/seed-demo`.

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
10. **Grouping + Sort & Sweep vs Naive vs Interval Tree untuk Deteksi Bentrok Jadwal**
    - *Kelebihan*: Pengelompokan `(hari, ruangan_kode)` & `(hari, dosen_id)` diikuti *Sort & Sweep* menyapu ~600 jadwal kampus hanya dalam **0,60 ms** (vs **5,22 ms** pada *Naive*), tanpa dependensi eksternal maupun kerumitan penyeimbangan *tree*, sementara versi *Naive* tetap dipertahankan sebagai *oracle* pada *differential testing* Hypothesis (`Counter(sweep) == Counter(naive)`).
    - *Kekurangan*: Jika kelak sistem menangani pencarian interval dinamis berskala jutaan data atau *CSP solver* ribuan kandidat per detik, struktur indeks berbasis *Interval Tree* tetap perlu dipertimbangkan ulang.
11. **Embedded Admin Dashboard HTML/JS vs SPA Frontend Terpisah (React/Vite)**
    - *Kelebihan*: Nol dependensi frontend tambahan, langsung aktif saat `uvicorn` dijalankan di `/dashboard/conflicts`, dan mudah diuji end-to-end langsung lewat FastAPI `TestClient`.
    - *Kekurangan*: Tidak memiliki manajemen state atau komponen modular skala besar seperti React/Vue apabila UI berkembang menjadi portal multi-halaman kompleks.

