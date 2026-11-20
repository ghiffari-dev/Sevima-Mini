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


## Log 12 — Modul Jadwal & Ruangan (Minggu 7–8): Interval Tree, Observer Pattern, Hybrid AI Rescheduler, Conflict Resolver UI, & Invalidasi KRS

### Tujuan
Mengimplementasikan seluruh kebutuhan **Minggu 7–8: Modul Jadwal & Ruangan** pada branch `tugas-7`, mencakup layanan penjadwalan & deteksi bentrok 3 dimensi berbasis *Interval Tree*, notifikasi berbasis *Observer Pattern*, antarmuka admin *Conflict Resolver UI* dengan saran alternatif AI (*hybrid*), serta sinkronisasi otomatis yang menginvalidasi KRS terdampak ke status `REVISION`.

### Perintah (Prompt)
"Implementasikan Modul Jadwal & Ruangan (Minggu 7–8) yang terintegrasi dengan modul KRS:
1. Scheduling Service: CRUD jadwal + ruangan (`Ruangan`, `JadwalKuliah` + migrasi Alembic), algoritma `detect_schedule_conflict()` menggunakan *Interval Tree* untuk mendeteksi `room_conflict`, `lecturer_conflict`, dan `time_overlap`, serta validasi kapasitas ruangan (`enrolled <= kapasitas`).
2. Observer Pattern: `ScheduleSubject` dan `NotificationManager` dengan `StudentObserver`, `LecturerObserver`, dan `AdminObserver` menggunakan simulasi Email/SMS/Push via log.
3. Conflict Resolver UI & Hybrid AI Rescheduler: halaman web `/dashboard/conflicts` beserta endpoint `/api/schedules/{id}/suggest-alternatives` yang menghasilkan 3 opsi jadwal pengganti (`[{hari, jam, ruangan, reason}]`) melalui LLM API (jika tersedia di `.env`) dengan *guardrail* deterministik dan *fallback* algoritmik lokal.
4. Integrasi KRS: setiap perubahan/penghapusan jadwal otomatis memindahkan KRS terdampak ke status `REVISION` (`invalidate_by_schedule_change`) beserta pencatatan `KRSLog` dan `Notifikasi` dalam satu transaksi ACID tanpa mematahkan test state machine sebelumnya.
5. Testing & Dokumentasi: buat `backend/tests/test_schedule.py`, sequence diagram Observer Pattern (`repo-structure/diagrams/sequence-schedule-observer.mmd`), serta perbarui ADR dan README."

### Hasil (Hasil Implementasi)
- Pembaruan `backend/app/core/config.py` untuk dukungan opsional `GEMINI_API_KEY`, `OPENAI_API_KEY`, dan `AI_MODEL` di `.env`.
- Pembuatan model SQLAlchemy `Ruangan` & `JadwalKuliah` (`backend/app/models/schedule.py`), ekspor di `backend/app/models/__init__.py`, dan migrasi Alembic `backend/alembic/versions/a1b2c3sch007_tabel_jadwal_ruangan.py`.
- Pembaruan `backend/app/models/krs.py` dengan method `KRS.invalidate_by_schedule_change()` yang menjaga `@validates("status")` dan 28 kombinasi transisi ilegal tetap utuh.
- Pembuatan `backend/app/services/interval_tree.py` (`IntervalTree`, `to_minutes`) dan `backend/app/services/conflict_detector.py` (`detect_schedule_conflict`, `check_room_capacity`).
- Pembuatan `backend/app/services/schedule_observer.py` (`ScheduleSubject`, `NotificationManager`, `StudentObserver`, `LecturerObserver`, `AdminObserver`).
- Pembuatan `backend/app/services/schedule_recommender.py` (`suggest_alternative_schedules` hybrid AI + *guardrail* + *rule-based fallback*) dan `backend/app/services/scheduling_service.py` (CRUD, invalidasi KRS ACID, & seeder demo).
- Pembuatan skema `backend/app/schemas/schedule.py`, router `backend/app/routers/schedule.py`, halaman UI `backend/app/static/conflict_resolver.html`, dan integrasi di `backend/app/main.py` (`/api/schedules` & `/dashboard/conflicts`).
- Pembuatan suite pengujian `backend/tests/test_schedule.py` serta diagram sekuens `repo-structure/diagrams/sequence-schedule-observer.mmd` dan pembaruan ADR (`3.14`–`3.17`).
- Verifikasi migrasi Alembic (`a1b2c3sch007 (head)`) pada `backend/pmb.db` maupun pengujian *upgrade/downgrade/re-upgrade* terisolasi, serta eksekusi seluruh test suite (`pytest`) dengan hasil **95 passed** (**72 passed** pada `test_models_and_schemas.py` + `test_krs_property.py` dan **23 passed** pada `test_pmb.py` + `test_krs_api.py` + `test_schedule.py`).

### OPAR (Observe – Plan – Act – Reflect)
- **Observe**: Modul KRS sebelumnya menyimpan waktu langsung pada `MataKuliah` tanpa entitas `Ruangan`/`Dosen`/`Kapasitas`, sementara `KRSStatus` dan `Actor` diuji ketat oleh `test_krs_property.py` (28 kombinasi ilegal) sehingga menambah enum baru akan merusak invarian lama.
- **Plan**: Membuat tabel `ruangan` dan `jadwal_kuliah` yang tertaut ke `matakuliah.kode_mk` (sekaligus menyinkronkan jam `MataKuliah` untuk validator KRS), menambah `KRS.invalidate_by_schedule_change()` khusus ke status `REVISION`, membangun *Interval Tree*, *Observer Pattern*, *Hybrid AI Rescheduler*, dan dashboard HTML mandiri di FastAPI.
- **Act**: Mengimplementasikan seluruh modul layanan, migrasi, router, UI admin, test suite (`test_schedule.py`), sequence diagram Observer, dan ADR 3.14–3.17.
- **Reflect**: Simulasi notifikasi Email/SMS/Push dan penyimpanan log riwayat di `NotificationManager` saat ini berjalan di memori dan `logging`; untuk produksi perlu diintegrasikan ke message broker/SMTP/gateway serta tabel log notifikasi permanen bila dibutuhkan riwayat lintas restart server.

### Evaluasi (Objektif)
- **Kelebihan**: Deteksi bentrok 3D berjalan deterministik via *Interval Tree*, notifikasi multi-stakeholder terdekupel rapi lewat *Observer Pattern*, saran penjadwalan ulang tetap aman berkat *guardrail* anti-halusinasi, dan integrasi invalidasi KRS ke `REVISION` bersifat atomik (ACID) tanpa merusak 86 test sebelumnya.
- **Kekurangan / Kompleksitas Tambahan**: Penambahan tabel `ruangan` dan `jadwal_kuliah` mengharuskan `alembic upgrade head` dijalankan pada database yang sudah ada sebelum memakai endpoint `/api/schedules`.


## Log 13 — Penyelarasan Penuh Modul Jadwal & Ruang Minggu ke-7 (4 Model Domain, Grouping + Sort & Sweep, Locking Pesimis, & Pengujian Properti)

