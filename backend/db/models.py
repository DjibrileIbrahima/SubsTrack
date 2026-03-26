import uuid, enum
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime, date
from sqlalchemy import String, Float, Integer, DateTime, Date, ForeignKey, func, Boolean, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from db.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)        # stored plain, encrypt in Phase 8
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    phone: Mapped[str] = mapped_column(String(255), nullable=True)        # will be encrypted when SMS added

    alert_email: Mapped[bool] = mapped_column(Boolean, default=False)
    alert_sms: Mapped[bool] = mapped_column(Boolean, default=False)
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
    institution_name: Mapped[str] = mapped_column(String, nullable=True)
    linked_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="accounts")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    merchant: Mapped[str] = mapped_column(String, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
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
