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


## Log 06 — Refaktorisasi Model KRS ke SQLAlchemy 2.0 & Implementasi Chain of Responsibility untuk Validasi KRS

### Tujuan
Menyelaraskan seluruh model akademik (User, Course, Kelas, Schedule, PendaftaranKRS, Enrollment, Grade, Payment) ke sintaks modern **SQLAlchemy 2.0 (`Mapped` & `mapped_column`)**, menerapkan pola 2 tingkat pada KRS (`PendaftaranKRS` sebagai satu kartu/header dengan atribut `semester`, `status`, dan `dosen_pa_id`, serta `Enrollment` sebagai baris detail kartu tanpa status per baris), serta mengimplementasikan **Chain of Responsibility Pattern** untuk validasi KRS (`SKSValidator`, `DuplicateValidator`, `PrerequisiteValidator`, `ConflictValidator`) yang bebas query N+1.

### Perintah (Prompt)
"Implementasikan Chain of Responsibility pattern untuk validasi KRS:
1. SKSValidator: cek total <= 24
2. PrerequisiteValidator: cek nilai MK prasyarat
3. ConflictValidator: cek bentrok jadwal
4. DuplicateValidator: cek double enrollment
Buat abstract Validator base class. Setiap validator return ValidationResult (pass/fail + message). Chain berhenti saat ada failure."

+ konteks dari saya:
- Python 3.12+, SQLAlchemy 2.0 (`Mapped` & `mapped_column`), sesuaikan dengan nama model yang ada (`Course`, `Kelas`, `Schedule`, `PendaftaranKRS`, `Enrollment`, `Grade`).
- Pastikan status KRS berada di level kartu (`PendaftaranKRS`), bukan per baris (`Enrollment`), serta tambahkan `semester` dan `dosen_pa_id` pada kartu KRS.
- Nilai prasyarat minimal C dibandingkan menggunakan bobot numerik (`bobot >= 2.0`), bukan perbandingan string huruf mentah, dan harus lulus pada semester sebelumnya.
- Cek bentrok jadwal menggunakan rumus irisan interval (`mulai_A < selesai_B` dan `mulai_B < selesai_A` pada hari yang sama), tepat 24 SKS masih diizinkan, pesan kegagalan wajib menyebut nama mata kuliah terkait, dan hindari query di dalam loop (N+1).

### Hasil (Hasil Implementasi)
- Refaktorisasi seluruh model di `backend/app/models/` (`user.py`, `course.py`, `pendaftaran.py`, `enrollment.py`, `grade.py`, `payment.py`) ke sintaks **SQLAlchemy 2.0 (`Mapped` & `mapped_column`)** serta perbaikan referensi ForeignKey `calon_mahasiswa.id`.
- Pemisahan struktur KRS 2 tingkat: penambahan `semester` dan `dosen_pa_id` pada `PendaftaranKRS` (kartu KRS) dan penghapusan `status` per baris dari `Enrollment` (baris detail KRS).
- Penambahan atribut `jam_mulai` dan `jam_selesai` pada model `Schedule` dan skema `course.py` untuk mendukung perhitungan irisan interval jadwal.
- Pembuatan modul `backend/app/services/krs_validator.py` yang mengimplementasikan *Chain of Responsibility Pattern* (`Validator` abstract base class, `ValidationResult`, `SKSValidator`, `DuplicateValidator`, `PrerequisiteValidator`, `ConflictValidator`) serta fungsi `validate_krs_with_db()` menggunakan `selectinload` (bebas query N+1).
- Penambahan pengujian unit di `backend/test_models_and_schemas.py` mencakup batas tepat 24 SKS vs 25 SKS, deteksi *double enrollment*, validasi prasyarat nilai D vs C pada semester sebelumnya, deteksi irisan interval jadwal, dan integrasi SQLAlchemy 2.0 dengan hasil **20 passed** secara keseluruhan (`pytest`).

