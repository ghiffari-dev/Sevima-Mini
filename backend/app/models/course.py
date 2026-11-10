from sqlalchemy import Column, String, Integer, ForeignKey, Table
from sqlalchemy.orm import relationship
from app.models.base import Base

# Association table untuk prasyarat course (Many-to-Many self-referential)
course_prerequisites = Table(
    "course_prerequisites",
    Base.metadata,
    Column("course_kode", String, ForeignKey("courses.kode"), primary_key=True),
    Column("prerequisite_kode", String, ForeignKey("courses.kode"), primary_key=True)
)

class Course(Base):
    __tablename__ = "courses"

    kode = Column(String, primary_key=True, index=True)
    nama = Column(String, nullable=False)
    sks = Column(Integer, nullable=False)

    kelas = relationship("Kelas", back_populates="course")
    
    prasyarat = relationship(
        "Course",
        secondary=course_prerequisites,
        primaryjoin=kode == course_prerequisites.c.course_kode,
        secondaryjoin=kode == course_prerequisites.c.prerequisite_kode,
        backref="dependent_courses"
    )

class Kelas(Base):
    __tablename__ = "kelass"

    id_kelas = Column(String, primary_key=True, index=True)
    nama_kelas = Column(String, nullable=False)
    semester = Column(String, nullable=False)
    kapasitas = Column(Integer, nullable=False)
    
    course_kode = Column(String, ForeignKey("courses.kode"), nullable=False)
    dosen_id = Column(String, ForeignKey("dosens.id"), nullable=True)

    course = relationship("Course", back_populates="kelas")
    dosen = relationship("Dosen", back_populates="kelas")
    schedules = relationship("Schedule", back_populates="kelas", cascade="all, delete-orphan")
    enrollments = relationship("Enrollment", back_populates="kelas")

class Schedule(Base):
    __tablename__ = "schedules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    hari = Column(String, nullable=False)
    jam = Column(String, nullable=False)
    ruangan = Column(String, nullable=False)
    
    kelas_id = Column(String, ForeignKey("kelass.id_kelas"), nullable=False)
    kelas = relationship("Kelas", back_populates="schedules")
