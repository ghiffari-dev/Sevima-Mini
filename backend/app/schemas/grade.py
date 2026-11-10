from pydantic import BaseModel, Field

class GradeCreate(BaseModel):
    enrollment_id: str
    nilaiAngka: float = Field(..., ge=0.0, le=100.0)

class GradeResponse(BaseModel):
    nilaiAngka: float
    nilaiHuruf: str
    bobot: float

    class Config:
        from_attributes = True

class KHSResponse(BaseModel):
    mahasiswa_id: str
    semester: str
    grades: list[dict]
    ips: float
    total_sks: int