### Evaluasi (Objektif)
- **Kelebihan**: Desain validasi KRS memenuhi prinsip *Single Responsibility Principle* (SRP) dan *Open/Closed Principle* (OCP) melalui *Chain of Responsibility*, sehingga penambahan aturan validasi baru dapat dilakukan tanpa memodifikasi kode validator yang sudah ada. Selain itu, penggunaan bobot numerik (`bobot >= 2.0`), rumus irisan interval, dan *eager loading* (`selectinload`) menghindari bug klasik perbandingan string ASCII maupun masalah performa query N+1.
- **Kekurangan / Kompleksitas Tambahan**: Memerlukan persiapan *context object* (`KRSValidationContext`) dengan *eager loading* di awal sebelum data diteruskan ke rantai validator.


## Log 07 — Penyelarasan 4 Tabel Modul KRS (`matakuliah`, `prerequisite`, `krs`, `krs_detail`), Migrasi Alembic, dan `KRSManager`

### Tujuan
Menyelaraskan implementasi modul KRS dengan spesifikasi arsitektur 4 tabel modul KRS (`matakuliah`, `prerequisite`, `krs`, `krs_detail` yang berelasi ke `calon_mahasiswa.nim`), menambahkan migrasi Alembic dengan *CHECK constraint* dan *UniqueConstraint*, menyeragamkan urutan rantai validator menjadi **`Duplicate -> SKS -> Prerequisite -> Conflict`** (dari operasi paling ringan ke paling berat), serta menyediakan layanan satu pintu **`KRSManager`** (`add_course`, `remove_course`, `validate_krs`, `submit_krs`, `approve_krs`) yang hanya mengizinkan perubahan saat kartu berstatus `DRAFT` atau `REVISION`.

### Perintah (Prompt)
Sesuaikan implementasi modul KRS dengan spesifikasi berikut:
1. Buat 4 tabel modul KRS di SQLAlchemy 2.0 (`app/models/krs.py`) dan migrasi Alembic:
   - `matakuliah` (`kode_mk` PK, `nama`, `sks`, `hari` int 1..6, `jam_mulai` Time, `jam_selesai` Time) dengan CHECK `sks BETWEEN 1 AND 4` dan `jam_mulai < jam_selesai`.
   - `prerequisite` (`kode_mk`, `kode_prasyarat` PK gabungan merujuk ke `matakuliah.kode_mk`) dengan CHECK `kode_mk <> kode_prasyarat` dan verifikasi arah join `sd.prasyarat == [algoritma]`.
   - `krs` (`id`, `nim` FK ke `calon_mahasiswa.nim`, `semester`, `status` enum `KRSStatus`: `DRAFT`, `SUBMITTED`, `APPROVED`, `REVISION`, `dosen_pa_id`) dengan `UniqueConstraint("nim", "semester")`.
   - `krs_detail` (`id`, `krs_id` FK ke `krs.id`, `kode_mk` FK ke `matakuliah.kode_mk`, `nilai` nullable) dengan `UniqueConstraint("krs_id", "kode_mk")`.
2. Sesuaikan `Validator`, `ValidationResult(ok: bool, message: str = "")`, `KRSContext`, dan `build_chain()` dengan urutan `DuplicateValidator -> SKSValidator -> PrerequisiteValidator -> ConflictValidator`.
3. Buat `KRSManager` (`app/services/krs_manager.py`) dengan `add_course`, `remove_course` (hanya saat `DRAFT` atau `REVISION`), `validate_krs`, `submit_krs`, dan `approve_krs`.

