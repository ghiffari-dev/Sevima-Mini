from sqlalchemy import Float, String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base

class Grade(Base):
    __tablename__ = "grades"

    enrollment_id: Mapped[str] = mapped_column(String(50), ForeignKey("enrollments.id_enrollment"), primary_key=True)
    nilaiAngka: Mapped[float] = mapped_column(Float, nullable=False)
    nilaiHuruf: Mapped[str] = mapped_column(String(5), nullable=False)
    bobot: Mapped[float] = mapped_column(Float, nullable=False)

    enrollment: Mapped["Enrollment"] = relationship("Enrollment", back_populates="grade")

