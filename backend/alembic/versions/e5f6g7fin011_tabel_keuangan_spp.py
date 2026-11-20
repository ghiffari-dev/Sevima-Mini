"""tambah tabel payment_method, billing, payment, dan kolom biaya_spp (minggu 11)

Revision ID: e5f6g7fin011
Revises: d4e5f6grd010
Create Date: 2026-11-20 16:45:00.000000

"""
from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e5f6g7fin011"
down_revision: Union[str, Sequence[str], None] = "d4e5f6grd010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Membuat tabel keuangan (payment_method, billing, payment) dan kolom program_studi.biaya_spp."""
    with op.batch_alter_table("program_studi") as batch_op:
        batch_op.add_column(
            sa.Column("biaya_spp", sa.Numeric(precision=14, scale=2), nullable=True)
        )

    op.create_table(
        "payment_method",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_payment_method_code"), "payment_method", ["code"], unique=True
    )

    now_utc = datetime.now(timezone.utc)
    pm_tbl = sa.table(
        "payment_method",
        sa.column("code", sa.String(length=40)),
        sa.column("name", sa.String(length=100)),
        sa.column("provider", sa.String(length=50)),
        sa.column("is_active", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        pm_tbl,
        [
            {
                "code": "VA_BCA",
                "name": "Virtual Account BCA",
                "provider": "BCA",
                "is_active": True,
                "created_at": now_utc,
            },
            {
                "code": "VA_BNI",
                "name": "Virtual Account BNI",
                "provider": "BNI",
                "is_active": True,
                "created_at": now_utc,
            },
            {
                "code": "QRIS",
                "name": "QRIS Nasional",
                "provider": "QRIS",
                "is_active": True,
                "created_at": now_utc,
            },
            {
                "code": "BANK_TRANSFER",
                "name": "Transfer Bank Manual",
                "provider": "BANK",
                "is_active": True,
                "created_at": now_utc,
            },
            {
                "code": "MANUAL_CASH",
                "name": "Loket Keuangan Kampus",
                "provider": "CAMPUS",
                "is_active": True,
                "created_at": now_utc,
            },
        ],
    )

    op.create_table(
        "billing",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("invoice_number", sa.String(length=60), nullable=False),
        sa.Column("nim", sa.String(length=20), nullable=False),
        sa.Column("semester", sa.String(length=10), nullable=False),
        sa.Column("program_studi_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column(
            "late_fee",
            sa.Numeric(precision=14, scale=2),
            server_default="0.00",
            nullable=False,
        ),
        sa.Column(
            "amount_paid",
            sa.Numeric(precision=14, scale=2),
            server_default="0.00",
            nullable=False,
        ),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "unpaid",
                "partial",
                "paid",
                "overdue",
                name="billingstatus",
            ),
            server_default="unpaid",
            nullable=False,
        ),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_reminder_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_billing_amount_positive"),
        sa.CheckConstraint("late_fee >= 0", name="ck_billing_late_fee_non_negative"),
        sa.CheckConstraint("amount_paid >= 0", name="ck_billing_amount_paid_non_negative"),
        sa.ForeignKeyConstraint(["nim"], ["calon_mahasiswa.nim"]),
        sa.ForeignKeyConstraint(["program_studi_id"], ["program_studi.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nim", "semester", name="uq_billing_nim_semester"),
    )
    op.create_index(
        op.f("ix_billing_invoice_number"), "billing", ["invoice_number"], unique=True
    )
    op.create_index(op.f("ix_billing_nim"), "billing", ["nim"], unique=False)
    op.create_index(op.f("ix_billing_semester"), "billing", ["semester"], unique=False)
    op.create_index(
        op.f("ix_billing_program_studi_id"),
        "billing",
        ["program_studi_id"],
        unique=False,
    )
    op.create_index(op.f("ix_billing_due_date"), "billing", ["due_date"], unique=False)
    op.create_index(op.f("ix_billing_status"), "billing", ["status"], unique=False)

    op.create_table(
        "payment",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("billing_id", sa.Integer(), nullable=False),
        sa.Column("payment_method_id", sa.Integer(), nullable=False),
        sa.Column("transaction_id", sa.String(length=100), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column(
            "status", sa.String(length=20), server_default="success", nullable=False
        ),
        sa.Column(
            "source", sa.String(length=20), server_default="manual", nullable=False
        ),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.String(length=300), nullable=True),
        sa.Column("raw_payload", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_payment_amount_positive"),
        sa.CheckConstraint(
            "status IN ('pending', 'success', 'failed', 'refunded')",
            name="ck_payment_status_valid",
        ),
        sa.ForeignKeyConstraint(["billing_id"], ["billing.id"]),
        sa.ForeignKeyConstraint(["payment_method_id"], ["payment_method.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_payment_billing_id"), "payment", ["billing_id"], unique=False
    )
    op.create_index(
        op.f("ix_payment_payment_method_id"),
        "payment",
        ["payment_method_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_payment_transaction_id"), "payment", ["transaction_id"], unique=True
    )


def downgrade() -> None:
    """Menghapus tabel payment, billing, payment_method, dan kolom program_studi.biaya_spp."""
    op.drop_index(op.f("ix_payment_transaction_id"), table_name="payment")
    op.drop_index(op.f("ix_payment_payment_method_id"), table_name="payment")
    op.drop_index(op.f("ix_payment_billing_id"), table_name="payment")
    op.drop_table("payment")

    op.drop_index(op.f("ix_billing_status"), table_name="billing")
    op.drop_index(op.f("ix_billing_due_date"), table_name="billing")
    op.drop_index(op.f("ix_billing_program_studi_id"), table_name="billing")
    op.drop_index(op.f("ix_billing_semester"), table_name="billing")
    op.drop_index(op.f("ix_billing_nim"), table_name="billing")
    op.drop_index(op.f("ix_billing_invoice_number"), table_name="billing")
    op.drop_table("billing")

    op.drop_index(op.f("ix_payment_method_code"), table_name="payment_method")
    op.drop_table("payment_method")

    with op.batch_alter_table("program_studi") as batch_op:
        batch_op.drop_column("biaya_spp")
