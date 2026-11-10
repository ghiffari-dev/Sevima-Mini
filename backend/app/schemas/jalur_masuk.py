from pydantic import BaseModel, Field

class JalurMasukBase(BaseModel):
    nama: str = Field(..., description="Nama jalur masuk seperti SNBP, SNBT, Mandiri")

class JalurMasukCreate(JalurMasukBase):
    pass

class JalurMasukResponse(JalurMasukBase):
    id: int

    class Config:
        from_attributes = True