### Hasil (Hasil Implementasi)
- Pembuatan model SQLAlchemy 2.0 di `backend/app/models/krs.py` (`MataKuliah`, `prerequisite`, `KRSStatus`, `KRS`, `KRSDetail`) dan skrip migrasi Alembic `backend/alembic/versions/8b2104krs005_tabel_krs.py` lengkap dengan `upgrade()`, `downgrade()`, `CheckConstraint`, dan `UniqueConstraint`.
- Pembaruan `backend/app/services/krs_validator.py` dengan `ValidationResult(ok, message)`, `KRSContext(nim, semester, details, mk_baru, db)`, fungsi `prasyarat_belum_lulus()`, `build_chain()`, serta urutan rantai validator **`Duplicate -> SKS -> Prerequisite -> Conflict`**.
- Pembuatan `backend/app/services/krs_manager.py` (`KRSManager` dan `KRSError`) sebagai satu pintu perubahan KRS dengan penguncian transaksi (`with_for_update()`) dan penjagaan state `EDITABLE = {KRSStatus.DRAFT, KRSStatus.REVISION}`.
- Penambahan pengujian integrasi `test_krs_manager_and_matakuliah_self_referential_flow` di `backend/test_models_and_schemas.py` dengan hasil keseluruhan **21 passed** (`pytest`).

### Evaluasi (Objektif)
- **Kelebihan**: Urutan validator `Duplicate -> SKS -> Prerequisite -> Conflict` memastikan pengecekan in-memory paling murah dieksekusi lebih dulu sebelum query database pada `PrerequisiteValidator`. Selain itu, pemisahan tanggung jawab antara `KRSManager` (alur use case & transaksi) dan `Validator` (aturan bisnis murni yang di-inject via constructor) mematuhi *Single Responsibility Principle* dan memudahkan pengujian unit.
- **Kekurangan / Kompleksitas Tambahan**: Penggunaan *self-referential many-to-many* pada `MataKuliah.prasyarat` menuntut ketelitian pada definisi `primaryjoin` dan `secondaryjoin` agar arah relasi prasyarat tidak tertukar.


## Log 08 — Implementasi State Machine KRS (`TRANSITIONS dict[(state, aktor)]` & Method `transition()`)

### Tujuan
Mengimplementasikan *State Machine* KRS sesuai spesifikasi Minggu 06 Step 2 untuk mencegah 4 bug klasik AI: lompatan state ilegal (`DRAFT -> APPROVED`), ketiadaan validasi aktor & kepemilikan `krs.dosen_pa_id`, pengiriman KRS kosong, serta perubahan langsung `krs.status = ...` di luar `transition()`.

### Perintah (Prompt)
"Buat enum KRSStatus dan state transition:
DRAFT -> SUBMITTED (mahasiswa submit)
SUBMITTED -> APPROVED (dosen approve)
SUBMITTED -> REVISION (dosen tolak)
REVISION -> SUBMITTED (mahasiswa perbaiki)
Buat method transition yang enforce aturan state. Tidak boleh DRAFT -> APPROVED langsung."

+ Tambahan prompt:
"Gunakan tabel transisi dict[(state, aktor)].
Approve/revise hanya oleh krs.dosen_pa_id.
Tolak submit jika KRS kosong.
Status hanya boleh diubah lewat transition().
Pesan error bahasa Indonesia, contoh: 'Transisi tidak diizinkan: DRAFT ke APPROVED'.
Sertakan pytest untuk semua transisi ilegal."

### Hasil (Hasil Implementasi)
- Penambahan tabel transisi `TRANSITIONS: dict[tuple[KRSStatus, str], set[KRSStatus]]` dan method `KRS.transition(new_status, actor, dosen_id)` di `backend/app/models/krs.py`.
- Proteksi atribut `KRS.status` menggunakan `@validates("status")` agar penulisan langsung `krs.status = ...` di luar `transition()` otomatis ditolak dengan `StateTransitionError`.
- Penegakan aturan KRS tidak boleh kosong saat menuju `SUBMITTED` serta validasi `dosen_id == self.dosen_pa_id` saat `actor == "dosen"` melakukan `APPROVED` atau `REVISION`.
- Integrasi `submit_krs()`, `approve_krs()`, dan `revise_krs()` pada `KRSManager` (`backend/app/services/krs_manager.py`) agar seluruhnya memanggil `krs.transition(...)`.
- Penambahan unit test parameterisasi untuk seluruh transisi ilegal, KRS kosong, dosen PA berbeda, dan direct assignment di `backend/test_models_and_schemas.py`.

