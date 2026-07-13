import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)        # stored plain, encrypt in Phase 8
    hashed_password: Mapped[str] = mapped_column(String, nullable=True)
    phone: Mapped[str] = mapped_column(String(255), nullable=True)        # will be encrypted when SMS added

    alert_email: Mapped[bool] = mapped_column(Boolean, default=False)
    alert_sms: Mapped[bool] = mapped_column(Boolean, default=False)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    mfa_secret: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    accounts: Mapped[list["LinkedAccount"]] = relationship(back_populates="user", cascade="all, delete")
    subscriptions: Mapped[list["Subscription"]] = relationship(back_populates="user", cascade="all, delete")
    alerts: Mapped[list["Alert"]] = relationship(back_populates="user", cascade="all, delete")
    def __repr__(self):
        return f"<User id={self.id} email={self.email}>"

class LinkedAccount(Base):
    __tablename__ = "linked_accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    access_token: Mapped[str] = mapped_column(String(1024), nullable=False)   # always encrypted
    item_id: Mapped[str] = mapped_column(String(256), nullable=True, index=True)
    institution_name: Mapped[str] = mapped_column(String, nullable=True)
    # "active" | "login_required" | "pending_expiration" | "revoked" — driven by ITEM webhooks
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", server_default="active")
    # Plaid /transactions/sync cursor — None means no sync has completed yet
    sync_cursor: Mapped[str | None] = mapped_column(String(256), nullable=True)
    linked_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="accounts")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="account", cascade="all, delete")


class Transaction(Base):
    """Local copy of Plaid transactions, kept fresh via /transactions/sync.

    positive amount = money out, matching Plaid's convention.
    """

    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_transactions_user_date", "user_id", "date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plaid_transaction_id: Mapped[str] = mapped_column(String(256), unique=True, index=True, nullable=False)
    linked_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("linked_accounts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    merchant_name: Mapped[str | None] = mapped_column(String, nullable=True)
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    pending: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    account: Mapped["LinkedAccount"] = relationship(back_populates="transactions")


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        # Mirrors the index created in migration c3d4e5f6a7b8 so that schemas
        # built from metadata (tests) enforce the same constraint as production.
        Index("ix_subscriptions_user_merchant_source", "user_id", text("lower(merchant)"), "source", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    # Which bank produced this subscription (NULL for manual subs and legacy
    # rows) — lets unlink deactivate only that account's subscriptions.
    linked_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("linked_accounts.id", ondelete="SET NULL"), index=True, nullable=True
    )
    merchant: Mapped[str] = mapped_column(String, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    frequency: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=True)
    last_charged: Mapped[date] = mapped_column(Date, nullable=True)
    next_expected: Mapped[date] = mapped_column(Date, nullable=True)
    occurrences: Mapped[int] = mapped_column(Integer, default=1)
    source: Mapped[str] = mapped_column(String, default="plaid")    # "plaid" or "manual"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship(back_populates="subscriptions")
    alerts: Mapped[list["Alert"]] = relationship(back_populates="subscription", cascade="all, delete")


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship()


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    subscription_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="CASCADE"), index=True, nullable=True)

    message: Mapped[str] = mapped_column(String, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="alerts")
    subscription: Mapped["Subscription"] = relationship(back_populates="alerts")
