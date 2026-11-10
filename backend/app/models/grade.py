from sqlalchemy import Column, Float, String, ForeignKey
from sqlalchemy.orm import relationship
from app.models.base import Base

class Grade(Base):
    __tablename__ = "grades"

    enrollment_id = Column(String, ForeignKey("enrollments.id_enrollment"), primary_key=True)
    nilaiAngka = Column(Float, nullable=False)
    nilaiHuruf = Column(String, nullable=False)
    bobot = Column(Float, nullable=False)

    enrollment = relationship("Enrollment", back_populates="grade")
