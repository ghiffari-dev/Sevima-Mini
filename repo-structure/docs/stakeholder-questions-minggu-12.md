# Klarifikasi Celah Spesifikasi & Keputusan Teknis — Minggu 12: Modul Presensi (QR Code)

Dokumen ini mencatat ambiguitas serta kontradiksi teknis yang ditemukan pada spesifikasi **Minggu 12: Modul Presensi (QR Code)** beserta keputusan implementasi dan pertanyaan konfirmasi kepada Stakeholder Akademik / Tim Produk.

---

## 1. Temuan Kontradiksi & Celah pada Dokumen Spesifikasi

1. **Kontradiksi Batas Waktu QR (15 Menit) vs Jendela Status Terlambat (15–30 Menit)**
   - **Spesifikasi:** Deliverable 1 & Step 1 menyatakan *"QR valid hanya 15 menit"* (`valid_minutes=15`), sedangkan Step 2 menyatakan *"Hadir jika scan dalam 15 menit pertama; Terlambat jika scan setelah 15 menit (max 30 menit)"*.
   - **Masalah:** Jika QR statis mati pada menit ke-15, mahasiswa yang datang pada menit ke-16 s.d. ke-30 akan selalu gagal pada langkah ke-1 (*Decode JWT & check exp*), sehingga cabang status `terlambat` menjadi *dead code* (tidak pernah tercapai).
   - **Keputusan Implementasi:** Sesi presensi dibuka selama **30 menit** (`closes_at = opened_at + 30 menit`), sementara token QR **berotasi otomatis setiap 120 detik** (`ATTENDANCE_QR_ROTATE_SECONDS=120`) dengan toleransi `grace_windows=1`. Dengan demikian, QR yang tampil di layar dosen tidak pernah berumur lebih dari beberapa menit, namun mahasiswa yang datang di menit ke-16..30 tetap dapat memindai QR terbaru dan tercatat sebagai `terlambat`.

2. **Klaim Anti-Replay pada Contoh Prompt Step 1 Belum Terpenuhi**
   - **Spesifikasi:** Deliverable 1 mewajibkan *"Token unik per sesi (prevent replay attack)"*, tetapi contoh kode Step 1 hanya memasukkan `{'schedule_id', 'iat', 'exp'}` tanpa identitas sesi maupun *nonce* unik.
   - **Masalah:** Token statis selama 15 menit dapat difoto dan dikirim ke grup pesan (*titip absen*), atau dipakai ulang lintas sesi jika jadwal dibuka dua kali.
   - **Keputusan Implementasi:** Setiap `AttendanceSession` memiliki `secret` acak 128-bit (`secrets.token_hex(16)`), dan setiap jendela rotasi menyertakan klaim `sid` (`session_id`), `win` (`window_index`), serta `jti = HMAC-SHA256(secret, "sid:win")[:32]`. Token jendela lama otomatis ditolak begitu melewati `grace_windows`.

3. **Potensi Spoofing `nim` pada Body `POST /attendance/scan` & `datetime.utcnow()` Usang**
   - **Spesifikasi:** Step 2 menerima `Input: { token: 'jwt_from_qr', nim: 'xxx' }` dan Step 1 memakai `datetime.utcnow()`.
   - **Keputusan Implementasi:** Seluruh stempel waktu memakai `datetime.now(timezone.utc)` dan konversi hari kuliah memakai zona waktu `Asia/Jakarta` (`zoneinfo.ZoneInfo`). Endpoint `/attendance/scan` mendukung autentikasi JWT Mahasiswa (`role="mahasiswa"`): bila header `Authorization: Bearer` dikirim, sistem menolak keras percobaan scan menggunakan `nim` mahasiswa lain (`403 AttendanceForbiddenError`) dan dapat mengisi `nim` otomatis dari klaim JWT, sambil tetap kompatibel dengan input `{token, nim}` pada pengujian otomatis.

4. **Validasi Lokasi (Geolocation) & Pembagi Persentase Kehadiran (`< 75%`)**
   - **Spesifikasi:** Tujuan Pembelajaran mencantumkan *"Geolocation validation (optional)"* tanpa rumus jarak/radius, dan Deliverable 3 mewajibkan *"persentase kehadiran per MK"* tanpa mendefinisikan pembagi (total sesi yang sudah dibuka vs 14 pertemuan rencana semester).
   - **Keputusan Implementasi:**
     - **Geofencing Haversine:** Dosen dapat menyertakan koordinat ruang kelas (`latitude`, `longitude`, `radius_m` default `100m`). Saat aktif, scan mahasiswa wajib menyertakan GPS dengan akurasi $\le 150\text{ m}$ dan jarak *Haversine* $\le \text{radius\_m}$.
     - **Pembagi Persentase & Risiko:** Persentase berjalan dihitung dari `(hadir + terlambat) / total_sesi_dibuka` (`Decimal` `ROUND_HALF_UP`), sedangkan proyeksi *early warning* (`aman` / `berisiko` / `kritis`) turut menghitung sisa jatah absen terhadap target `14` pertemuan semester (`ATTENDANCE_TOTAL_PERTEMUAN=14`).

---

## 2. Daftar Pertanyaan Resmi untuk Stakeholder Akademik

1. **Kebijakan Bobot Status `terlambat`:** Apakah mahasiswa berstatus `terlambat` (16–30 menit) dihitung penuh (`1.0` kehadiran) dalam syarat kelayakan ujian $\ge 75\%$, atau apakah setiap $N$ kali `terlambat` dikonversi menjadi 1 kali `alpha`?
2. **Radius Geofence Kampus:** Apakah radius default `100 meter` dengan batas akurasi GPS `150 meter` sudah sesuai dengan kondisi gedung perkuliahan (termasuk ruang laboratorium di lantai bawah)?
3. **Izin / Sakit Resmi:** Apakah pada iterasi berikutnya diperlukan status tambahan `izin` / `sakit` yang diinput manual oleh dosen pengampu agar tidak otomatis dihitung sebagai `alpha`?
