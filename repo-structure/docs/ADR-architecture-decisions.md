# ADR-001: Keputusan Arsitektur Sistem Akademik SEVIMA-Mini

## 1. Status
Disetujui

## 2. Konteks
Sistem informasi akademik mini (SEVIMA-Mini) membutuhkan desain kelas UML dan implementasi backend RESTful API (FastAPI & SQLAlchemy) yang mencakup manajemen pengguna, katalog mata kuliah, penawaran kelas per semester, KRS, modul penjadwalan kuliah & ruangan (4 entitas domain `Ruangan`, `Dosen`, `Kelas`, `Jadwal`, deteksi bentrok 3 dimensi dengan *Grouping + Sort & Sweep* dan *Naive* sebagai acuan, penguncian pesimis `FOR UPDATE`, validasi kapasitas `409 Conflict`, notifikasi berbasis *Observer Pattern*, saran penjadwalan ulang *AI-Powered* beserta *Conflict Resolver UI*, serta sinkronisasi invalidasi KRS), modul pencatatan nilai, audit trail, dan perhitungan IPS/IPK presisi desimal, serta pembayaran. Desain dikembangkan secara iteratif melalui analisis arsitektur berorientasi objek (OOP) dan prinsip SOLID.

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

### 3.15 Observer Pattern (`ScheduleSubject`, `typing.Protocol`, & Strategy `LogChannel`)
- **Pemisahan Tanggung Jawab (OCP) & `typing.Protocol` vs `ABC`**: `ScheduleSubject` dan turunannya `NotificationManager` (`backend/app/services/schedule_observer.py`) mengelola subscriber lewat `attach()`, `detach()`, dan `notify(event)`. Kontrak `ScheduleObserver`, `NotificationChannel`, dan `ParticipantRepository` ditulis menggunakan `typing.Protocol` (*structural typing*) agar kelas observer atau spy uji tidak wajib mewarisi kelas dasar tertentu (mematuhi *Dependency Inversion Principle* dan memudahkan pengujian *unit test* tanpa *boilerplate* pewarisan).
- **Immutable `ScheduleEvent` & `EventType` Enum**: `EventType` mendefinisikan `SCHEDULE_CHANGED` dan `SCHEDULE_DELETED`, dibungkus dalam `@dataclass(frozen=True) class ScheduleEvent` yang membawa `event_id` unik (UUID), `before`, `after`, `meta`, dan `timestamp`. Sifat *frozen* menjamin satu observer tidak dapat memutasi payload event bagi observer berikutnya.
- **Isolasi Error & Salinan Daftar**: `notify()` mengiterasi salinan daftar (`list(self._observers)`) sehingga `detach()` di tengah jalan tidak merusak perulangan, dan membungkus setiap `observer.update(event)` dengan blok `try ... except Exception` agar kegagalan satu observer tercatat pada `NotifyReport.failed_observers` tanpa membungkam observer berikutnya.
- **Strategy Kanal & Kunci Idempotensi**: Kanal pengiriman (`EMAIL`, `SMS`, `PUSH`) dimodelkan sebagai objek `LogChannel` berkontrak `send(..., key)` sehingga pergantian ke penyedia SMTP/gateway nyata kelak tidak menyentuh kode observer. Setiap pengiriman membawa kunci idempotensi `f"{event_id}:{recipient}:{channel.name}"` untuk mencegah pesan ganda saat *retry*.
- **Observer In-Process vs Pub/Sub**: Proyek memilih *Observer in-process* karena seluruh komponen berjalan dalam satu layanan FastAPI, namun penulisan event persisten ke tabel `outbox` menjadi fondasi transisi ke arsitektur *Publish–Subscribe* (Redis/RabbitMQ/Kafka) di masa depan.

| Subscriber (Observer) | Target Penerima | Medium Simulasi | Tujuan Notifikasi |
| :--- | :--- | :--- | :--- |
| `StudentObserver` | NIM peserta kelas via `ParticipantRepository` / `affected_nims` | `EMAIL`, `PUSH` | Menginformasikan perubahan/penghapusan jadwal dan pengajuan ulang KRS |
| `LecturerObserver` | Dosen pengampu baru & lama (`after.dosen`, `before.dosen`) | `EMAIL`, `SMS` | Memberitahu perubahan hari, jam, atau ruangan mengajar |
| `AdminObserver` | `admin.akademik@sevima.ac.id` | `EMAIL`, `SMS`, `PUSH` | Audit perubahan jadwal, jumlah KRS direvisi, dan bentrok terdeteksi |

