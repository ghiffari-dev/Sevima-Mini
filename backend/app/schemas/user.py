from pydantic import BaseModel, EmailStr, Field

class UserBase(BaseModel):
    nama: str = Field(..., min_length=2, max_length=150)
    email: EmailStr

class MahasiswaResponse(UserBase):
    id: str
    nim: str
    jurusan: str
    
    class Config:
        from_attributes = True

class DosenResponse(UserBase):
    id: str
    nip: str
    keahlian: str

    class Config:
        from_attributes = True

class AdminResponse(UserBase):
    id: str
    role: str

    class Config:
        from_attributes = True