### Evaluasi (Objektif)
- **Kelebihan**: Penggunaan tabel transisi `dict[(state, aktor)]` menggantikan percabangan `if-else` yang rawan bocor, menjamin hanya kombinasi `(state, aktor)` yang terdaftar yang dapat dieksekusi, serta mengunci mutasi status satu pintu melalui `transition()`.
- **Kekurangan / Kompleksitas Tambahan**: Memerlukan penjagaan flag internal (`_allow_status_change`) pada model SQLAlchemy agar inisialisasi objek tetap berjalan normal namun mutasi langsung pasca-inisialisasi diblokir.


## Log 09 — Penyelarasan State Machine KRS (Enum `Actor`, `cek_transisi`, Kepemilikan 403 vs 409, Validasi Submit, Catatan Revisi, & Audit Log)

### Tujuan
Menyelaraskan implementasi State Machine KRS dengan keempat slide materi Minggu 06 (*Status yang tidak bisa dilompati*, *Empat state empat panah*, *Tabel transisi + satu pintu perubahan*, serta *Peran dan kepemilikan*) secara menyeluruh.

### Perintah (Prompt)
Analisis 4 slide materi Minggu 06 dan selaraskan kekurangan berikut pada modul KRS beserta pembaruan `ai-usage-log.md`:
1. Menggunakan Enum `Actor` (`MAHASISWA`, `DOSEN_PA`) pada kunci tabel `TRANSITIONS: dict[tuple[KRSStatus, Actor], set[KRSStatus]]`.
2. Memisahkan pengecekan ke method `cek_transisi()` dan `TransitionError` (dengan alias kompatibilitas `StateTransitionError`).
3. Menegakkan dua lapis keamanan (peran & kepemilikan mahasiswa/dosen PA) dengan pemisahan status HTTP: orang salah $\rightarrow$ `403 Forbidden` (`KRSForbiddenError`), orang benar tapi status salah $\rightarrow$ `409 Conflict` (`TransitionError`).
4. Menjalankan validasi KRS (`validate_krs`) otomatis saat `submit_krs`.
5. Mewajibkan parameter `catatan` saat `revise_krs` dan menyimpannya ke kolom `catatan_revisi`.
6. Mencatat `approved_at` (UTC) dan log (`logging`) saat `approve_krs` (plus migrasi Alembic kolom baru).

### Hasil (Hasil Implementasi)
- Pembaruan `backend/app/models/krs.py` dan `backend/app/models/__init__.py`: penambahan `Actor`, `TransitionError` (409), `KRSForbiddenError` (403), `cek_transisi()`, serta kolom `approved_at` dan `catatan_revisi` pada model `KRS`.
- Pembuatan migrasi Alembic `backend/alembic/versions/9c3205krs006_krs_state_columns.py` dengan `upgrade()` dan `downgrade()` menggunakan `batch_alter_table`.
- Pembaruan `KRSManager` (`backend/app/services/krs_manager.py`): pengecekan kepemilikan mahasiswa (`requester_nim`) dan dosen PA (`dosen_pa_id`), pemanggilan `_validate_krs_obj()` otomatis di `submit_krs()`, parameter wajib `catatan` di `revise_krs()`, serta pencatatan `logger.info` di `submit_krs()`, `approve_krs()`, dan `revise_krs()`.
- Penambahan dan pembaruan unit test di `backend/test_models_and_schemas.py` (termasuk `test_krs_manager_ownership_validation_and_audit_guards` untuk 403 vs 409, validasi sebelum submit, catatan revisi wajib, `approved_at`, dan log audit).

### Evaluasi (Objektif)
- **Kelebihan**: Seluruh mekanisme state machine, pemisahan peran dan kepemilikan (403 vs 409), validasi pra-submit, kewajiban alasan revisi, dan jejak audit persetujuan kini 100% selaras dengan spesifikasi desain Minggu 06 dan teruji otomatis lewat `pytest`.
- **Kekurangan / Kompleksitas Tambahan**: Penambahan kolom `approved_at` dan `catatan_revisi` pada tabel `krs` memerlukan sinkronisasi migrasi Alembic pada database yang sudah ada.