### Tujuan
Menyelaraskan implementasi modul Jadwal & Ruangan dengan seluruh spesifikasi kuliah OOP Minggu ke-7 sambil tetap mempertahankan fitur Minggu ke-8 (*Observer Pattern*, *Hybrid AI Rescheduler*, *Conflict Resolver UI*, dan invalidasi KRS ke `REVISION`), meliputi:
1. Pemodelan 4 entitas domain (`Ruangan`, `Dosen` dengan NIDN unik, `Kelas` paralel dengan kuota/semester, `Jadwal` dengan indeks gabungan `(hari, ruangan_kode)` dan `(hari, dosen_id)`), penghapusan kolom jam dari `MataKuliah`, serta penambahan `KRSDetail.kelas_id` melalui migrasi Alembic `b2c3d4sch008`.
2. Detektor bentrok dua versi: **Versi Naive** (`itertools.combinations`) sebagai *oracle* dan **Versi Grouping + Sort & Sweep** dengan `@dataclass(frozen=True) class Conflict` (`room_conflict` & `lecturer_conflict` saja), serta penundaan *Interval Tree* berdasar pengukuran skala kampus di ADR.
3. Penyatuan alur `create_schedule` dan `update_schedule` di `SchedulingService._simpan()`, penguncian pesimis `with_for_update()` berurutan (`Ruangan -> Dosen`), query bentrok langsung di SQL, *capacity check* `max(kuota, terdaftar) <= kapasitas` dengan status `409 Conflict`, validasi Pydantic (`datetime.time`, `jam_mulai < jam_selesai` → `422`), dan polimorfisme `ScheduleError.body()`.
4. Pengujian contoh berparameter (`@pytest.mark.parametrize`) atas 5 bug klasik AI, 2 properti `Hypothesis` (*schedule-free invariant* via slot 1 jam + `Counter`, dan *differential testing* `Counter(sweep) == Counter(naive)`), serta pembaruan ADR dan dokumentasi.

### Perintah (Prompt) & Perbandingan Dua Model AI
Prompt kunci yang diuji pada dua model (*Gemini Flash* via Google AI Studio vs pembanding model di OpenRouter) untuk fungsi deteksi bentrok:
> "Buat fungsi `detect_schedule_conflict(schedules)` pada proyek Python + SQLAlchemy 2.0 menggunakan model `Ruangan`, `Dosen`, `Kelas`, dan `Jadwal`. Gunakan interval setengah terbuka `[jam_mulai, jam_selesai)` bertipe `datetime.time` (kuliah bersambung mis. 08:00–09:40 dan 09:40–11:20 tidak bentrok), kembalikan `@dataclass(frozen=True) class Conflict(type, affected)` hanya untuk tipe `room_conflict` dan `lecturer_conflict` (setiap pasangan dilaporkan sekali per tipe). Sediakan versi naif sebagai acuan serta versi teroptimasi Grouping + Sort & Sweep beserta bukti kesamaan keduanya di pytest."

**Ringkasan Perbandingan Output Model:**
- **Gemini Flash (Google AI Studio):** Menghasilkan struktur `@dataclass(frozen=True)` dan fungsi `detect_conflicts_sweep` yang ringkas, namun pada percobaan awal sempat menyisipkan pengecekan `<=` pada batas akhir aktif di sweep loop dan menduplikasi pasangan `(A, B)`/`(B, A)` pada versi naif sebelum diarahkan memakai `itertools.combinations`.
- **Model Pembanding (OpenRouter):** Menghasilkan `itertools.combinations` yang tepat pada versi naif, namun sempat melaporkan tipe tambahan `time_overlap` dan memakai tipe `str` pada input jam sebelum diwajibkan memakai `datetime.time` dan `Literal["room_conflict", "lecturer_conflict"]`.

### Revisi Manual atas 5 Bug Klasik AI
1. **Operator batas interval (`<=` → `<` / `>`):** Memastikan kondisi irisan memakai `a.jam_mulai < b.jam_selesai and b.jam_mulai < a.jam_selesai` dan pembersihan daftar aktif memakai `a.jam_selesai > cur.jam_mulai` agar kuliah bersambung tepat pukul `09:40` tidak ditolak.
2. **Tipe jam (`str` → `datetime.time`):** Memakai kolom SQLAlchemy `Time` dan skema Pydantic `datetime.time` (plus `@model_validator` yang melempar `422` bila `jam_mulai >= jam_selesai`) sehingga kasus `"9:00"` vs `"10:00"` tidak salah dibandingkan secara leksikografis.
3. **Pemeriksaan hari:** Memastikan pengelompokan dan query SQL memfilter `hari` secara eksplisit agar Senin pagi dan Rabu pagi di ruangan sama tidak dilaporkan bentrok.
4. **Duplikasi pasangan (`(A, B)` vs `(B, A)`):** Versi naif memakai `itertools.combinations(..., 2)` dan helper `pasangan(a, b)` mengurutkan ID sehingga setiap pasangan hanya muncul satu kali per tipe.
5. **Penamaan tipe konflik & status HTTP:** Menghapus tipe `time_overlap` pada detektor penjadwalan (hanya `room_conflict` dan `lecturer_conflict`), mengubah `ScheduleCapacityError` menjadi `409 Conflict`, serta mengganti percabangan handler menjadi polimorfisme `exc.body()`.

### OPAR (Observe – Plan – Act – Reflect)
- **Observe:** Pada implementasi awal Minggu 7–8, entitas masih terbatas pada `Ruangan(kode_ruangan)` dan `JadwalKuliah` (tanpa tabel `Dosen` & `Kelas` paralel), `MataKuliah` masih menyimpan kolom `hari`/`jam_mulai`/`jam_selesai`, belum ada indeks gabungan `(hari, ruangan_kode)` & `(hari, dosen_id)`, pencarian bentrok menarik seluruh data ke memori Python tanpa *row locking* (`with_for_update()`)—sehingga bila dua admin menyimpan jadwal di ruang dan jam sama secara bersamaan, keduanya lolos pengecekan bentrok sebelum komit—serta error kapasitas masih `400` dan detektor langsung memakai *Interval Tree* tanpa *Naive oracle* & pengukuran benchmark.
- **Plan:** Memecah domain ke 4 model (`Ruangan`, `Dosen`, `Kelas`, `Jadwal`) + migrasi Alembic `b2c3d4sch008`, menghapus *Interval Tree* dan beralih ke `Naive` + `Grouping + Sort & Sweep` (disertai benchmark 600 jadwal untuk ADR), menyatukan `create_schedule` & `update_schedule` ke `_simpan()` dengan penguncian pesimis `_kunci()` urutan tetap `Ruangan -> Dosen`, mengecek bentrok langsung di SQL memakai indeks gabungan sebelum `db.add()`, menetapkan kapasitas `409` & validasi Pydantic `422`, serta melengkapi tes `@pytest.mark.parametrize` + 2 properti `Hypothesis`.
- **Act:** Merefaktor `models/schedule.py`, `models/krs.py`, `models/__init__.py` (beserta full path relasi di `user.py`, `course.py`, `enrollment.py`, `pendaftaran.py`), membuat migrasi `b2c3d4sch008`, mengganti `interval_tree.py` dengan `conflict_detector.py` versi `Naive` & `Sort & Sweep`, memperbarui `scheduling_service.py`, `schedule_recommender.py`, integrasi KRS (`krs_validator.py`, `krs_manager.py`, `krs_recommender.py`, `routers/krs.py`), `schemas/schedule.py`, `routers/schedule.py`, `main.py`, `conflict_resolver.html`, serta memperbarui `test_models_and_schemas.py`, `test_krs_api.py`, dan `test_schedule.py`. Menjalankan benchmark 600 jadwal (*tersebar*: `Naive 5,22 ms` vs `Sort & Sweep 0,60 ms`; *padat*: `Naive 7,80 ms` vs `Sort & Sweep 4,53 ms`), menguji migrasi Alembic `upgrade -> downgrade -> upgrade` terisolasi serta `alembic upgrade head` pada `backend/pmb.db`, dan menjalankan seluruh 5 file uji dengan hasil **104 passed** (`72 passed` pada `test_models_and_schemas.py` + `test_krs_property.py` dan `32 passed` pada `test_pmb.py` + `test_krs_api.py` + `test_schedule.py`).
- **Reflect:** Pengujian konkurensi pada SQLite tidak membuktikan penguncian baris `SELECT ... FOR UPDATE` yang sesungguhnya karena dialek SQLite SQLAlchemy mengabaikan klausa `FOR UPDATE` saat kompilasi SQL; oleh karena itu, pembuktian perilaku penguncian pesimis dua transaksi paralel harus dilakukan di MySQL atau PostgreSQL, sedangkan di suite tes diverifikasi melalui spy pemanggilan `.with_for_update()` (kompilasi dialek MySQL) serta urutan eksekusi query (`Ruangan -> Dosen -> Cek Bentrok SQL`). Selain itu, keputusan menunda *Interval Tree* dicatat lengkap beserta angka benchmark di ADR-001, dan pengecekan kapasitas saat mahasiswa menambah kelas di `KRSManager` serta filter semester aktif dicatat sebagai limitasi di PR Template.

