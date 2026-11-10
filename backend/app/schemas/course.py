from pydantic import BaseModel, Field

class ScheduleBase(BaseModel):
    hari: str = Field(..., description="Senin, Selasa, dll")
    jam: str = Field(..., description="08:00 - 10:30")
    ruangan: str = Field(..., description="Lab A, R.101")

class ScheduleResponse(ScheduleBase):
    id: int

    class Config:
        from_attributes = True

class KelasBase(BaseModel):
    id_kelas: str
    nama_kelas: str
    semester: str
    kapasitas: int = Field(..., gt=0)

class KelasCreate(KelasBase):
    course_kode: str

class KelasResponse(KelasBase):
    schedule: list[ScheduleResponse] = []

    class Config:
        from_attributes = True

class CourseBase(BaseModel):
    kode: str = Field(..., min_length=3, max_length=10)
    nama: str
    sks: int = Field(..., ge=1, le=6)

class CourseCreate(CourseBase):
    prasyarat_kode: list[str] = []

class CourseResponse(CourseBase):
    prasyarat: list["CourseResponse"] = []
    kelas: list[KelasResponse] = []

    class Config:
        from_attributes = True

CourseResponse.model_rebuild()
