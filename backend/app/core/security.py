import os
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from fastapi import Depends, Header, HTTPException, status
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db as get_orm_db
from app.models.schedule import Dosen as DosenJadwal

# Secret key untuk JWT (menggunakan environment variable jika ada, dengan fallback default untuk development/testing)
SECRET_KEY = os.getenv("SECRET_KEY", "sevima-mini-secret-key-very-secure")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def get_password_hash(password: str) -> str:
    pwd_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(pwd_bytes, salt)
    return hashed.decode("utf-8")


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> dict[str, Any]:
    """Memverifikasi dan mendekode JWT access token."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return dict(payload)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token autentikasi tidak valid atau kedaluwarsa",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def _extract_bearer_payload(
    authorization: str | None,
    *,
    required_message: str,
) -> dict[str, Any]:
    """Mengekstrak dan memverifikasi payload JWT dari header Authorization Bearer."""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=required_message,
            headers={"WWW-Authenticate": "Bearer"},
        )
    parts = authorization.strip().split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Format header Authorization harus 'Bearer <token>'",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return decode_access_token(parts[1].strip())


def require_admin_akademik(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Dependency RBAC FastAPI: hanya mengizinkan role admin / admin_akademik."""
    payload = _extract_bearer_payload(
        authorization,
        required_message="Autentikasi Admin Akademik diperlukan (Bearer token)",
    )
    role = str(payload.get("role") or "").strip().lower()
    if role not in {"admin", "admin_akademik"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak: endpoint khusus Admin Akademik",
        )
    return payload


def get_current_dosen(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_orm_db),
) -> DosenJadwal:
    """Dependency FastAPI: mengambil entitas Dosen terautentikasi dari JWT Bearer token."""
    payload = _extract_bearer_payload(
        authorization,
        required_message="Autentikasi Dosen diperlukan (Bearer token)",
    )
    role = str(payload.get("role") or "").strip().lower()
    if role != "dosen":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak: endpoint khusus Dosen Pengampu",
        )

    dosen: DosenJadwal | None = None
    raw_dosen_id = payload.get("dosen_id")
    if raw_dosen_id is not None:
        try:
            dosen = db.get(DosenJadwal, int(raw_dosen_id))
        except (TypeError, ValueError):
            dosen = None

    if dosen is None:
        nidn = str(payload.get("nidn") or "").strip()
        if nidn:
            dosen = db.scalars(
                select(DosenJadwal).where(DosenJadwal.nidn == nidn)
            ).first()

    if dosen is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identitas dosen pada token tidak ditemukan di master dosen",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return dosen


def get_current_dosen_or_admin(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Dependency RBAC FastAPI: mengizinkan Dosen Pengampu maupun Admin Akademik."""
    payload = _extract_bearer_payload(
        authorization,
        required_message="Autentikasi Dosen atau Admin Akademik diperlukan (Bearer token)",
    )
    role = str(payload.get("role") or "").strip().lower()
    if role not in {"dosen", "admin", "admin_akademik"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak: endpoint khusus Dosen atau Admin Akademik",
        )
    return payload


def get_optional_bearer_payload(
    authorization: str | None = Header(default=None),
) -> dict[str, Any] | None:
    """Mendekode Bearer token bila header Authorization dikirim; None jika tanpa header."""
    if not authorization or not authorization.strip():
        return None
    return _extract_bearer_payload(
        authorization,
        required_message="Autentikasi Bearer token tidak valid",
    )

