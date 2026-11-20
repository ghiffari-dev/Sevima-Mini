from app.models.base import Base
from app.models.program_studi import ProgramStudi
from app.models.jalur_masuk import JalurMasuk
from app.models.calon_mahasiswa import CalonMahasiswa
from app.models.krs import (
    Actor,
    ForbiddenError,
    KRS,
    KRSBillingBlockedError,
    KRSDetail,
    KRSError,
    KRSForbiddenError,
    KRSLockedError,
    KRSLog,
    KRSStatus,
    MataKuliah,
    Notifikasi,
    StateTransitionError,
    TRANSITIONS,
    TransitionError,
    prerequisite,
)
from app.models.user import User, Mahasiswa, Dosen, Admin
from app.models.course import Course, Kelas, Schedule
from app.models.pendaftaran import Pendaftaran, PendaftaranPMB, PendaftaranKRS
from app.models.enrollment import Enrollment
from app.models.grade import (
    AlasanWajibError,
    DEFAULT_SKALA_NILAI,
    Grade,
    GradeError,
    GradeForbiddenError,
    GradeHistory,
    GradeNotFoundError,
    HurufTidakValidError,
    PresensiKurangError,
    RIWAYAT_NILAI_VIEW_SQL,
    SkalaNilai,
    ensure_riwayat_nilai_view,
    seed_skala_nilai,
)
from app.models.payment import Payment, PembayaranPMB, PembayaranKRS
from app.models.finance import (
    BILLING_TRANSITIONS,
    Billing,
    BillingAlreadyPaidError,
    BillingNotFoundError,
    BillingStatus,
    DEFAULT_PAYMENT_METHODS,
    FinanceError,
    InvalidPaymentAmountError,
    PaymentMethod,
    PaymentMethodNotFoundError,
    PaymentTransaction,
    WebhookSignatureError,
    seed_payment_methods,
)
from app.models.schedule import (
    Dosen as DosenJadwal,
    HARI_MAP,
    Jadwal,
    JadwalKuliah,
    Kelas as KelasJadwal,
    Outbox,
    OutboxStatus,
    Ruangan,
    ScheduleCapacityError,
    ScheduleConflictError,
    ScheduleError,
    ScheduleNotFoundError,
    format_hari,
    normalize_hari,
)
from app.models.attendance import (
    AttendanceError,
    AttendanceForbiddenError,
    AttendanceNotFoundError,
    AttendanceRecord,
    AttendanceSession,
    AttendanceStatus,
    DuplicateAttendanceError,
    GeolocationError,
    GeolocationRequiredError,
    NotEnrolledError,
    OutsideAttendanceWindowError,
    QRExpiredError,
    QRTokenInvalidError,
    RateLimitExceededError,
    SessionAlreadyOpenError,
    SessionStatus,
)

