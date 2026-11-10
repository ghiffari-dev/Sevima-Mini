import sqlite3
import datetime

conn = sqlite3.connect("pmb_pure.db")
cursor = conn.cursor()

cursor.executescript("""
CREATE TABLE IF NOT EXISTS program_studi (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kode VARCHAR(3) NOT NULL UNIQUE,
    nama VARCHAR(100) NOT NULL,
    fakultas VARCHAR(100) NOT NULL
);

CREATE TABLE IF NOT EXISTS jalur_masuk (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nama VARCHAR(50) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS calon_mahasiswa (
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
""")

cursor.execute("INSERT OR IGNORE INTO program_studi (kode, nama, fakultas) VALUES ('001', 'Teknik Informatika', 'Fakultas Teknik');")
cursor.execute("INSERT OR IGNORE INTO jalur_masuk (nama) VALUES ('SNBP'), ('SNBT'), ('Mandiri');")
conn.commit()
conn.close()
print("Pure SQLite Schema & Seed Data Created Successfully!")

import sqlite3
import datetime
from sqlalchemy import create_engine, String, DateTime, Date, ForeignKey, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

class Base(DeclarativeBase):
    pass

class ProgramStudi(Base):
    __tablename__ = "program_studi"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kode: Mapped[str] = mapped_column(String(3), unique=True, nullable=False, index=True)
    nama: Mapped[str] = mapped_column(String(100), nullable=False)
    fakultas: Mapped[str] = mapped_column(String(100), nullable=False)

class JalurMasuk(Base):
    __tablename__ = "jalur_masuk"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    nama: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)

class CalonMahasiswa(Base):
    __tablename__ = "calon_mahasiswa"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    nama_lengkap: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str] = mapped_column(String(150), unique=True, nullable=False, index=True)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    tanggal_lahir: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    alamat: Mapped[str | None] = mapped_column(Text, nullable=True)
    program_studi_id: Mapped[int] = mapped_column(ForeignKey("program_studi.id"), nullable=False)
    jalur_masuk_id: Mapped[int] = mapped_column(ForeignKey("jalur_masuk.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    nim: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    approved_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)

engine = create_engine("sqlite:///./pmb_test.db", echo=False)
Base.metadata.create_all(engine)
print("Database tables created successfully!")