### 3.16 Transactional Outbox & `OutboxDispatcher` (Kirim Setelah Komit)
- **Mengapa Wajib Dikirim Setelah `COMMIT`**: Mengirim notifikasi sebelum `commit()` menimbulkan dua bahaya: (1) jika server kanal mati, pengecualian membatalkan perubahan jadwal yang sah, dan (2) jika `commit()` gagal/rollback, pengguna sudah terlanjur menerima notifikasi palsu.
- **Pola Transactional Outbox (`outbox` vs `notifikasi` Minggu 6)**: Tabel `notifikasi` dari Minggu ke-6 tetap dipertahankan sebagai kotak masuk (*inbox*) mahasiswa di database, sedangkan tabel baru `outbox` (`backend/app/models/schedule.py`, migrasi `c3d4e5sch009`) berfungsi sebagai log event handal dengan kolom `event_id` unik, `payload` JSON (`event_type`, `before`, `after`, `meta`), `status` (`pending`/`sent`/`failed`), `attempts`, dan `last_error`.
- **Atomisitas + *At-Least-Once Delivery* dengan Deduplikasi**: Perubahan/penghapusan `Jadwal`, invalidasi KRS, dan penambahan baris `Outbox` dieksekusi dalam **satu transaksi DB (1× `commit()`)**. Setelah komit berhasil, `OutboxDispatcher.run()` mengunci baris `pending` dengan `.with_for_update(skip_locked=True)` agar aman dari dua worker bersamaan, memanggil `subject.notify(event)`, menandai `sent` bila `report.ok`, atau me-retry maksimal **5 kali** sebelum menjadi `failed`. Kegagalan dispatcher tidak pernah membatalkan perubahan jadwal.

### 3.17 Sinkronisasi Jadwal ke KRS via `Actor.SYSTEM` & Satu Pintu `transition()`
- **Penambahan `Actor.SYSTEM` pada State Machine**: Alih-alih membuat jalan pintas yang mem-bypass `TRANSITIONS`, `Actor` di `backend/app/models/krs.py` diperluas dengan `Actor.SYSTEM` dan dua transisi resmi baru: `(KRSStatus.SUBMITTED, Actor.SYSTEM) -> KRSStatus.REVISION` dan `(KRSStatus.APPROVED, Actor.SYSTEM) -> KRSStatus.REVISION`.
- **Satu Pintu `transition()` & Ruang Kombinasi 48 Kasus**: Method `KRS.invalidate_by_schedule_change(reason)` kini mendelegasikan langsung ke `self.transition(KRSStatus.REVISION, actor=Actor.SYSTEM, catatan=reason)` (mengosongkan `approved_at = None` dan mengisi `catatan_revisi`), sementara `DRAFT` dan `REVISION` tidak disentuh. Konsekuensinya, uji parametrisasi di `backend/tests/test_krs_property.py` diperbarui menjadi $4 \times 4 \times 3 = 48$ kombinasi (**6 sah** dan **42 ilegal**). Invalidator ikut di dalam transaksi `SchedulingService` tanpa melakukan `commit()` sendiri.

### 3.18 AI Rescheduler (`LLMClient` + 4 Saringan), Conflict Resolver UI Satu Pintu, & RBAC
- **Abstraksi `LLMClient` & Determinisme Slot**: Pemanggilan LLM dibungkus di balik `Protocol LLMClient` dengan method `complete(prompt) -> str` (`GeminiLLMClient` dengan JSON mode `responseMimeType: "application/json"`, `OpenRouterLLMClient`, `OpenAILLMClient`, dan `FakeLLMClient` untuk CI test deterministik tanpa panggilan API nyata). Daftar slot tersedia dihitung secara deterministik oleh backend dari matriks hari/jam/ruangan dikurangi jadwal terisi — **tidak pernah dikarang oleh AI**.
- **Empat Saringan Ketat Atas Keluaran AI (`filter_ai_suggestions`)**:
  1. **Saringan 1 (Parsing):** Mengekstrak substring di antara `[` pertama dan `]` terakhir; JSON rusak mengembalikan `[]` tanpa crash.
  2. **Saringan 2 (Skema Pydantic):** Validasi tiap item dengan `AISuggestionItem` (`hari` 1–6, format jam `datetime.time` sah); item rusak dibuang per item.
  3. **Saringan 3 (Ruangan & Kapasitas):** Ruangan wajib ada di database dan `kapasitas >= enrolled_count`.
  4. **Saringan 4 (Deteksi Bentrok Ulang):** Membentuk calon `JadwalSlot(id=-1, ...)` dan memanggil `detect_conflicts_sweep()`; jika `-1` muncul di konflik, saran dibuang. Hanya maks. 3 saran tervalidasi yang dikembalikan (dengan *rule-based fallback* opsional pada mode interaktif).
