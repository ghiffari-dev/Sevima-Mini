from pydantic import BaseModel, EmailStr, Field

class ProgramStudiBase(BaseModel):
    kode: str = Field(..., min_length=3, max_length=3)
    nama: str
    fakultas: str

class ProgramStudiCreate(ProgramStudiBase):
    pass

class ProgramStudiResponse(ProgramStudiBase):
    id: int

    class Config:
        from_attributes = True
