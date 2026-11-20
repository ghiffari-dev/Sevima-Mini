import os
from datetime import datetime, timedelta, timezone
from typing import Any
from fastapi import Header, HTTPException, status
from jose import JWTError, jwt
import bcrypt

# Secret key untuk JWT (menggunakan environment variable jika ada, dengan fallback default untuk development/testing)
SECRET_KEY = os.getenv("SECRET_KEY", "sevima-mini-secret-key-very-secure")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def get_password_hash(password: str) -> str:
    pwd_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(pwd_bytes, salt)
    return hashed.decode('utf-8')

def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
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


def require_admin_akademik(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Dependency RBAC FastAPI: hanya mengizinkan role admin / admin_akademik."""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autentikasi Admin Akademik diperlukan (Bearer token)",
            headers={"WWW-Authenticate": "Bearer"},
        )
    parts = authorization.strip().split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Format header Authorization harus 'Bearer <token>'",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_access_token(parts[1].strip())
    role = str(payload.get("role") or "").strip().lower()
    if role not in {"admin", "admin_akademik"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak: endpoint khusus Admin Akademik",
        )
    return payload