### Evaluasi (Objektif)
- **Kelebihan:** Skema 4 model domain kini mendukung kelas paralel dan multi-pertemuan per minggu, *Grouping + Sort & Sweep* berjalan sub-milidetik (`0,60 ms` untuk 600 jadwal) dan terbukti identik dengan versi *Naive* pada ratusan contoh acak `Hypothesis`, serta `SchedulingService._simpan()` aman dari *autoflush* prematur dan siap terhadap penguncian pesimis pada MySQL/PostgreSQL.
- **Kekurangan / Kompleksitas Tambahan:** Pemisahan jadwal dari `MataKuliah` memerlukan migrasi skema `b2c3d4sch008` dan penyesuaian fixture uji KRS agar tiap mata kuliah di database memiliki baris `Kelas` dan `Jadwal`.


## Log 14 — Penyelarasan Penuh Modul Jadwal & Ruangan Minggu ke-8 (Observer `Protocol`, Transactional Outbox, `Actor.SYSTEM`, `LLMClient` + 4 Saringan, RBAC Admin, & Ekspor iCalendar `.ics`)

### Tujuan
Menyelaraskan seluruh implementasi Modul Jadwal & Ruangan di branch `tugas-8` terhadap spesifikasi kuliah PBO Minggu ke-8:
1. **Observer Pattern & Strategy Channel:** Menggunakan `typing.Protocol` (`ScheduleObserver`, `NotificationChannel`, `ParticipantRepository`), `EventType` enum (`SCHEDULE_CHANGED`, `SCHEDULE_DELETED`), `@dataclass(frozen=True) ScheduleEvent` dengan `event_id` unik + `before`/`after`, serta `LogChannel` dengan *idempotency key* (`f"{event_id}:{recipient}:{medium}"`).
2. **Transactional Outbox & `OutboxDispatcher`:** Menambah tabel `outbox` dan kolom `jadwal.sequence` lewat migrasi Alembic `c3d4e5sch009`, menulis event ke `outbox` dalam satu transaksi bersama perubahan jadwal & invalidasi KRS, lalu mengirimkannya **setelah komit** memakai `FOR UPDATE SKIP LOCKED`, isolasi `try/except` per observer, dan retry maksimal 5× sebelum berstatus `failed`.
3. **Integrasi KRS Satu Pintu (`Actor.SYSTEM`):** Memindahkan logika invalidasi KRS (`SUBMITTED`/`APPROVED` $\rightarrow$ `REVISION`, membiarkan `DRAFT`/`REVISION` utuh) melalui `KRS.transition(..., actor=Actor.SYSTEM)` dan memperbarui uji parametrisasi menjadi **48 kombinasi** (**6 sah**, **42 ilegal**).
4. **AI Rescheduler (`LLMClient` + 4 Saringan) & Conflict Resolver UI + RBAC:** Membungkus LLM di balik interface `LLMClient.complete()` (`GeminiLLMClient` dengan JSON mode, `OpenRouterLLMClient`, `OpenAILLMClient`, `FakeLLMClient`), menerapkan 4 saringan ketat (parsing `[`..`]`, validasi Pydantic `AISuggestionItem`, cek eksistensi & kapasitas ruang DB, serta uji ulang `detect_conflicts_sweep` memakai calon ID `-1`), memasang RBAC JWT `require_admin_akademik` + `POST /api/auth/login`, serta memperbarui UI `/dashboard/conflicts` (bilah login admin, panel Outbox, fix tampilan `ruangan_kode`, dan pesan konflik `409`).
5. **Ekspor Kalender iCalendar (`.ics`):** Endpoint `GET /api/schedules/export.ics` (mendukung filter `?semester=` & `?nim=`) sesuai RFC 5545 (`CRLF` `\r\n`, `UID` stabil, `DTSTART`/`DTEND` `Asia/Jakarta`, `RRULE:FREQ=WEEKLY;UNTIL=...Z`, dan kenaikan `SEQUENCE` saat jadwal berubah).
6. **Diagram, ADR, & 4 Tes Utama Minggu 8:** Memperbarui `sequence-schedule-observer.mmd`, `ADR-architecture-decisions.md` (`3.15`–`3.19` & trade-off `9`, `12`–`14`), dan menambahkan 4 tes inti + tes RBAC + tes `.ics` di `backend/tests/test_schedule.py`.

### Perintah (Prompt)
> "Sempurnakan implementasi Observer Pattern, Transactional Outbox, integrasi KRS, AI Rescheduler, RBAC Admin, dan Ekspor `.ics` untuk Modul Jadwal & Ruangan Minggu ke-8 dengan 4 syarat anti-bug Observer dan 4 saringan AI:
> - **4 Syarat Observer & Outbox:** (1) Notifikasi hanya dikirim **setelah `commit()`** lewat tabel `outbox` + `OutboxDispatcher` (`FOR UPDATE SKIP LOCKED`, retry maks. 5× lalu `failed`), (2) setiap pemanggilan `observer.update()` dibungkus `try/except` tersendiri dan melaporkan nama observer gagal, (3) `NotificationManager` dirangkai **sekali saat aplikasi start** (bukan di dalam endpoint request), dan (4) setiap pengiriman pada `LogChannel` memiliki **kunci idempotensi** `event_id:recipient:channel` agar pengulangan tidak mengirim pesan ganda.
> - **KRS `Actor.SYSTEM`:** Jalankan invalidasi `SUBMITTED`/`APPROVED -> REVISION` lewat satu pintu `KRS.transition()` dan perbarui uji state machine menjadi 48 kombinasi (6 sah, 42 ilegal).
> - **4 Saringan Saran AI (`LLMClient.complete()`):** Hitung slot tersedia secara deterministik di kode, lalu saring keluaran LLM lewat (1) ekstraksi `[`..`]` yang mengembalikan `[]` bila JSON rusak, (2) validasi skema Pydantic per item (`AISuggestionItem`), (3) cek ruangan ada di DB & `kapasitas >= enrolled`, dan (4) uji bentrok ulang dengan calon `id = -1` di `detect_conflicts_sweep()`.
> - **RBAC, `.ics`, & Dokumentasi:** Lindungi endpoint manajemen jadwal dengan JWT `require_admin_akademik`, sediakan `GET /api/schedules/export.ics` RFC 5545 (`CRLF`, `UID`, `RRULE UNTIL` UTC, `SEQUENCE`), serta perbarui `sequence-schedule-observer.mmd`, ADR-001, dan log ini."

