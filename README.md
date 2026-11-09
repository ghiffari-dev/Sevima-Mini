# Sevima-Mini

Sistem Informasi Akademik Mini (Sevima-Mini) adalah aplikasi berbasis Object-Oriented Programming (OOP) untuk mengelola aktivitas akademik di sebuah institusi pendidikan, seperti pendaftaran mahasiswa baru, pengisian Kartu Rencana Studi (KRS), penjadwalan kelas, dan pencatatan nilai.

## Fitur Utama

- **Manajemen pengguna (User):** Mahasiswa, Dosen, Admin, dan Calon Mahasiswa dengan sistem autentikasi (login/logout). `User` dirancang sebagai abstract base class.
- **Manajemen mata kuliah (Course):** kode, nama, SKS, dan daftar prasyarat.
- **Pendaftaran Mahasiswa Baru (PMB):** melalui kelas `CalonMahasiswa` dan `PendaftaranPMB`, dengan pemisahan proses antara pembayaran dan verifikasi hasil seleksi oleh `Admin`.
- **Pengisian KRS:** melalui `PendaftaranKRS` dan `Enrollment` yang menghubungkan `Mahasiswa` dan `Course`, dilengkapi validasi komprehensif (prasyarat, SKS, jadwal, kapasitas) serta *deferred enrollment* setelah pembayaran lunas.
- **Penjadwalan kuliah (Schedule):** hari, jam, dan ruangan (berelasi komposit dengan `Kelas`).
- **Pencatatan nilai (Grade):** nilai angka, nilai huruf, dan bobot, terkait komposisi dengan `Enrollment`.
- **Desain berbasis prinsip SOLID** (terutama Open/Closed Principle dan Liskov Substitution Principle).
- **Relasi antar kelas** menggunakan Aggregation (relasi lemah) dan Composition (relasi kuat).

## Struktur Proyek

```
repo-structure/
├── diagrams/
│   ├── class-diagram.mmd        # Diagram kelas UML (Mermaid)
│   ├── usecase-diagram.puml     # Diagram use case UML (PlantUML)
│   ├── sequence-krs.mmd         # Diagram sekuens KRS (Mermaid)
│   └── sequence-pmb.mmd         # Diagram sekuens PMB (Mermaid)
├── docs/
│   ├── ADR-architecture-decisions.md # Keputusan Arsitektur Sistem (ADR-001)
│   ├── ADR-architecture-decisions.pdf
│   └── Final-UML-diagram.pdf
└── prompts/
    └── ai-usage-log.md          # Catatan penggunaan AI selama perancangan
```

## Teknologi & Tools

- Bahasa pemrograman: Python
- **Diagrams:** Mermaid (`.mmd`) untuk Class Diagram & Sequence Diagram, PlantUML (`.puml`) untuk Use Case Diagram
- Dokumentasi & Arsitektur: Markdown, PDF, Architecture Decision Records (ADR)

## Cara Menjalankan & Melihat

1. Pastikan lingkungan Python terinstal.
2. Diagram UML dapat dilihat menggunakan renderer Mermaid (`.mmd`) dan PlantUML (`.puml`) di VS Code (PlantUML/Mermaid Preview) atau GitHub.

## Lisensi

Tidak ada lisensi tertentu.
