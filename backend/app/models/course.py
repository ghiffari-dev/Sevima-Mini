from sqlalchemy import Column, String, Integer, ForeignKey, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base

# Association table untuk prasyarat course (Many-to-Many self-referential)
course_prerequisites = Table(
    "course_prerequisites",
    Base.metadata,
    Column("course_kode", String(20), ForeignKey("courses.kode"), primary_key=True),
    Column("prerequisite_kode", String(20), ForeignKey("courses.kode"), primary_key=True)
)

class Course(Base):
    __tablename__ = "courses"

    kode: Mapped[str] = mapped_column(String(20), primary_key=True, index=True)
    nama: Mapped[str] = mapped_column(String(150), nullable=False)
    sks: Mapped[int] = mapped_column(Integer, nullable=False)

    kelas: Mapped[list["Kelas"]] = relationship("Kelas", back_populates="course")
    
    prasyarat: Mapped[list["Course"]] = relationship(
        "Course",
        secondary=course_prerequisites,
        primaryjoin=kode == course_prerequisites.c.course_kode,
        secondaryjoin=kode == course_prerequisites.c.prerequisite_kode,
        backref="dependent_courses"
    )

class Kelas(Base):
    __tablename__ = "kelass"

    id_kelas: Mapped[str] = mapped_column(String(50), primary_key=True, index=True)
    nama_kelas: Mapped[str] = mapped_column(String(100), nullable=False)
    semester: Mapped[str] = mapped_column(String(20), nullable=False)
    kapasitas: Mapped[int] = mapped_column(Integer, nullable=False)
    
    course_kode: Mapped[str] = mapped_column(String(20), ForeignKey("courses.kode"), nullable=False)
    dosen_id: Mapped[str | None] = mapped_column(String(50), ForeignKey("dosens.id"), nullable=True)

    course: Mapped["Course"] = relationship("Course", back_populates="kelas")
    dosen: Mapped["Dosen | None"] = relationship("Dosen", back_populates="kelas")
    schedules: Mapped[list["Schedule"]] = relationship("Schedule", back_populates="kelas", cascade="all, delete-orphan")
    enrollments: Mapped[list["Enrollment"]] = relationship("Enrollment", back_populates="kelas")

class Schedule(Base):
    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hari: Mapped[str] = mapped_column(String(20), nullable=False)
    jam: Mapped[str] = mapped_column(String(30), nullable=False)  # Contoh: "08:00-10:00"
    jam_mulai: Mapped[str | None] = mapped_column(String(10), nullable=True)  # Contoh: "08:00"
    jam_selesai: Mapped[str | None] = mapped_column(String(10), nullable=True)  # Contoh: "10:00"
    ruangan: Mapped[str] = mapped_column(String(50), nullable=False)
    
    kelas_id: Mapped[str] = mapped_column(String(50), ForeignKey("kelass.id_kelas"), nullable=False)
    kelas: Mapped["Kelas"] = relationship("Kelas", back_populates="schedules")