- **Conflict Resolver UI Satu Pintu & RBAC Admin Akademik**: Halaman `/dashboard/conflicts` (`backend/app/static/conflict_resolver.html`) menyediakan login Admin Akademik (`POST /api/auth/login`), daftar bentrok, rekomendasi AI, serta tabel status *Outbox*. Tombol *"Terapkan Jadwal"* memanggil `PUT /api/schedules/{id}` yang sama (prinsip satu pintu: cek bentrok ulang `409` bila slot keburu terisi, invalidasi KRS, tulis Outbox, kirim notifikasi). Seluruh endpoint manajemen `/api/schedules/*` diproteksi dependensi JWT `require_admin_akademik` (`401`/`403`).

### 3.19 Ekspor Kalender Perkuliahan (iCalendar `.ics`)
- **Standar RFC 5545 tanpa Dependensi Eksternal Tambahan**: `backend/app/services/calendar_exporter.py` dan endpoint `GET /api/schedules/export.ics` (mendukung filter `?semester=` dan `?nim=`) mengekspor jadwal ke berkas `.ics` yang kompatibel dengan Google Calendar dan kalender ponsel.
- **Detail Protokol & Sinkronisasi**:
  - Pemisah baris wajib `CRLF` (`\r\n`) dan blok `VTIMEZONE` `Asia/Jakarta`.
  - `UID` stabil (`jadwal-{id}@sevima-mini.ac.id`) dan kolom `jadwal.sequence` (dinaikkan tiap kali jadwal diubah via `update_schedule`) agar impor ulang memperbarui event lama tanpa duplikasi.
  - `DTSTART`/`DTEND` dihitung dari tanggal pertemuan pertama sesuai awal semester dan hari kuliah, dilengkapi `RRULE:FREQ=WEEKLY;UNTIL=...Z` (konversi akhir semester ke UTC berakhiran `Z` sesuai RFC 5545 saat `DTSTART` memakai `TZID`).

### 3.20 Single Source of Truth Nilai (`krs_detail`), `skala_nilai` Berbasis Data, & Asumsi Kelulusan (Minggu 9)
- **Menyimpan Nilai di `krs_detail` vs Tabel `grades` Terpisah:**
  - Sejak Minggu ke-5, tabel `krs_detail` sudah memiliki kolom `nilai` (`nullable`), dan sejak Minggu ke-7 memiliki `kelas_id`, sehingga satu baris `krs_detail` secara unik merepresentasikan **satu mahasiswa pada satu kelas di satu semester**. Query prasyarat KRS juga membaca kolom ini.
  - Membuat tabel `grades` kedua untuk modul nilai akan menciptakan dua sumber kebenaran (*dual source of truth*) yang rentan menyimpang. Oleh karena itu, modul nilai Minggu ke-9 menggunakan **`krs_detail.nilai`** sebagai *single source of truth*, dengan **Foreign Key** `fk_krs_detail_nilai_skala_nilai` ke `skala_nilai.huruf` (`d4e5f6grd010`) agar huruf tak dikenal ditolak langsung oleh database. Model legacy `Grade` (`grades`) di `backend/app/models/grade.py` dipertahankan sementara semata untuk *backward-compatibility* test awal Minggu 1–4.
- **Skala Nilai `NUMERIC(3, 2)` / `Decimal` & Kolom `lulus BOOLEAN`:**
  - Tabel `skala_nilai` menyimpan `huruf` (`A`, `B`, `C`, `D`, `E`), `bobot` bertipe `NUMERIC(3, 2)` (`Decimal` di Python—bukan `float`), dan kolom `lulus` (`BOOLEAN`).
  - Menyimpan kelulusan sebagai **data** di kolom `skala_nilai.lulus` (bukan konstanta `bobot >= 2.0` di kode) membuat `GPACalculator` maupun `PrerequisiteValidator` adaptif terhadap perubahan kebijakan akademik cukup dengan mengubah baris data.
