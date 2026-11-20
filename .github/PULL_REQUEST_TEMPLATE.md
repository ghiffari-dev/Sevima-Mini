## Deskripsi Fitur
<!-- Jelaskan fitur atau perubahan yang diimplementasikan pada PR ini -->

## Isu Terkait
<!-- Cantumkan nomor/link issue, misal: Closes #... -->

## Apa yang Dibantu AI
<!-- Jelaskan bagian kode/test/dokumentasi apa saja yang dibantu AI dan apa yang direvisi secara manual -->

## 3 Prompt Kunci
1. <!-- Prompt kunci 1 -->
2. <!-- Prompt kunci 2 -->
3. <!-- Prompt kunci 3 -->

## Risiko & Limitasi
- **Otorisasi Endpoint KRS**: Parameter `dosen_pa_id` pada endpoint `/api/krs/{nim}/approve` dan `/api/krs/{nim}/revise` saat ini masih dikirim melalui *request body* karena modul autentikasi/JWT belum dihubungkan langsung ke router KRS (idealnya diambil dari identitas login terverifikasi agar tidak dapat dipalsukan).
- **Limitasi Database SQLite**: Uji *pessimistic row lock* (`SELECT ... FOR UPDATE` / `.with_for_update()`) pada modul KRS dan Penjadwalan (`Ruangan -> Dosen`) tidak dapat membuktikan *row-level locking* konkuren secara fisik di SQLite karena SQLite mengabaikan `FOR UPDATE` (harus diverifikasi lanjut pada MySQL atau PostgreSQL).
- **Filter Semester Aktif & Kapasitas Sisi Mahasiswa**: Validasi kapasitas saat mahasiswa mengambil kelas pada `KRSManager` serta pembatasan semester aktif pada seluruh endpoint penjadwalan masih menggunakan nilai default `"20251"` / parameter query dan perlu diperketat pada integrasi akhir.

## Cara Uji
Jalankan seluruh test suite (Unit, Integration, Property-Based Testing, dan API TestClient):
```powershell
$env:PYTHONPATH = "backend"
.\venv\Scripts\pytest.exe backend/test_models_and_schemas.py backend/test_pmb.py backend/tests/test_krs_property.py backend/tests/test_krs_api.py backend/tests/test_schedule.py -v
```

## AI Usage Log & OPAR
- [x] Entri AI Usage Log dan refleksi **OPAR** (*Observe, Plan, Act, Reflect*) telah diperbarui di [`backend/ai-usage-log.md`](backend/ai-usage-log.md) dan [`repo-structure/prompts/ai-usage-log.md`](repo-structure/prompts/ai-usage-log.md).
- [x] Keputusan arsitektur telah dicatat di [`repo-structure/docs/ADR-architecture-decisions.md`](repo-structure/docs/ADR-architecture-decisions.md).