## Log 10 — Penyempurnaan ADR (Tabel Sendiri vs Library), `KRSLockedError`, Unit Kerja ACID (`KRSLog` + `Notifikasi`), dan Optimistic Lock (`version` & `diubah_pada`)

### Tujuan
Menyempurnakan modul KRS dan dokumentasi arsitektur agar 100% selaras dengan keempat slide lanjutan Minggu 06:
1. Mencatat keputusan arsitektur pemilihan tabel transisi state machine sendiri (`dict[(state, aktor)]`) vs library eksternal (`python-statemachine` / `transitions`) di dokumen ADR.
2. Menambahkan `KRSLockedError` (`409 Conflict`), kolom `submitted_at`, serta penggabungan seluruh pesan kegagalan validasi (`"; ".join(...)`) pada `submit_krs`.
3. Menerapkan transaksi ACID satu unit kerja (`try ... commit() / except ... rollback()`) pada `approve_krs` dan `revise_krs` yang menyimpan baris `KRSLog` dan `Notifikasi` ke database.
4. Menerapkan kombinasi *Pessimistic Lock* (`with_for_update()`) dan *Optimistic Lock* (`version_id_col = version` + pembaruan `diubah_pada` saat `add_course` / `remove_course`) untuk menolak layar basi dengan error `409 Conflict` (`"KRS sudah berubah, muat ulang"`).

### Perintah (Prompt)
"Sempurnakan implementasi State Machine dan transaksi pada modul KRS dengan ketentuan berikut:
1. Catat keputusan arsitektur di dokumen ADR mengenai alasan memilih tabel transisi `dict[(state, aktor)]` buatan sendiri dibandingkan library eksternal (`python-statemachine` / `transitions`) dari sisi dependensi, skala 4 state, dan kemudahan penjelasan saat viva.
2. Pada `KRSManager`, tambahkan `KRSLockedError` (status 409) sebagai penjaga di `add_course` dan `remove_course` ketika status KRS bukan `EDITABLE`, catat `submitted_at` saat `submit_krs`, dan gabungkan semua pesan kegagalan validasi (`'; '.join(...)`) sebelum berpindah state.
3. Jadikan `approve_krs` dan `revise_krs` sebagai satu unit kerja transaksi ACID (`try ... commit() / except ... rollback()`) yang menyimpan riwayat `KRSLog` dan baris `Notifikasi` ke database dalam transaksi yang sama.
4. Cegah race condition dan layar basi ketika dosen menyetujui saat mahasiswa masih mengedit dengan mengombinasikan Pessimistic Lock (`with_for_update()`) dan Optimistic Lock (`version` dengan `version_id_col` pada `KRS`, serta sentuh `diubah_pada` saat `add_course`/`remove_course` agar nomor versi selalu naik dan tolak versi lama dengan error 409 'KRS sudah berubah, muat ulang')."

### Hasil (Hasil Implementasi)
- Pembaruan `repo-structure/docs/ADR-architecture-decisions.md` dengan penambahan sub-bab **3.12 (State Machine KRS: Tabel Transisi Sendiri vs Library Eksternal)**, sub-bab **3.13 (Unit Kerja Transaksi ACID & Strategi Penguncian Ganda)**, serta analisis trade-off ke-7.
- Pembaruan `backend/app/models/krs.py` dan `backend/app/models/__init__.py`: penambahan `KRSLockedError` (409), alias `ForbiddenError`, kolom `submitted_at`, `version` (`version_id_col`), dan `diubah_pada` pada model `KRS`, serta model `KRSLog` dan `Notifikasi`.
- Pembaruan `backend/app/services/krs_manager.py`: penggunaan `KRSLockedError` pada `add_course`/`remove_course`, pembaruan `krs.diubah_pada` agar `version` naik saat detail berubah, penggabungan pesan gagal di `submit_krs`, blok transaksi ACID (`try/except rollback`) beserta penyimpanan `KRSLog` & `Notifikasi` pada `approve_krs` dan `revise_krs`, serta pengecekan versi layar basi (`409`).
- Pembaruan migrasi Alembic `backend/alembic/versions/9c3205krs006_krs_state_columns.py` dan penambahan unit test `test_krs_locked_error_acid_log_notifikasi_and_optimistic_version_lock` di `backend/test_models_and_schemas.py`.

