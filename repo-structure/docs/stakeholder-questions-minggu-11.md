# Pertanyaan Tertulis ke Stakeholder — Modul Keuangan / SPP (Minggu 11)

## 1. Celah, Ambiguitas, & Kontradiksi Spesifikasi yang Ditemukan

Selama analisis spesifikasi **Minggu 11: Modul Keuangan (SPP)** sebelum implementasi, ditemukan beberapa celah aturan bisnis dan teknis:

1. **Bug Logika Cicilan pada Pseudo-Code `process_payment` (Halaman 2):**
   - Dokumen tugas mencantumkan:
     - *"Jika `amount < billing.total` -> status `'partial'`"*
     - *"Jika `amount >= billing.total` -> status `'paid'`"*
   - Jika mahasiswa mencicil tagihan Rp 5.000.000 dua kali (Rp 2.000.000 lalu Rp 3.000.000), membandingkan pembayaran kedua (`amount = 3.000.000`) terhadap `billing.total` (`5.000.000`) akan keliru mempertahankan status `'partial'` padahal total terbayar kumulatif sudah mencapai 100%.
   - Selain itu, spesifikasi belum mengatur: pembayaran terhadap tagihan yang sudah `paid`, nominal `<= 0`, dan skenario kelebihan bayar (*overpayment*).
2. **Rumus Denda Keterlambatan Tidak Dirinci:**
   - Deliverable ke-2 mensyaratkan *"Calculate denda keterlambatan"*, namun tidak menetapkan besaran tarif (persentase/bulan vs flat harian), adanya masa tenggang (*grace period*), batas maksimal denda (*cap*), serta apakah denda dihitung dari pokok tagihan atau sisa tagihan.
3. **Prioritas Status `overdue` vs `partial` Setelah Jatuh Tempo:**
   - Ketika tagihan telah melewati `due_date` (`overdue`) lalu mahasiswa membayar sebagian (belum lunas), apakah status tetap `overdue` atau berubah menjadi `partial`?
4. **Definisi "Tunggakan" Pemblokir KRS:**
   - Apakah pengisian KRS diblokir hanya untuk tagihan berstatus `overdue`, atau untuk **seluruh** tagihan yang belum berstatus `paid` (`unpaid`, `partial`, `overdue`)?
5. **Keterbatasan Kolom CSV vs Kebutuhan Laporan AI:**
   - Input CSV pada Langkah 3 memiliki kolom `nim, jumlah, tanggal, status`, sedangkan laporan meminta top tunggakan dan jumlah mahasiswa dengan tunggakan `> 2` bulan. Kolom CSV tersebut tidak memiliki `due_date` maupun `program_studi`.
6. **Ketahanan Webhook Gateway (Payload, Signature, & Idempotensi):**
   - Langkah 2 menyebut ekstraksi `transaction_id, amount, status`, padahal endpoint tetap membutuhkan pengenal tagihan (`billing_id` atau `invoice_number`), penanganan status gagal/pending agar tidak menambah saldo bayar, serta perlindungan terhadap *retry* duplikat (`transaction_id` unik).

## 2. Dampak Kuantitatif Jika Salah Asumsi

- **Cicilan kumulatif vs cicilan tunggal:** Tagihan Rp 5.000.000 yang dilunasi 2x (Rp 2.000.000 + Rp 3.000.000) akan tetap memblokir KRS mahasiswa dan mengacaukan *collection rate* apabila status tidak berubah menjadi `paid`.
- **Tarif denda keterlambatan:** Pada tagihan Rp 5.000.000 yang telat 45 hari, skema `2%` per blok 30 hari menghasilkan denda **Rp 200.000** (`4%`), sedangkan skema harian tanpa batas bisa terus bertambah dan mengubah total kewajiban pada *Dashboard Keuangan* maupun *Top 10 Tunggakan*.
- **Webhook retry tanpa idempotensi:** Pengiriman ulang notifikasi pembayaran yang sama dari gateway berisiko menggandakan `amount_paid` dan mengacaukan total pendapatan bulanan.

## 3. Daftar Pertanyaan ke Stakeholder (Bagian Keuangan / Akademik)

1. Untuk denda keterlambatan SPP, manakah rumus resmi institusi: **persentase per bulan keterlambatan** (mis. `2%` per 30 hari dari pokok, batas maks `10%`), **nominal harian tetap**, dan apakah diberlakukan *grace period* setelah `due_date`?
2. Jika mahasiswa dengan tagihan `overdue` membayar cicilan sebagian (belum lunas), apakah status tagihan tetap dipertahankan sebagai `overdue` sampai lunas penuh (`paid`)?
3. Apabila mahasiswa melakukan pembayaran melebihi total kewajiban (*overpayment*), apakah kelebihan dana dicatat sebagai kredit/deposit semester berikutnya atau harus ditolak sejak validasi input?
4. Apakah pemblokiran KRS berlaku bagi mahasiswa yang belum memiliki record tagihan sama sekali (misal mahasiswa bebas biaya / beasiswa penuh), atau khusus bagi yang memiliki baris `billing` berstatus selain `paid`?
5. Untuk sumber data CSV laporan bulanan eksternal (`nim, jumlah, tanggal, status`), apakah tanggal pada baris menunggak dapat diperlakukan sebagai acuan umur tunggakan (> 60 hari), atau apakah format CSV produksi boleh ditambah kolom `due_date` dan `sisa`?

## 4. Keputusan Sementara & Mitigasi Teknis yang Diterapkan

- **Pemblokiran KRS (Terkonfirmasi):** Semua tagihan belum lunas (`unpaid`, `partial`, `overdue`) memblokir `add_course`, `remove_course`, dan `submit_krs` (`403 Forbidden` via `KRSBillingBlockedError`). Mahasiswa tanpa record `billing` tidak diblokir sehingga seluruh 149 tes modul sebelumnya tetap aman.
- **Konfigurasi Denda Default (`LateFeeConfig` & `Settings`):** Denda dihitung dengan konfigurasi yang dapat diubah via environment variable (`.env`) tanpa menyentuh kode logika: default **`2%` per blok 30 hari** (`LATE_FEE_RATE_PER_MONTH=0.02`), batas maksimal **`10%`** (`LATE_FEE_MAX_RATE=0.10`), dan **`grace_days=0`** (`LATE_FEE_GRACE_DAYS=0`), seluruhnya memakai aritmatika `Decimal` (`ROUND_HALF_UP`).
- **Tarif SPP Berbasis Data (`program_studi.biaya_spp`):** Tarif per prodi dapat diisi langsung pada kolom `program_studi.biaya_spp`, dengan fallback terkonfigurasi (`SPP_TEKNIK_AMOUNT=5000000.00`, `SPP_EKONOMI_AMOUNT=4000000.00`, `SPP_DEFAULT_AMOUNT=4500000.00`).
- **Cicilan Kumulatif & Idempotensi Webhook:** Evaluasi status selalu memakai total terbayar kumulatif (`amount_paid + amount`) terhadap `amount + late_fee`, `transaction_id` dijaga unik (`UNIQUE`), dan seluruh metrik angka AI Financial Report dihitung deterministik di backend sebelum narasi LLM.
