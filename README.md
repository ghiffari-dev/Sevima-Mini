# Sevima-Mini

Sistem Informasi Akademik Mini (Sevima-Mini) adalah aplikasi berbasis Object-Oriented Programming (OOP) untuk mengelola aktivitas akademik di sebuah institusi pendidikan, seperti pendaftaran mahasiswa baru, pengisian Kartu Rencana Studi (KRS), penjadwalan kelas, dan pencatatan nilai.

## Fitur Utama

- **Manajemen pengguna (User):** Mahasiswa, Dosen, Admin, dan Calon Mahasiswa dengan sistem autentikasi (login/logout). `User` dirancang sebagai abstract base class.
- **Manajemen mata kuliah (Course):** kode, nama, SKS, dan daftar prasyarat.
- **Pendaftaran Mahasiswa Baru (PMB):** melalui kelas `CalonMahasiswa`.
- **Pengisian KRS:** melalui `Enrollment` yang menghubungkan `Mahasiswa` dan `Course`.
- **Penjadwalan kuliah (Schedule):** hari, jam, dan ruangan.
- **Pencatatan nilai (Grade):** nilai angka, nilai huruf, dan bobot, terkait komposisi dengan `Enrollment`.
- **Desain berbasis prinsip SOLID** (terutama Open/Closed Principle dan Liskov Substitution Principle).
- **Relasi antar kelas** menggunakan Aggregation (relasi lemah) dan Composition (relasi kuat).

## Struktur Proyek

```
repo-structure/
├── diagrams/
│   ├── class-diagram.mmd     # Diagram kelas UML (Mermaid)
│   ├── usecase-diagram.mmd   # Diagram use case UML (Mermaid)
│   ├── sequence-krs.mmd      # Diagram sekuens KRS (Mermaid)
│   └── sequence-pmb.mmd      # Diagram sekuens PMB (Mermaid)
├── docs/
│   ├── ADR-architecture-decisions.pdf
│   └── Final-UML-diagram.pdf
└── prompts/
    └── ai-usage-log.md       # Catatan penggunaan AI selama perancangan
```

## Teknologi & Tools

- Bahasa pemrograman: Python (contoh berkas: `nama.py`)
- Diagram: Mermaid (`.mmd`)
- Dokumentasi: Markdown, PDF

## Cara Menjalankan

1. Pastikan Python terinstal.
2. Diagram UML dapat dilihat dengan renderer Mermaid dan PlantUML(VS Code Mermaid Preview, GitHub, dll.).


## Lisensi

Tidak ada lisensi tertentu.