- **Penanganan Kontradiksi Spesifikasi `>= D (2.0)`:**
  - Dokumen tugas menyatakan *"Lulus mata kuliah jika nilai >= D (2.0)"*, padahal `D = 1.00` dan `2.00 = C`. AI dilarang menebak diam-diam; pertanyaan resmi dicatat di `repo-structure/docs/stakeholder-questions-minggu-9.md`, sementara sistem memakai asumsi sementara **minimal `C` (`A/B/C = True`, `D/E = False`)** agar selaras dengan angka `2.0` dan prasyarat Minggu 5–6.

### 3.21 Penjaga Input Nilai 2 Lapis, `PresensiPort` (DIP Stub), `FOR UPDATE`, & `get_current_dosen`
- **Dua Penjaga di `GradeService.input_nilai()`:**
  1. **Otorisasi Kepemilikan (`is_pengampu`):** Memeriksa apakah terdapat baris pada tabel `jadwal` yang memasangkan `kelas_id` dengan `dosen_id`. Jika bukan pengampu, langsung melempar `GradeForbiddenError` (`403`) **sebelum** membaca data mahasiswa mana pun. Identitas dosen diambil dari JWT via dependency `get_current_dosen` (`role == "dosen"` + klaim `dosen_id`/`nidn` ke master `dosen`), bukan dari *request body*.
  2. **Penjaga Presensi (`>= 75%`) via `PresensiPort`:** Karena modul presensi baru dibangun pada Minggu ke-12, `GradeService` menerapkan *Dependency Inversion Principle* dengan menerima protokol `PresensiPort` melalui konstruktor dan memakai `StubPresensiPort` (berbasis kamus memori) untuk sementara. Batas tepat `75%` diizinkan; `< 75%` ditolak dengan `PresensiKurangError` (`422`). Saat Minggu ke-12 selesai, implementasi DB nyata cukup disuntikkan tanpa mengubah satu baris pun di `GradeService`.
- **Pencegahan Race Condition & Idempotensi PUT:**
  - Baris `KRSDetail` dikunci dengan `.with_for_update()` (`404` jika tidak ada) agar dua dosen pengampu paralel tidak saling menimpa nilai tanpa jejak.
  - Endpoint `PUT /api/kelas/{kelas_id}/nilai/{nim}` memvalidasi payload `NilaiIn` (`^[A-E]$`, `min_length=1`, `max_length=1` $\rightarrow$ `422` untuk input seperti `"F+"` atau huruf kecil) sebelum masuk servis, bersifat *no-op* jika huruf sama dengan yang tersimpan, mewajibkan `alasan` (`AlasanWajibError` `422`) saat mengubah nilai lama, dan menangani seluruh error secara polimorfik melalui `@app.exception_handler(GradeError)`.

### 3.22 Compute-on-Read IPK, Functional Core, & Verifikasi SQL Aggregate
- **Compute-on-Read vs Cache Kolom `ipk`:**
  - Kriteria *"IPK terupdate otomatis saat nilai diinput"* dipenuhi dengan pola **hitung saat dibaca (*compute-on-read*)**, bukan menyimpan kolom cache `ipk`.
  - Satu mahasiswa umumnya hanya memiliki $\le 60$ baris nilai selama kuliah sehingga 1 query terindeks `krs.nim` berjalan dalam hitungan milidetik dan menjamin IPK tidak pernah basi (*stale*) meskipun ada koreksi data. Jika kelak sistem memerlukan laporan massal ribuan mahasiswa sekaligus, mekanisme *cache invalidation* dapat dibangun memakai Transactional Outbox + Observer dari Minggu ke-8.
