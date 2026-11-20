from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db as get_orm_db
from app.core.security import create_access_token, verify_password
from app.models.user import Admin, User
from app.schemas.auth import LoginRequest, Token

router = APIRouter()


@router.post("/login", response_model=Token, status_code=status.HTTP_200_OK)
def login(body: LoginRequest, db: Session = Depends(get_orm_db)) -> Token:
    """Mengautentikasi pengguna (termasuk Admin Akademik demo) dan menerbitkan JWT Bearer token."""
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
        token = create_access_token({"sub": user.email, "role": role})
        return Token(access_token=token)

    if (
        body.email == settings.ADMIN_DEMO_EMAIL
        and body.password == settings.ADMIN_DEMO_PASSWORD
    ):
        token = create_access_token({"sub": body.email, "role": "admin_akademik"})
        return Token(access_token=token)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Email atau password salah",
    )