### Hasil (Hasil Implementasi)
- **Model & Migrasi (`c3d4e5sch009`):** Menambahkan `Jadwal.sequence`, `OutboxStatus`, dan `Outbox` (`from_event()`, `to_event()`) di `backend/app/models/schedule.py`, mengekspornya di `backend/app/models/__init__.py`, serta membuat migrasi `backend/alembic/versions/c3d4e5sch009_outbox_dan_sequence_jadwal.py`.
- **State Machine KRS (`Actor.SYSTEM`):** Memperbarui `Actor`, `TRANSITIONS`, `KRS.transition()`, dan `KRS.invalidate_by_schedule_change()` di `backend/app/models/krs.py`; memperbarui `backend/tests/test_krs_property.py` menjadi **6 sah / 42 ilegal** (`48` kombinasi).
- **Observer, Channel, & OutboxDispatcher:** Merefaktor `backend/app/services/schedule_observer.py` (`EventType`, frozen `ScheduleEvent`, `ScheduleObserver` `Protocol`, `NotificationChannel` `Protocol`, `LogChannel` dengan kunci idempotensi, `ParticipantRepository`, `SQLAlchemyParticipantRepository`, `NotifyReport`, isolasi `try/except` di `ScheduleSubject.notify()`, dan `OutboxDispatcher`).
- **Scheduling Service & Recommender:** Memperbarui `backend/app/services/scheduling_service.py` (penulisan `Outbox` satu transaksi sebelum `commit()`, eksekusi `OutboxDispatcher` setelah `commit()`, `Actor.SYSTEM` hanya untuk `SUBMITTED`/`APPROVED`, kenaikan `jadwal.sequence`, dan seeding akun demo Admin Akademik), serta merefaktor `backend/app/services/schedule_recommender.py` (`LLMClient`, `GeminiLLMClient`, `OpenRouterLLMClient`, `OpenAILLMClient`, `FakeLLMClient`, `AISuggestionItem`, `filter_ai_suggestions()`, dan `recommend_with_llm()`).
- **iCalendar, RBAC, & Dashboard UI:** Menambahkan `backend/app/services/calendar_exporter.py` (`export_schedules_to_ics`), `decode_access_token` & `require_admin_akademik` di `backend/app/core/security.py`, `backend/app/routers/auth.py` (`POST /api/auth/login`), memperbarui `backend/app/core/config.py`, `backend/app/main.py`, `backend/app/schemas/schedule.py`, `backend/app/routers/schedule.py` (`/export.ics`, `/outbox`, `/outbox/dispatch`, RBAC admin), dan `backend/app/static/conflict_resolver.html`.
- **Diagram & ADR:** Memperbarui `repo-structure/diagrams/sequence-schedule-observer.mmd` (mencantumkan `COMMIT` sebelum `OutboxDispatcher`, `loop` observer dengan `try/except`, dan cabang status `sent`/`failed`) serta `repo-structure/docs/ADR-architecture-decisions.md` (`3.15`–`3.19` dan trade-off `9`, `12`–`14`).
- **Verifikasi Migrasi & Test Suite:**
  - Uji siklus migrasi Alembic `upgrade head -> downgrade b2c3d4sch008 -> upgrade head` pada salinan SQLite terisolasi berhasil (`ISOLATED_OK True True`), dan `backend/pmb.db` berada di revisi `c3d4e5sch009 (head)`.
  - Suite unit & properti (`backend/test_models_and_schemas.py` + `backend/tests/test_krs_property.py`): **88 passed**.
  - Suite API & penjadwalan (`backend/test_pmb.py` + `backend/tests/test_krs_api.py` + `backend/tests/test_schedule.py`): **38 passed** (mencakup 4 tes inti Minggu 8, tes RBAC, dan tes `.ics`).
  - **Total keseluruhan:** **126 passed, 0 failed**.

### OPAR (Observe – Plan – Act – Reflect)
- **Observe:** Implementasi awal Minggu ke-8 pada branch `tugas-7` sudah memiliki `ScheduleSubject`, 3 observer, dan fallback AI, namun belum memiliki tabel `outbox`, isolasi `try/except` per observer, objek kanal dengan *idempotency key*, `Actor.SYSTEM` di `TRANSITIONS` (masih bypass `transition()`), interface `LLMClient` + validasi Pydantic per item, RBAC Admin Akademik pada router `/api/schedules`, serta ekspor iCalendar `.ics`.
- **Plan:** Menambahkan migrasi `c3d4e5sch009` (`outbox` + `jadwal.sequence`), memindahkan invalidasi KRS ke `Actor.SYSTEM` via `transition()`, merefaktor `schedule_observer.py` ke `typing.Protocol` + `LogChannel` + `OutboxDispatcher`, membungkus LLM dengan `LLMClient` + 4 saringan ketat, membuat `calendar_exporter.py`, memasang JWT RBAC Admin Akademik & `POST /api/auth/login`, memperbarui UI & Sequence Diagram & ADR, lalu memverifikasi seluruh migrasi dan 5 file uji.
- **Act:** Mengimplementasikan seluruh perubahan di model, migrasi, layanan, router, UI, diagram, ADR, dan suite pengujian. Satu bug minor pada test `SelfDetachingObserver` (`subject` vs `subject2`) langsung diperbaiki sebelum verifikasi akhir **88 passed + 38 passed (126 passed)** dan verifikasi migrasi `c3d4e5sch009 (head)`.
- **Reflect:** Klausa `FOR UPDATE SKIP LOCKED` pada `OutboxDispatcher` di SQLite hanya diabaikan saat runtime sehingga perilaku SQL-nya diverifikasi lewat kompilasi dialek PostgreSQL (`for update skip locked`); pengujian konkurensi multi-worker nyata tetap perlu diverifikasi pada PostgreSQL/MySQL. Selain itu, `LogChannel` masih menyimpan `_sent_keys` di memori untuk simulasi log sehingga pada sistem terdistribusi kelak perlu dipindahkan ke penyimpanan bersama (mis. tabel dedup DB atau Redis).