### Evaluasi (Objektif)
- **Kelebihan**: Sistem KRS kini tahan terhadap *race condition* maupun kondisi layar basi berkat kombinasi *Pessimistic Lock* (`FOR UPDATE`) dan *Optimistic Lock* (`version`), menjamin atomisitas data audit (`KRSLog`) dan `Notifikasi` melalui prinsip ACID, serta memiliki justifikasi arsitektur yang lengkap di ADR untuk persiapan viva.
- **Kekurangan / Kompleksitas Tambahan**: Penambahan tabel `krs_log` dan `notifikasi` serta kolom `version` menuntut pengelolaan transaksi (`commit` / `rollback`) yang konsisten di seluruh method `KRSManager`.


## Log 11 — Implementasi Router API KRS, Exception Handler FastAPI, Property-Based Testing (Hypothesis), Challenge CSP Recommender, PR Template, & OPAR

### Tujuan
Melengkapi lapisan API HTTP FastAPI untuk modul KRS beserta *exception handler* global, menguji piramida pengujian secara utuh (Unit, Integration, API `TestClient`, dan *Property-Based Testing* menggunakan `hypothesis`), menambahkan fitur *KRS Recommendation* berbasis *Constraint Satisfaction Problem* (CSP *backtracking*) dengan verifikasi rantai validator, serta mendokumentasikan PR Template dan refleksi **OPAR** (*Observe, Plan, Act, Reflect*).

### Perintah (Prompt)
"Lengkapi modul KRS backend dengan lapisan API FastAPI, piramida pengujian, dan dokumentasi PR sebagai berikut:
1. Buat router `/api/krs/{nim}/...` (POST `/courses`, DELETE `/courses/{kode_mk}`, POST `/submit`, POST `/approve`, POST `/revise`) lengkap dengan skema Pydantic dan `@app.exception_handler(KRSError)` agar status 400/403/409/422 dan pesan bahasa Indonesia keluar konsisten.
2. Buat suite *property-based testing* menggunakan `hypothesis` untuk menguji langsung `SKSValidator` (total SKS diterima <= 24 pada 1000 contoh acak), `ConflictValidator` (tidak ada irisan jadwal pada 1000 contoh acak), dan seluruh 28 kombinasi transisi ilegal dari `itertools.product(KRSStatus, KRSStatus, Actor)` tanpa menyentuh DB.
3. Buat API integration test via FastAPI `TestClient` yang memverifikasi error pesan prasyarat, jadwal bentrok, kode 400/403/409/422, optimistic lock versi basi, dan `KRSLockedError`.
4. Tambahkan modul rekomendasi jadwal KRS bebas bentrok berbasis CSP *backtracking* (`recommend_krs_csp`) yang memprioritaskan MK wajib di atas pilihan dan memvalidasi hasil akhirnya melalui `default_validators()`, serta siapkan `.github/PULL_REQUEST_TEMPLATE.md` dan refleksi OPAR."

