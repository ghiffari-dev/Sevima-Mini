from pydantic import BaseModel, ConfigDict, EmailStr, Field

class UserBase(BaseModel):
    nama: str = Field(..., min_length=2, max_length=150)
    email: EmailStr

class MahasiswaResponse(UserBase):
    id: str
    nim: str
    jurusan: str
    
    model_config = ConfigDict(from_attributes=True)

class DosenResponse(UserBase):
    id: str
    nip: str
    keahlian: str

    model_config = ConfigDict(from_attributes=True)

class AdminResponse(UserBase):
    id: str
    role: str

    model_config = ConfigDict(from_attributes=True)
