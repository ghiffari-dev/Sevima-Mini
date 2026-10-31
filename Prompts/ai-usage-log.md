# AI Usage Log (Log Penggunaan AI)
## Log 01 — Diagram Kelas Awal

### Tujuan
Menghasilkan Diagram Kelas UML awal untuk sistem informasi akademik seperti SEVIMA-Mini.

### Perintah (Prompt)
Anda adalah arsitek sistem. Buat class diagram UML untuk sistem akademik dengan komponen berikut:

-User sebagai base class (Mahasiswa, Dosen, Admin, CalonMahasiswa)
-Course dengan atribut kode, nama, SKS, prasyarat
-Enrollment yang hubungkan Mahasiswa dan Course
-Schedule dengan hari, jam, ruangan
-Grade untuk nilai mahasiswa Terapkan prinsip SOLID.

Gunakan composition untuk relasi kuat dan aggregation untuk relasi lemah. Output dalam format Mermaid. 

### Hasil AI
classDiagram
    direction TB

    class User {
        <<abstract>>
        # String id
        # String nama
        # String email
        + login()
        + logout()
    }

    class Mahasiswa {
        - String nim
        - String jurusan
        + getMahasiswaInfo()
    }

    class Dosen {
        - String nip
        - String keahlian
        + getDosenInfo()
    }

    class Admin {
        - String role
        + manageSystem()
    }

    class CalonMahasiswa {
        - String noPendaftaran
        + submitRegistration()
    }

    class Course {
        - String kode
        - String nama
        - int sks
        + getCourseDetails()
    }

    class Enrollment {
        - String idEnrollment
        - Date tanggalDaftar
        - String status
        + processEnrollment()
    }

    class Schedule {
        - String hari
        - String jam
        - String ruangan
        + updateSchedule()
    }

    class Grade {
        - double nilaiAngka
        - String nilaiHuruf
        - double bobot
        + calculateFinalGrade()
    }

    %% Inheritance (Penerapan OCP & LSP)
    User <|-- Mahasiswa
    User <|-- Dosen
    User <|-- Admin
    User <|-- CalonMahasiswa

    %% Aggregation (Relasi Lemah: Jadwal atau Prasyarat bisa eksis terpisah dari Course)
    Course o-- Schedule : memiliki jadwal
    Course "*" o-- "*" Course : prasyarat

    %% Composition (Relasi Kuat: Grade tidak memiliki siklus hidup mandiri tanpa Enrollment)
    Enrollment *-- Grade : mencakup

    %% Associations
    Mahasiswa "1" --> "*" Enrollment : melakukan
    Course "1" --> "*" Enrollment : memiliki

### Evaluasi
1. Kelas Payment (Pembayaran) belum ada dalam diagram awal.
2. Beberapa relasi, khususnya antara Course–Schedule dan Enrollment–Grade, memerlukan validasi lebih lanjut.
3. Multiplisitas perlu diperiksa kembali.
4. Visibilitas sudah dicantumkan, namun memerlukan pemeriksaan konsistensi.
5. Prinsip-prinsip SOLID belum terlihat secara memadai hanya dari diagram tersebut.

### Alasan Revisi
Untuk meningkatkan ketepatan dan kelengkapan UML, serta memastikan kesesuaian dengan persyaratan tugas sistem akademik.

---