### Hasil (Hasil Implementasi)
- Pembaruan `backend/requirements.txt` (penambahan `hypothesis>=6.100.0`) dan penyelarasan format pesan di `backend/app/services/krs_validator.py` (`"Prasyarat tidak terpenuhi: ..."` dan `"Jadwal bentrok: ..."`).
- Pembuatan modul CSP solver `backend/app/services/krs_recommender.py` (`CourseOffering`, `RecommendationResult`, `recommend_krs_csp`) yang memprioritaskan mata kuliah wajib di depan mata kuliah pilihan, mendukung kelas paralel, serta selalu menjalankan guardrail rantai `default_validators()` sebelum mengembalikan hasil.
- Pembaruan `backend/app/schemas/krs.py` (`AddCourseRequest`, `ApproveKRSRequest`, `ReviseKRSRequest`, `CourseOfferingInput`, `RecommendKRSRequest`, `KRSActionResponse`, `KRSRecommendationResponse`), pembuatan router `backend/app/routers/krs.py` (menggunakan SQLAlchemy `Session` dari `app.core.database.get_db`), dan pendaftaran `@app.exception_handler(KRSError)` serta router `/api/krs` di `backend/app/main.py`.
- Pembuatan `backend/tests/test_krs_property.py` (32 kasus test: `test_total_sks_tidak_pernah_lebih_dari_24` 1000 contoh, `test_mk_diterima_tidak_pernah_bentrok` 1000 contoh, `test_jumlah_kombinasi_transisi_ilegal_adalah_28`, 28 kasus `test_transisi_ilegal_ditolak`, serta 200 contoh properti `test_recommender_csp_properti_bebas_bentrok_dan_sks_valid`).
- Pembuatan `backend/tests/test_krs_api.py` (6 API test via `TestClient` dengan SQLite in-memory `StaticPool`).
- Pembuatan `.github/PULL_REQUEST_TEMPLATE.md` dan eksekusi seluruh test suite: **72 passed** (`test_models_and_schemas.py` + `test_krs_property.py`) dan **14 passed** (`test_pmb.py` + `test_krs_api.py`), total **86 passed**.

### OPAR (Observe – Plan – Act – Reflect)
- **Observe**: Masih terdapat celah potensi MK baru masuk ke kartu KRS `SUBMITTED`/`APPROVED` melalui tab lain (*race condition*), belum adanya pembuktian otomatis atas properti invarian sistem pada kombinasi acak tak terduga (SKS > 24, bentrok jadwal, 28 transisi ilegal), serta belum terujinya kode status HTTP (`400`/`403`/`409`/`422`) di lapisan API FastAPI.
- **Plan**: Mengunci baris `krs` di seluruh method (`with_for_update()`), menambahkan *optimistic lock* (`version_id_col` + pembaruan `diubah_pada`), menyediakan endpoint `/api/krs/{nim}/...` dengan `@app.exception_handler(KRSError)`, membuktikan properti sistem via `hypothesis` (2×1000 contoh acak + 28 transisi ilegal + 200 contoh CSP) dan `TestClient`, serta mencatat limitasi secara jujur di PR Template.
- **Act**: Mengimplementasikan penyempurnaan di `krs.py`, `krs_manager.py`, `krs_validator.py`, `krs_recommender.py`, `schemas/krs.py`, `routers/krs.py`, `main.py`, `tests/test_krs_property.py`, `tests/test_krs_api.py`, dan `.github/PULL_REQUEST_TEMPLATE.md`.
- **Reflect**: SQLite tidak membuktikan *concurrent row-level lock* `FOR UPDATE` secara penuh seperti pada database server, sehingga verifikasi konkurensi lintas sesi tetap perlu diuji pada PostgreSQL/MySQL; selain itu, parameter `dosen_pa_id` pada endpoint `/approve` dan `/revise` saat ini masih dikirim melalui *request body* karena integrasi autentikasi JWT belum dihubungkan langsung ke router KRS.

### Evaluasi (Objektif)
- **Kelebihan**: Seluruh lapisan piramida pengujian (unit, integrasi `KRSManager`, properti `hypothesis`, dan API `TestClient`) terverifikasi lulus penuh (total **86 passed**), pesan error HTTP terstandarisasi lewat satu *exception handler*, dan fitur rekomendasi CSP tetap tunduk pada guardrail `default_validators()`.
- **Kekurangan / Kompleksitas Tambahan**: Otorisasi berbasis token JWT untuk mengidentifikasi `dosen_pa_id` secara otomatis dari sesi login masih perlu ditambahkan pada iterasi integrasi autentikasi berikutnya.