### Evaluasi (Objektif)
- **Kelebihan:** Arsitektur kini tahan terhadap *crash* setelah komit (*Transactional Outbox*), kegagalan parsial observer (*try/except* per subscriber), duplikasi retry (*idempotency key*), serta halusinasi AI (4 saringan deterministik dengan calon ID `-1`), sekaligus konsisten menjaga satu pintu `KRS.transition()`.
- **Kekurangan / Kompleksitas Tambahan:** Penambahan RBAC mewajibkan klien/UI dashboard melakukan login ke `/api/auth/login` terlebih dahulu sebelum mengakses endpoint `/api/schedules/*` (kecuali `/api/schedules/export.ics` yang terbuka untuk mahasiswa).

### Ringkasan Jawaban Viva (Tanpa AI)
1. **Mengapa notifikasi wajib dikirim setelah `commit()` (lewat Outbox)?** Karena jika dikirim sebelum `commit()` lalu transaksi rollback, mahasiswa dan dosen menerima kabar palsu tentang jadwal yang tidak pernah berubah; sebaliknya, jika server kanal error sebelum `commit()`, perubahan jadwal yang sah ikut batal. Dengan *Transactional Outbox*, perubahan jadwal, invalidasi KRS, dan janji event disimpan atomik dalam satu transaksi DB, lalu dikirim belakangan oleh `OutboxDispatcher`.
2. **Mengapa saran AI harus divalidasi ulang oleh kode kita?** Karena LLM bersifat probabilistik: ia dapat membalas teks non-JSON, melanggar skema jam/hari, mengarang nama ruangan yang tidak ada di DB, memilih ruangan berkapasitas kurang, atau menyarankan slot yang bentrok dengan jadwal dosen/kelas lain. Karena itu slot kosong dihitung kode sendiri dan setiap saran AI disaring 4 lapis (parsing, skema Pydantic, eksistensi & kapasitas ruangan, serta `detect_conflicts_sweep` dengan calon `id=-1`).


## Log 15 — Modul Nilai & Transkrip Bagian 1 (Minggu 9): Skala Nilai Berbasis Data, `GradeService` (`PresensiPort` & `FOR UPDATE`), `Decimal` Pure GPA Calculator, Audit Trail `grade_history`, & Kontradiksi Spesifikasi

### Tujuan
Mengimplementasikan seluruh cakupan **Minggu ke-9 (Materi 5: Modul Nilai & Transkrip Bagian 1)** pada branch `tugas-9` yang terintegrasi rapi dengan fondasi KRS & Penjadwalan Minggu 5–8:
1. **Model & Migrasi (`d4e5f6grd010`):** Memakai `krs_detail.nilai` sebagai *single source of truth* dengan Foreign Key ke `skala_nilai.huruf` (`bobot NUMERIC(3,2)`, kolom `lulus BOOLEAN`), menambahkan tabel *append-only* `grade_history` (`grade_id -> krs_detail.id`), serta membuat SQL View `riwayat_nilai`.
2. **Penjaga Input Nilai & DIP (`GradeService` + `PresensiPort`):** Menegakkan otorisasi 2 lapis (`is_pengampu` via tabel `jadwal` $\rightarrow$ `403`, identitas dari JWT `get_current_dosen`), penguncian baris `.with_for_update()`, batas presensi $\ge 75\%$ melalui protokol `PresensiPort` + `StubPresensiPort` (hingga Modul Presensi Minggu 12), validasi Pydantic `NilaiIn` (`^[A-E]$`), idempotensi `PUT`, alasan wajib saat ubah nilai, dan transaksi atomik `krs_detail` + `grade_history`.
3. **Perhitungan IPS & IPK Presisi `Decimal` (*Functional Core, Imperative Shell*):** Memisahkan dataclass *frozen* `Skala` & `NilaiRecord` serta fungsi murni (`rata`, `hitung_ips`, `hitung_ipk` dengan `ROUND_HALF_UP` sekali di akhir), `NilaiRepo`, `GPACalculator` (*compute-on-read*), serta pembanding SQL CTE `calculate_ipk_sql`.
4. **Klarifikasi Kontradiksi Spesifikasi & Pengujian Lengkap:** Mencatat kontradiksi *"nilai >= D (2.0)"* ke dokumen stakeholder (`stakeholder-questions-minggu-9.md`), menulis uji berparameter ($\ge 10$ kasus IPK + 3 IPS + 1 tukar skala `D` lulus), 3 properti `Hypothesis`, integration test, API/UI `TestClient` (`/dashboard/grades`), serta pembaruan ADR dan README.

### Perintah (Prompt) & Kepatuhan AI-First Charter
> "Implementasikan Modul Nilai & Transkrip Bagian 1 (Minggu 9) di Python 3.15 + SQLAlchemy 2.0 + FastAPI dengan ketentuan ketat berikut:
> - **Sebutkan dulu semua ambiguitas di spesifikasi sebelum menulis satu baris kode pun.** (Khususnya kontradiksi `>= D (2.0)` vs skala `A=4, B=3, C=2, D=1, E=0`).
> - Gunakan `Decimal` dari string/integer (bukan `float`) dengan pembulatan `ROUND_HALF_UP` 2 desimal hanya sekali di akhir; kembalikan `Decimal('0.00')` jika total SKS nol, dan kirim IPS/IPK dari endpoint sebagai string 2 desimal.
> - Tulis fungsi murni (`rata`, `hitung_ips`, `hitung_ipk`) yang menerima daftar `NilaiRecord` dan kamus `Skala` tanpa DB/side-effect, baca status kelulusan dari kolom `skala_nilai.lulus` (bukan *hardcode*), dan definisikan IPS (semua MK semester tsb termasuk D/E) vs IPK (pilih bobot terbaik per `kode_mk` lebih dulu, baru saring `lulus`).
> - Terapkan *Dependency Inversion* lewat `PresensiPort` (`Protocol`) + `StubPresensiPort` (dummy Rina 90% dan Budi 70% — **AI-First Charter: jangan pernah memasukkan nilai mahasiswa sungguhan ke prompt**), cek `is_pengampu` `403`, `FOR UPDATE`, alasan wajib saat ubah nilai, serta audit trail `grade_history` dalam 1 transaksi atomik.
> - Sediakan ≥ 10 kasus `@pytest.mark.parametrize` IPK, 3 kasus IPS, 1 tes tukar skala `D` lulus, 3 properti `Hypothesis`, serta API & form web `/dashboard/grades`."