- **Presisi `Decimal` & *Functional Core, Imperative Shell*:**
  - Logika inti dipisahkan dari ORM ke dataclass *frozen* `Skala` dan `NilaiRecord` beserta tiga fungsi murni (`rata`, `hitung_ips`, `hitung_ipk`) di `backend/app/services/gpa_calculator.py`. Seluruh aritmatika memakai `Decimal` (diinisialisasi dari string/integer, bukan `float`) dan dibulatkan **hanya sekali di akhir** dengan `ROUND_HALF_UP` (`0.01`) sehingga `3.125` menjadi `3.13` (bukan `3.12` oleh *banker's rounding* `round()`). Endpoint API mengirim `ips` dan `ipk` sebagai **string** 2 desimal (`"3.08"`) agar klien tidak mengonversinya kembali ke `float`.
  - **Urutan Wajib `hitung_ipk`:** Ambil nilai terbaik per `kode_mk` berdasarkan **`bobot` numerik tertinggi** (bukan `max()` pada string huruf karena `'E' > 'A'` secara ASCII), **lalu** saring `skala[huruf].lulus`, dan hitung dari total mutu dibagi total SKS (mengembalikan `Decimal("0.00")` jika total SKS nol). `NilaiRepo` hanya bertugas menarik `records(nim)` (`nilai IS NOT NULL`) dan `skala()` untuk diserahkan ke `GPACalculator`. Tersedia pula `calculate_ipk_sql` (CTE `terbaik` + `ROW_NUMBER()` + `NULLIF`) untuk *differential testing*.

### 3.23 Audit Trail `grade_history` dalam Satu Transaksi Service vs DB Trigger & View `riwayat_nilai`
- **Satu Transaksi di `GradeService` vs Database Trigger:**
  - Perubahan `krs_detail.nilai` dan penambahan baris `grade_history` (termasuk input pertama dengan `nilai_lama = NULL` serta stempel waktu UTC) dieksekusi di dalam satu blok transaksi `try ... db.commit() / except ... db.rollback()`.
  - Pendekatan *service transaction* dipilih dibanding *database trigger* karena konteks aplikasi (`diubah_oleh` `dosen_id` dan `alasan`) tersedia langsung tanpa variabel sesi khusus, logikanya eksplisit dan mudah diuji, serta sintaksnya konsisten antara SQLite (pengujian) dan MySQL/PostgreSQL (produksi). Keduanya **tidak boleh dipakai bersamaan** agar satu perubahan tidak tercatat dua kali.
- **Append-Only & SQL View `riwayat_nilai`:**
  - Tabel `grade_history` bersifat *append-only* (tidak pernah di-`UPDATE` atau `DELETE`; di produksi hak `UPDATE`/`DELETE` untuk user aplikasi dicabut). SQL View `riwayat_nilai` menggabungkan `grade_history`, `krs_detail`, `krs`, `matakuliah`, dan `dosen` sehingga endpoint `GET /api/mahasiswa/{nim}/riwayat-nilai` dapat mengambil histori lengkap mahasiswa dengan satu `SELECT`.

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
9. **Invalidasi KRS ke Status `REVISION` via `Actor.SYSTEM` vs Status Terpisah `INVALIDATED`**
   - *Kelebihan*: Tetap menjaga prinsip satu pintu `KRS.transition()` dan seluruh aturan tercatat di `TRANSITIONS` ($4 \times 4 \times 3 = 48$ kombinasi: 6 sah, 42 ilegal), sekaligus memungkinkan mahasiswa langsung mengajukan ulang KRS (`REVISION -> SUBMITTED`) tanpa memperbanyak state kartu KRS.
   - *Kekurangan*: Memerlukan pembaruan uji parametrisasi transisi ilegal dari 28 menjadi 42 kombinasi serta pembedaan antara revisi Dosen PA dan revisi sistem melalui `catatan_revisi` serta `KRSLog`.
10. **Grouping + Sort & Sweep vs Naive vs Interval Tree untuk Deteksi Bentrok Jadwal**
    - *Kelebihan*: Pengelompokan `(hari, ruangan_kode)` & `(hari, dosen_id)` diikuti *Sort & Sweep* menyapu ~600 jadwal kampus hanya dalam **0,60 ms** (vs **5,22 ms** pada *Naive*), tanpa dependensi eksternal maupun kerumitan penyeimbangan *tree*, sementara versi *Naive* tetap dipertahankan sebagai *oracle* pada *differential testing* Hypothesis (`Counter(sweep) == Counter(naive)`).
    - *Kekurangan*: Jika kelak sistem menangani pencarian interval dinamis berskala jutaan data atau *CSP solver* ribuan kandidat per detik, struktur indeks berbasis *Interval Tree* tetap perlu dipertimbangkan ulang.
11. **Embedded Admin Dashboard HTML/JS vs SPA Frontend Terpisah (React/Vite)**
    - *Kelebihan*: Nol dependensi frontend tambahan, langsung aktif saat `uvicorn` dijalankan di `/dashboard/conflicts`, dan mudah diuji end-to-end langsung lewat FastAPI `TestClient`.
    - *Kekurangan*: Tidak memiliki manajemen state atau komponen modular skala besar seperti React/Vue apabila UI berkembang menjadi portal multi-halaman kompleks.
12. **Transactional Outbox (`outbox` + `OutboxDispatcher`) vs Pemanggilan `notify()` Langsung Setelah `commit()`**
    - *Kelebihan*: Menjamin event tidak pernah hilang apabila aplikasi crash tepat setelah `commit()`, mendukung *retry* otomatis hingga 5× dengan *idempotency key* (deduplikasi), aman dari worker ganda via `SKIP LOCKED`, serta mempertahankan tabel `notifikasi` sebagai kotak masuk mahasiswa.
    - *Kekurangan*: Menambah satu tabel dan langkah migrasi (`c3d4e5sch009`) serta eksekusi dispatcher setelah komit.
13. **`typing.Protocol` vs `ABC` untuk Kontrak Observer, Channel, & `LLMClient`**
    - *Kelebihan*: Mendukung *structural subtyping* (*duck typing* bertipe aman) sehingga `SpyObserver`, `BrokenObserver`, dan `FakeLLMClient` dapat ditulis ringkas tanpa mewarisi kelas abstrak tertentu.
    - *Kekurangan*: Pelanggaran tanda tangan method hanya terdeteksi saat pemeriksaan tipe statis (`mypy`/`pyright`) atau saat `update()`/`complete()` dipanggil, bukan saat instansiasi kelas seperti `ABC`.
14. **Generator iCalendar `.ics` Murni Python vs Library Eksternal (`icalendar`)**
    - *Kelebihan*: `+0` dependensi tambahan untuk format teks RFC 5545 yang relatif kecil (`VCALENDAR`/`VEVENT`/`VTIMEZONE`), serta memberi kendali penuh atas pemisah baris `CRLF` (`\r\n`), `UID`, `SEQUENCE`, dan format UTC `UNTIL`.
    - *Kekurangan*: Jika kelak dibutuhkan fitur iCalendar tingkat lanjut (seperti pengecualian tanggal libur `EXDATE` atau zona waktu DST dinamis lintas negara), pemakaian library `icalendar` + `dateutil` akan lebih hemat usaha.
15. **`krs_detail.nilai` sebagai Single Source of Truth vs Tabel `grades` Terpisah**
    - *Kelebihan*: Menghilangkan duplikasi sumber kebenaran antara prasyarat KRS dan modul nilai, memanfaatkan relasi `kelas_id` & `krs` yang sudah ada, serta menjaga integritas huruf melalui Foreign Key ke `skala_nilai.huruf`.
    - *Kekurangan*: Memerlukan migrasi `batch_alter_table` pada SQLite (`d4e5f6grd010`) dan pembaruan fixture test lama agar mengisi `skala_nilai` terlebih dahulu sebelum menulis `KRSDetail.nilai`.
16. **Compute-on-Read IPK vs Kolom Cache `ipk` di Database**
    - *Kelebihan*: IPK dan IPS selalu konsisten 100% dengan data nilai mutakhir tanpa kompleksitas invalidasi cache, sangat cepat untuk ~60 baris per mahasiswa, dan menghindari risiko data basi akibat perubahan manual/remedial.
    - *Kekurangan*: Jika kelak terdapat halaman rekap transkrip atau peringkat untuk ribuan mahasiswa dalam satu request, query agregasi per mahasiswa perlu digantikan oleh cache terkelola (via Transactional Outbox + Observer) atau query batch.
17. **Functional Core (`Decimal` Pure Functions) vs Kalkulasi Langsung di ORM / SQL**
    - *Kelebihan*: Fungsi murni (`rata`, `hitung_ips`, `hitung_ipk`) dapat diuji ratusan/ribuan kali per detik dengan `pytest.mark.parametrize` dan `Hypothesis` tanpa DB/mock, menjamin `Decimal` + `ROUND_HALF_UP` presisi penuh, dan menjadi *oracle* bagi *differential testing* versi SQL CTE.
    - *Kekurangan*: Membutuhkan layer `NilaiRepo` tipis serta penyesuaian skema API agar IPK/IPS dikembalikan sebagai string 2 desimal (bukan float JSON).
18. **Audit Trail via Satu Transaksi `GradeService` vs Database Trigger (+ `StubPresensiPort`)**
    - *Kelebihan*: Menyimpan `diubah_oleh` (`dosen_id`) dan `alasan` secara portabel di SQLite maupun MySQL/PostgreSQL dalam satu unit atomik `try/commit/rollback`, sementara `PresensiPort` memungkinkan pengembangan & pengujian penuh Minggu 9 tanpa menunggu Modul Presensi Minggu 12.
    - *Kekurangan*: Perubahan nilai langsung lewat SQL manual di luar aplikasi tidak terekam ke `grade_history` (diatasi di produksi dengan membatasi akses tulis langsung), dan fitur presensi nyata bergantung pada injeksi implementasi `PresensiPort` baru pada Minggu 12.

