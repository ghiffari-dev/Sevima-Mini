from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db as get_orm_db
from app.core.security import create_access_token, verify_password
from app.models.schedule import Dosen as DosenJadwal
from app.models.user import Admin, Dosen as DosenUser, User
from app.schemas.auth import LoginRequest, Token

router = APIRouter()


@router.post("/login", response_model=Token, status_code=status.HTTP_200_OK)
def login(body: LoginRequest, db: Session = Depends(get_orm_db)) -> Token:
    """Mengautentikasi pengguna (User DB, Admin Akademik demo, atau Dosen demo) dan menerbitkan JWT."""
    if inspect(db.get_bind()).has_table(User.__tablename__):
        user = db.scalars(select(User).where(User.email == body.email)).first()
        if user is not None:
            if not verify_password(body.password, user.hashed_password):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Email atau password salah",
                )
            role = (
                user.admin_role
                if isinstance(user, Admin) and user.admin_role
                else user.role
            )
            claims: dict[str, object] = {"sub": user.email, "role": role}
            if isinstance(user, DosenUser) or str(role).strip().lower() == "dosen":
                nip = getattr(user, "nip", None)
                if nip:
                    claims["nidn"] = nip
                    dosen_jadwal = db.scalars(
                        select(DosenJadwal).where(DosenJadwal.nidn == nip)
                    ).first()
                    if dosen_jadwal is not None:
                        claims["dosen_id"] = dosen_jadwal.id
            token = create_access_token(claims)
            return Token(access_token=token)

    if (
        body.email == settings.ADMIN_DEMO_EMAIL
        and body.password == settings.ADMIN_DEMO_PASSWORD
    ):
        token = create_access_token({"sub": body.email, "role": "admin_akademik"})
        return Token(access_token=token)

    if (
        body.email == settings.DOSEN_DEMO_EMAIL
        and body.password == settings.DOSEN_DEMO_PASSWORD
    ):
        dosen_jadwal = db.scalars(
            select(DosenJadwal).where(DosenJadwal.nidn == "00100101")
        ).first()
        if dosen_jadwal is None:
            dosen_jadwal = DosenJadwal(nidn="00100101", nama="Dr. Pengampu Demo")
            db.add(dosen_jadwal)
            db.commit()
            db.refresh(dosen_jadwal)
        token = create_access_token(
            {
                "sub": body.email,
                "role": "dosen",
                "dosen_id": dosen_jadwal.id,
                "nidn": dosen_jadwal.nidn,
            }
        )
        return Token(access_token=token)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Email atau password salah",
    )
