# Pertanyaan Tertulis ke Stakeholder — Modul Nilai & Transkrip (Minggu 9)

## 1. Kontradiksi Spesifikasi yang Ditemukan
Pada bagian *Business Rules* dokumen tugas tertulis:
> *"Lulus mata kuliah jika nilai >= D (2.0)."*

Sementara itu, pada definisi skala nilai akademik di sistem ditetapkan 5 tingkat huruf tanpa nilai antara:
- `A` = `4.00`
- `B` = `3.00`
- `C` = `2.00`
- `D` = `1.00`
- `E` = `0.00`

Kalimat *"nilai >= D (2.0)"* **bertentangan dengan dirinya sendiri** karena:
- Nilai **`D`** berbobot **`1.00`** (bukan `2.00`).
- Bobot **`2.00`** adalah nilai **`C`**.

## 2. Dampak Kuantitatif Jika Salah Asumsi
Perbedaan tafsir antara batas lulus `C (2.00)` dan `D (1.00)` berdampak langsung pada dua bagian utama sistem:

1. **Perhitungan IPK Kumulatif (contoh kasus dummy Rina):**
   - Semester `20241`: Kalkulus 1 (`3 SKS`, `E`), Algoritma (`4 SKS`, `A`), Bahasa Inggris (`2 SKS`, `B`) $\rightarrow$ IPS = `2.44`.
   - Semester `20242`: Kalkulus 1 ulang (`3 SKS`, `B`), Struktur Data (`3 SKS`, `C`), Basis Data (`3 SKS`, `D`) $\rightarrow$ IPS = `2.00`.
   - **Jika minimal `C` (`2.00`) yang lulus:** Basis Data (`D`) **tidak** masuk IPK $\rightarrow$ $\text{IPK} = 37 / 12 = \mathbf{3.08}$.
   - **Jika minimal `D` (`1.00`) yang lulus:** Basis Data (`D`) **ikut** masuk IPK $\rightarrow$ $\text{IPK} = 40 / 15 = \mathbf{2.67}$.
   - Selisihnya mencapai **0,41 poin** dan memengaruhi predikat kelulusan maupun syarat akademik.
2. **Validasi Prasyarat KRS (`PrerequisiteValidator`):**
   - Pada Minggu ke-5/6, prasyarat KRS juga mengacu pada kelulusan mata kuliah sebelumnya (`>= C` / `bobot >= 2.0`). Jika aturan kelulusan di `skala_nilai` berbeda atau ikut berubah menjadi `D`, kelayakan pengambilan mata kuliah lanjutan ikut berubah.

## 3. Daftar Pertanyaan ke Stakeholder (Dosen / Bagian Akademik)
1. Untuk kelulusan mata kuliah pada transkrip dan perhitungan IPK, manakah batas yang berlaku secara resmi: **minimal huruf `C` (bobot `>= 2.00`)** atau **minimal huruf `D` (bobot `>= 1.00`)**?
2. Apakah definisi kelulusan mata kuliah untuk perhitungan **IPK** sama persis dengan definisi kelulusan untuk **prasyarat KRS** (`PrerequisiteValidator`), atau apakah ada mata kuliah/kondisi khusus di mana `D` dianggap lulus di IPK tetapi tidak memenuhi prasyarat?
3. Apakah batas minimal kelulusan berlaku seragam untuk seluruh mata kuliah, atau ada rencana skala per kurikulum/prodi di semester mendatang?

## 4. Asumsi Sementara & Mitigasi Teknis
- **Asumsi sementara:** Selama menunggu jawaban tertulis stakeholder, sistem menggunakan **minimal `C` (`2.00`) lulus** (`A, B, C` $\rightarrow$ `lulus = True`; `D, E` $\rightarrow$ `lulus = False`), konsisten dengan angka `2.0` pada spesifikasi dan aturan prasyarat Minggu 5–6.
- **Mitigasi berbasis data:** Aturan kelulusan **tidak ditulis mati (hardcode)** di kode Python maupun SQL. Nilai boolean kelulusan disimpan di kolom **`skala_nilai.lulus`** (migrasi `d4e5f6grd010`). Apabila stakeholder memutuskan `D` dianggap lulus, perubahan cukup dilakukan dengan memperbarui **1 baris data** pada tabel `skala_nilai` (`UPDATE skala_nilai SET lulus = TRUE WHERE huruf = 'D'`) tanpa menyentuh kode layanan `GPACalculator` maupun `PrerequisiteValidator`.
