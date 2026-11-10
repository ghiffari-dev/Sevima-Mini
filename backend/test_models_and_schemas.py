import pytest
from datetime import date
from app.core.security import get_password_hash, verify_password, create_access_token
from app.schemas.auth import LoginRequest
from app.schemas.course import CourseCreate, KelasCreate
from app.schemas.krs import PendaftaranKRSCreate
from app.schemas.grade import GradeCreate
from app.schemas.payment import VerifyPaymentRequest

def test_security_password_hashing():
    password = "securepassword123"
    hashed = get_password_hash(password)
    assert verify_password(password, hashed) is True
    assert verify_password("wrongpassword", hashed) is False

def test_security_jwt_token():
    token = create_access_token({"sub": "test@sevima.com", "role": "admin"})
    assert isinstance(token, str)
    assert len(token) > 0

def test_login_schema():
    login_data = {"email": "user@sevima.com", "password": "password123"}
    login_req = LoginRequest(**login_data)
    assert login_req.email == "user@sevima.com"
    assert login_req.password == "password123"

def test_course_schema():
    course_data = {"kode": "IF101", "nama": "Pemrograman Berorientasi Objek", "sks": 3}
    course = CourseCreate(**course_data)
    assert course.kode == "IF101"
    assert course.sks == 3

def test_krs_schema():
    krs_data = {"pilihan_matkul_ids": ["IF101-A", "IF102-B"]}
    krs = PendaftaranKRSCreate(**krs_data)
    assert len(krs.pilihan_matkul_ids) == 2

def test_grade_schema():
    grade_data = {"enrollment_id": "ENR-001", "nilaiAngka": 85.5}
    grade = GradeCreate(**grade_data)
    assert grade.nilaiAngka == 85.5

def test_payment_schema():
    pay_data = {"status_bayar": "Lunas"}
    pay = VerifyPaymentRequest(**pay_data)
    assert pay.status_bayar == "Lunas"

