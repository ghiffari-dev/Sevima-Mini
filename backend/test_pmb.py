import pytest
from fastapi.testclient import TestClient
from datetime import datetime

import sqlite3
import os

from app.main import app, DB_PATH, get_db

# Setup test database
TEST_DB = "backend/pmb_test.db"

@pytest.fixture(autouse=True)
def setup_db():
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    
    conn = sqlite3.connect(TEST_DB)
    cursor = conn.cursor()
    cursor.executescript("""
        CREATE TABLE program_studi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kode VARCHAR(3) NOT NULL UNIQUE,
            nama VARCHAR(100) NOT NULL,
            fakultas VARCHAR(100) NOT NULL
        );
        CREATE TABLE jalur_masuk (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nama VARCHAR(50) NOT NULL UNIQUE
        );
        CREATE TABLE calon_mahasiswa (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nama_lengkap VARCHAR(150) NOT NULL,
            email VARCHAR(150) NOT NULL UNIQUE,
            phone VARCHAR(20) NOT NULL,
            tanggal_lahir DATE NOT NULL,
            alamat TEXT,
            program_studi_id INTEGER NOT NULL,
            jalur_masuk_id INTEGER NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            nim VARCHAR(20) UNIQUE,
            created_at DATETIME NOT NULL,
            approved_at DATETIME,
            FOREIGN KEY (program_studi_id) REFERENCES program_studi (id),
            FOREIGN KEY (jalur_masuk_id) REFERENCES jalur_masuk (id)
        );
        INSERT INTO program_studi (kode, nama, fakultas) VALUES ('001', 'Teknik Informatika', 'Fakultas Teknik');
        INSERT INTO jalur_masuk (nama) VALUES ('SNBP'), ('SNBT'), ('Mandiri');
    """)
    conn.commit()
    conn.close()

    # Override dependency
    def override_get_db():
        conn = sqlite3.connect(TEST_DB)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.clear()

client = TestClient(app)

def test_register_success():
    response = client.post("/api/pmb/register", json={
        "nama_lengkap": "Budi Santoso",
        "email": "budi@example.com",
        "phone": "081234567890",
        "tanggal_lahir": "2004-05-12",
        "alamat": "Jl. Merdeka No. 10",
        "program_studi_id": 1,
        "jalur_masuk_id": 1
    })
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "pending"

def test_register_duplicate_email():
    payload = {
        "nama_lengkap": "Budi Santoso",
        "email": "budi@example.com",
        "phone": "081234567890",
        "tanggal_lahir": "2004-05-12",
        "alamat": "Jl. Merdeka No. 10",
        "program_studi_id": 1,
        "jalur_masuk_id": 1
    }
    client.post("/api/pmb/register", json=payload)
    response = client.post("/api/pmb/register", json=payload)
    assert response.status_code == 409

def test_invalid_phone_format():
    response = client.post("/api/pmb/register", json={
        "nama_lengkap": "Budi Santoso",
        "email": "budi@example.com",
        "phone": "12345", # Invalid phone
        "tanggal_lahir": "2004-05-12",
        "program_studi_id": 1,
        "jalur_masuk_id": 1
    })
    assert response.status_code == 422

def test_approve_generate_nim():
    reg = client.post("/api/pmb/register", json={
        "nama_lengkap": "Siti Aminah",
        "email": "siti@example.com",
        "phone": "089876543210",
        "tanggal_lahir": "2005-01-01",
        "program_studi_id": 1,
        "jalur_masuk_id": 2
    })
    m_id = reg.json()["id"]
    
    approve_res = client.put(f"/api/pmb/approve/{m_id}")
    assert approve_res.status_code == 200
    res_data = approve_res.json()
    assert "nim" in res_data
    assert res_data["status"] == "approved"
    expected_prefix = f"{datetime.utcnow().year}001-"
    assert res_data["nim"].startswith(expected_prefix)

def test_approve_idempotent():
    reg = client.post("/api/pmb/register", json={
        "nama_lengkap": "Joko Widodo",
        "email": "joko@example.com",
        "phone": "081122334455",
        "tanggal_lahir": "2003-08-17",
        "program_studi_id": 1,
        "jalur_masuk_id": 3
    })
    m_id = reg.json()["id"]
    
    first_approve = client.put(f"/api/pmb/approve/{m_id}").json()
    nim_1 = first_approve["nim"]
    
    second_approve = client.put(f"/api/pmb/approve/{m_id}").json()
    nim_2 = second_approve["nim"]
    
    assert nim_1 == nim_2
