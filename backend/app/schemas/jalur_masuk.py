from pydantic import BaseModel, ConfigDict, Field

class JalurMasukBase(BaseModel):
    nama: str = Field(..., description="Nama jalur masuk seperti SNBP, SNBT, Mandiri")

class JalurMasukCreate(JalurMasukBase):
    pass

class JalurMasukResponse(JalurMasukBase):
    id: int

    model_config = ConfigDict(from_attributes=True)