### Revisi Manual atas 7 Bug Klasik AI
1. **`float` & `round()` (*Banker's Rounding*) $\rightarrow$ `Decimal` + `ROUND_HALF_UP`:** Mengganti aritmatika `float` (`0.1 + 0.2 != 0.3`) dan `round(3.125, 2) == 3.12` dengan `Decimal` (dari `str`/`int`) dan `.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)` sekali di akhir sehingga `25 / 8 = 3.125` menjadi **`3.13`**.
2. **Menjumlahkan Nilai Tidak Lulus (`E` / `D`) ke IPK:** Memastikan `hitung_ips()` tetap menyertakan semua MK bernilai pada semester tsb, sedangkan `hitung_ipk()` menyaring `skala[r.huruf].lulus` setelah memilih nilai terbaik.
3. **Menghitung Ganda Mata Kuliah Ulang (SKS & Mutu):** Mengelompokkan record per `kode_mk` di kamus `terbaik` agar MK ulang (mis. `MA101` `E` $\rightarrow$ `B`) tidak dihitung dua kali.
4. **Pembagian dengan Nol (`ZeroDivisionError` $\rightarrow$ 500) untuk Semester Awal:** Mengembalikan `Decimal("0.00")` di `rata()` saat `total_sks == 0` dan memakai `NULLIF(SUM(sks), 0)` pada versi SQL CTE.
5. **Baris `nilai IS NULL` Memicu `KeyError`:** Menyaring `KRSDetail.nilai.is_not(None)` pada `NilaiRepo.records()` dan query SQL CTE agar mata kuliah semester berjalan yang belum dinilai tidak menyebabkan `KeyError`.
6. **`max()` pada String Huruf (`'E' > 'A'` secara ASCII):** Membandingkan **`Decimal(str(skala[r.huruf].bobot))`**, bukan membandingkan string huruf, sehingga pengulangan `E -> A -> C` maupun `B -> C` selalu memilih bobot terbaik (`4.00` / `3.00`).
7. **IPK Dihitung sebagai Rata-Rata IPS:** Pada kasus Rina, rata-rata IPS (`(2.44 + 2.00) / 2 = 2.22`) salah karena mengabaikan bobot SKS & penyaringan kelulusan; `hitung_ipk()` menghitung `total_mutu / total_sks` (`37 / 12 = 3.08`), serta di SQL CTE menghindari *integer division* SQLite (`CAST(... AS REAL)`) dan kesalahan float IEEE-754 (mis. `127/40`).

### Hasil (Hasil Implementasi)
- **Model, Exception Polimorfik, & View (`backend/app/models/grade.py`, `krs.py`, `__init__.py`):** Menambahkan `SkalaNilai` (`NUMERIC(3,2)`, `lulus`), `seed_skala_nilai`, `GradeHistory`, `RIWAYAT_NILAI_VIEW_SQL`, `ensure_riwayat_nilai_view`, hierarki `GradeError` (`GradeForbiddenError` `403`, `GradeNotFoundError` `404`, `PresensiKurangError` `422`, `AlasanWajibError` `422`, `HurufTidakValidError` `422`), mempertahankan `Grade` legacy untuk tes Minggu 1–4, serta menambahkan FK `krs_detail.nilai -> skala_nilai.huruf`.
- **Migrasi Alembic (`backend/alembic/versions/d4e5f6grd010_skala_nilai_grade_history.py`):** Membuat `skala_nilai` + *seed* `A..E`, FK `krs_detail.nilai` via `batch_alter_table`, `grade_history`, dan SQL View `riwayat_nilai`. Siklus terisolasi `upgrade head -> downgrade c3d4e5sch009 -> upgrade head` lolos (`ISOLATED_MIGRATION_OK`), dan `backend/pmb.db` berada pada **`d4e5f6grd010 (head)`**.
- **Penyelarasan Validator KRS & Fixture Lama (`backend/app/services/krs_validator.py`, `backend/test_models_and_schemas.py`):** `prasyarat_belum_lulus()` membaca `SkalaNilai.lulus` dari DB (dengan fallback legacy bila tabel kosong), dan `test_krs_manager_and_matakuliah_self_referential_flow` memanggil `seed_skala_nilai(db)`.
- **GPA Calculator & Grade Service (`backend/app/services/gpa_calculator.py`, `grade_service.py`):** Implementasi *Functional Core* (`Skala`, `NilaiRecord`, `rata`, `hitung_ips`, `hitung_ipk`), `NilaiRepo`, `GPACalculator` (*compute-on-read*), `calculate_ipk_sql` (CTE `ROW_NUMBER`), `PresensiPort` + `StubPresensiPort`, serta `GradeService` (403, `FOR UPDATE` 404, presensi $\ge 75\%$, idempoten, alasan wajib, transaksi atomik, view `riwayat_nilai`, & `seed_demo_data` Rina/Budi).
- **Auth, API, & UI (`config.py`, `security.py`, `routers/auth.py`, `schemas/grade.py`, `routers/grade.py`, `main.py`, `static/grade_input.html`):** Menambahkan `get_current_dosen`, login demo dosen (`DOSEN_DEMO_EMAIL`), `NilaiIn` (`^[A-E]$`), `PUT /api/kelas/{kelas_id}/nilai/{nim}`, `GET /api/kelas/pengampu`, `GET /api/kelas/{kelas_id}/peserta`, `GET /api/mahasiswa/{nim}/ips/{semester}`, `GET /api/mahasiswa/{nim}/ipk`, `GET /api/mahasiswa/{nim}/riwayat-nilai`, `POST /api/grades/seed-demo`, `@app.exception_handler(GradeError)`, dan UI `/dashboard/grades`.
- **Test Suite & Dokumentasi:** Menambahkan `backend/tests/test_grade.py` (**23 passed**), `repo-structure/docs/stakeholder-questions-minggu-9.md`, pembaruan ADR `3.20–3.23` & trade-off `15–18`, PR Template, serta README.
- **Verifikasi Penuh `pytest` (6 file suite):**
  - `test_models_and_schemas.py` (**40 passed**) + `test_krs_property.py` (**48 passed**) = **88 passed**.
  - `test_pmb.py` (**8 passed**) + `test_krs_api.py` (**6 passed**) + `test_schedule.py` (**24 passed**) + `test_grade.py` (**23 passed**) = **61 passed**.
  - **Total keseluruhan:** **149 passed, 0 failed** (dalam `7.54s`).

### OPAR (Observe – Plan – Act – Reflect)
- **Observe:** Dokumen tugas mengandung kontradiksi internal *"nilai >= D (2.0)"* (padahal `D = 1.00`, `2.00 = C`), AI generatif cenderung mengasumsikan batas lulus diam-diam serta menghasilkan bug klasik (`float` + `round(3.125) -> 3.12`, `max()` string huruf, pembagian 0, dan mengabaikan baris `nilai=None`), sementara Modul Presensi baru dikerjakan pada Minggu ke-12 dan kode lama masih memiliki tabel `grades` berbasis `Float` serta validator `GRADE_WEIGHT_MAP` *hardcoded*.
- **Plan:** Mencatat pertanyaan tertulis ke stakeholder sambil menetapkan asumsi sementara minimal `C` di kolom data `skala_nilai.lulus`, memakai `krs_detail.nilai` sebagai *single source of truth* (FK ke `skala_nilai.huruf` lewat migrasi `d4e5f6grd010`, menjaga `Grade` legacy hanya demi kompatibilitas tes Minggu 1–4), memisahkan logika `Decimal` ke fungsi murni tanpa DB (*Functional Core*), mengisolasi ketergantungan presensi di balik `PresensiPort` + `StubPresensiPort`, menerapkan `GradeService` dalam satu transaksi bersama `grade_history` + SQL View `riwayat_nilai`, serta memverifikasi penuh dengan 11 kasus IPK berparameter, 3 IPS, tukar skala, 3 properti `Hypothesis`, differential test SQL CTE, dan API `TestClient`.
- **Act:** Mengimplementasikan seluruh model, migrasi `d4e5f6grd010`, layanan (`gpa_calculator.py`, `grade_service.py`, `krs_validator.py`), autentikasi `get_current_dosen`, router `/api` + `/dashboard/grades`, `test_grade.py`, serta pembaruan dokumentasi stakeholder, ADR, log AI, PR template, dan README. Satu temuan selama pengujian (`DetachedInstanceError` pada fixture `grade_api_env` akibat akses atribut objek `Dosen` setelah sesi ditutup) langsung diperbaiki dengan mengekstrak skalar `(id, nidn)` di fixture sebelum sesi ditutup. Seluruh verifikasi migrasi dan **149 test passed (0 failed)**.
- **Reflect:** Karena Modul Presensi belum tersedia, penjaga presensi 75% bergantung pada `StubPresensiPort` hingga Minggu ke-12 (dicatat sebagai risiko di PR Template). Selain itu, `.with_for_update()` pada SQLite diabaikan saat runtime sehingga uji konkurensi baris antar-sesi tetap perlu diverifikasi di PostgreSQL/MySQL, serta pada `auth.py` ditambahkan pengecekan eksistensi tabel `users` agar login demo dosen tetap berjalan di `pmb.db` hasil migrasi Alembic yang belum memiliki tabel `users`.

### Evaluasi (Objektif)
- **Kelebihan:** Desain *Functional Core, Imperative Shell* memisahkan kalkulasi `Decimal` murni dari ORM sehingga ribuan kasus diuji cepat tanpa mock; definisi kelulusan di `skala_nilai.lulus` dan `PresensiPort` membuat sistem siap terhadap keputusan stakeholder maupun integrasi Minggu 12 tanpa menyentuh kode inti; dan IPK *compute-on-read* bebas risiko cache basi.
- **Kekurangan / Kompleksitas Tambahan:** Diperlukan penyesuaian fixture test lama agar mengisi `skala_nilai` sebelum menyimpan `KRSDetail.nilai`, serta keberadaan model `Grade` legacy tetap dipertahankan sementara di `models/grade.py` hingga modul lama dibersihkan sepenuhnya.

### Ringkasan Jawaban Viva (Tanpa AI)
1. **Mengapa `Decimal` + `ROUND_HALF_UP` wajib dipakai dan dibulatkan sekali di akhir?** Karena `float` berbasis biner tidak dapat merepresentasikan pecahan desimal seperti `0.1` secara tepat, dan `round()` Python memakai *banker's rounding* (`round(3.125, 2) == 3.12`) yang merugikan mahasiswa pada batas predikat kelulusan. Dengan `Decimal` dari string dan `quantize(Decimal("0.01"), ROUND_HALF_UP)` sekali di akhir (`total_mutu / total_sks`), `3.125` menjadi `3.13` tanpa akumulasi galat pembulatan per semester.
2. **Mengapa tidak langsung memutus batas lulus `D` atau `C` secara diam-diam di kode?** Karena kontradiksi *"nilai >= D (2.0)"* adalah keputusan kebijakan akademik (stakeholder), bukan kewenangan teknis AI atau programmer untuk ditebak diam-diam—apalagi dampaknya mengubah IPK Rina dari `3.08` menjadi `2.67`. Menaruh aturan di `skala_nilai.lulus` menjadikan perubahan kebijakan cukup 1 baris data.
3. **Mengapa memilih *compute-on-read* untuk IPK dan transaksi `GradeService` untuk `grade_history`?** *Compute-on-read* menjamin IPK selalu akurat tanpa risiko cache basi untuk ~60 baris nilai per mahasiswa; sedangkan pencatatan audit di `GradeService` dalam satu transaksi DB menangkap `diubah_oleh` dan `alasan` secara portabel di SQLite maupun MySQL/PostgreSQL tanpa duplikasi dengan trigger.


## Log 16 — Modul Keuangan / SPP (Minggu 11): Payment Schema `e5f6g7fin011`, `BillingService`, Webhook HMAC-SHA256, Blokir KRS, APScheduler, Dashboard, & AI Financial Insights

### Tujuan
Mengimplementasikan seluruh cakupan **Minggu 11: Modul Keuangan (SPP)** pada branch `tugas-11` beserta integrasi penuh ke modul KRS, Auth RBAC, dan Notifikasi:
1. **Payment Schema & Migrasi (`e5f6g7fin011`):** Menambahkan tabel `payment_method`, `billing` (`unpaid`, `partial`, `paid`, `overdue`, `UniqueConstraint(nim, semester)`), `payment` (`transaction_id` unik), serta kolom `program_studi.biaya_spp` bertipe `NUMERIC(14, 2)` / `Decimal`.
2. **Billing Service & Cron Jobs (`APScheduler`):** `generate_billing()` untuk mahasiswa aktif (Teknik Rp 5jt, Ekonomi Rp 4jt, jatuh tempo +14 hari), `process_payment()` atomik (`with_for_update()`), perhitungan denda keterlambatan terkonfigurasi (`2%/bulan` maks `10%`, `grace_days=0`), serta `FinanceSchedulerManager` (`BackgroundScheduler` + `CronTrigger` awal semester & harian 07:00).
3. **Pemblokiran KRS Saat Ada Tunggakan:** Memblokir `add_course`, `remove_course`, dan `submit_krs` (`403 KRSBillingBlockedError`) apabila mahasiswa memiliki tagihan berstatus `unpaid`, `partial`, atau `overdue` via `BillingGuardPort` (serta `TunggakanValidator`).
4. **Payment Webhook Simulation & Receipt Email:** Endpoint `POST /api/finance/webhook` dengan verifikasi `HMAC-SHA256`, idempotensi `transaction_id`, penanganan status gagal/pending, dan simulasi pengiriman receipt email via `LogChannel("EMAIL")` + tabel `notifikasi`.
5. **Dashboard Keuangan & AI Financial Insights:** Endpoint real-time `/api/finance/dashboard`, halaman `/dashboard/finance`, serta laporan JSON deterministik (`total_revenue_bulan_ini`, `collection_rate_percent`, `top_10_tunggakan`, `Z` mahasiswa tunggakan `>2` bulan) + narasi AI tervalidasi Pydantic dengan *fallback* deterministik.

### Perintah (Prompt)
> "Analisis spesifikasi Minggu 11: Modul Keuangan (SPP) terhadap codebase `Sevima-Mini`, laporkan celah/ambiguitas terlebih dahulu, lalu implementasikan dengan keputusan:
> 1. Pemblokiran KRS berlaku untuk semua tagihan yang belum lunas (`unpaid`, `partial`, `overdue`).
> 2. Denda keterlambatan memakai konfigurasi default (`Settings` / `LateFeeConfig`: 2% per 30 hari, cap 10%, grace 0 hari) berbasis `Decimal`.
> 3. Lengkapi dengan dokumentasi ADR, pertanyaan stakeholder (`stakeholder-questions-minggu-11.md`), AI usage log + OPAR, PR template, dan pembaruan `README.md`."

### Revisi Manual & Bug yang Ditemukan Saat Verifikasi
1. **Bug Cicilan Kumulatif pada Pseudo-Code Spesifikasi:** Spesifikasi menulis `amount < billing.total -> 'partial'`, padahal cicilan tahap ke-2 (mis. 2jt + 3jt = 5jt) akan salah tetap berstatus `partial`. Diperbaiki dengan mengevaluasi akumulasi `amount_paid + amount` terhadap `total_due` (`determine_billing_status`).
2. **`inspect(db.get_bind()).has_table(...)` Memicu `ROLLBACK` pada SQLite `SingletonThreadPool`:** Pengecekan keberadaan tabel di `SQLAlchemyBillingGuard` dan `TunggakanValidator` sempat memanggil `inspect(db.get_bind())` yang membuka koneksi sementara pada pool tunggal in-memory SQLite dan me-`rollback` baris `KRS` yang baru di-`flush()` (`StaleDataError` pada 6 test KRS/Jadwal). Diperbaiki menjadi `inspect(db.connection()).has_table(...)` agar memakai koneksi transaksi sesi aktif.
3. **Atribut `job.next_run_time` pada APScheduler 3.11.3 Sebelum `start()`:** Mengakses `job.next_run_time` secara langsung saat scheduler belum berjalan memicu `AttributeError`; diperbaiki dengan `getattr(job, "next_run_time", None)`.
4. **Tanggal Jatuh Tempo pada Test Fixture (`2026-11-01` vs `2026-11-20`):** Penetapan `semester_start="2026-11-01"` membuat `due_date="2026-11-15"` otomatis berstatus `overdue` pada tanggal pengujian `2026-11-20`; diselaraskan menggunakan `date.today().isoformat()` untuk skenario pembayaran tepat waktu.

### Hasil (Hasil Implementasi)
- **Model, Exception Polimorfik, & Migrasi:** `backend/app/models/finance.py`, pembaruan `program_studi.py`, `krs.py` (`KRSBillingBlockedError`), `__init__.py`, dan migrasi `backend/alembic/versions/e5f6g7fin011_tabel_keuangan_spp.py` (`ISOLATED_MIGRATION_OK` untuk siklus `upgrade head -> downgrade d4e5f6grd010 -> upgrade head`; `backend/pmb.db` pada `e5f6g7fin011 (head)`).
- **Layanan & Functional Core:** `backend/app/services/finance_calculator.py`, `billing_service.py`, `finance_ai_report.py`, `finance_scheduler.py`, serta integrasi di `krs_validator.py` dan `krs_manager.py`.
- **API, Lifespan, & UI:** `backend/app/schemas/finance.py`, `backend/app/routers/finance.py`, `backend/app/main.py` (`lifespan` APScheduler, `@app.exception_handler(FinanceError)`, `/dashboard/finance`), dan `backend/app/static/finance_dashboard.html`.
- **Test Suite (`backend/tests/test_finance.py` — 31 tests):** Parameterized unit tests (denda, status, tarif, HMAC), 2 *Property-Based Tests* `Hypothesis` (2×200 contoh), integrasi `BillingService`, webhook HMAC + idempotensi, blokir & buka blokir KRS, lifecycle `APScheduler`, AI Financial Insights (CSV + DB + guardrail `FakeLLMClient`), RBAC dashboard, dan HTML UI.
- **Verifikasi Penuh `pytest` (7 file suite):** **180 passed, 0 failed** (`149` test sebelumnya + `31` test baru di `test_finance.py`).

### OPAR (Observe – Plan – Act – Reflect)
- **Observe:** Spesifikasi Minggu 11 memuat pseudo-code cicilan tunggal yang rentan bug kumulatif, tidak menetapkan rumus denda secara eksplisit, rawan duplikasi saldo jika webhook dikirim ulang (*retry*), dan berisiko membuat LLM menghitung angka finansial secara keliru jika data mentah CSV langsung dikirim ke LLM. Selain itu, integrasi blokir KRS harus tidak merusak 149 test existing yang belum memiliki data tagihan.
- **Plan:** Memisahkan tabel baru `payment_method`, `billing`, dan `payment` (`NUMERIC(14,2)`) dari tabel legacy `payments`, menyisipkan `BillingGuardPort` di `KRSManager` agar mahasiswa tanpa record tagihan tetap lolos sementara mahasiswa dengan tagihan `unpaid`/`partial`/`overdue` terblokir `403`, mengamankan webhook via HMAC-SHA256 + `transaction_id` unik + `with_for_update()`, menjadwalkan cron `APScheduler` lewat `lifespan`, dan menghitung seluruh metrik AI report secara deterministik sebelum meminta narasi teranonimasi dari `LLMClient`.
- **Act:** Mengimplementasikan seluruh modul, migrasi Alembic `e5f6g7fin011`, dashboard `/dashboard/finance`, 31 test di `test_finance.py`, serta memperbaiki 3 temuan saat eksekusi (`inspect(db.connection())`, `getattr(job, "next_run_time", None)`, dan tanggal fixture test) hingga seluruh **180 test passed (0 failed)**.
- **Reflect:** Pengiriman receipt dan reminder via email saat ini disimulasikan melalui `LogChannel("EMAIL")` + tabel `notifikasi` (belum terhubung ke SMTP server produksi), scheduler `APScheduler` in-process cocok untuk worker tunggal tetapi memerlukan pemisahan proses/lock jika di-deploy multi-worker, dan `FOR UPDATE` pada SQLite tidak menguji penguncian paralel antar-sesi seperti PostgreSQL/MySQL.

### Evaluasi (Objektif)
- **Kelebihan:** Seluruh kalkulasi uang dan laporan memakai `Decimal` + fungsi murni deterministik, webhook tahan *retry* dan pemalsuan signature, blokir KRS teruji end-to-end terbuka otomatis setelah pelunasan webhook, dan seluruh ambiguitas terdokumentasi resmi untuk stakeholder.
- **Kekurangan / Kompleksitas Tambahan:** Mempertahankan tabel legacy `payments` bersama tabel baru `payment` sampai modul PMB/KRS awal disatukan sepenuhnya pada iterasi akhir.

### Ringkasan Jawaban Viva (Tanpa AI)
1. **Mengapa `determine_billing_status` harus mengevaluasi `amount_paid + amount`, bukan `amount` tunggal?** Karena pembayaran cicilan mengubah status secara kumulatif. Jika tagihan Rp 5 juta dibayar Rp 2 juta lalu Rp 3 juta, membandingkan pembayaran ke-2 (`3 juta < 5 juta`) akan salah mempertahankan status `partial` padahal total terbayar sudah `5 juta` (`paid`).
2. **Bagaimana webhook gateway diamankan dari pemalsuan dan pengiriman ulang (*retry*)?** Pertama, payload mentah diverifikasi dengan `HMAC-SHA256` menggunakan `hmac.compare_digest` (`401` bila gagal). Kedua, kolom `payment.transaction_id` diberi constraint `UNIQUE` dan dicek di awal `process_payment()` sehingga retry dengan `transaction_id` sama langsung mengembalikan `200 OK` (`idempotent_replay=True`) tanpa menambah `amount_paid`.
3. **Mengapa perhitungan angka pada AI Financial Insights tidak diserahkan ke LLM?** Karena LLM bersifat probabilistik dan rawan halusinasi aritmatika maupun melanggar privasi bila NIM mentah dikirim ke API luar. Backend menghitung revenue, *collection rate*, top 10 tunggakan, dan jumlah mahasiswa telat `>2` bulan (`Z`) secara deterministik di Python/`Decimal`, lalu LLM hanya menyusun ringkasan dari metrik agregat teranonimasi.












