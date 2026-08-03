import uuid
from datetime import datetime
from typing import List, Optional
from sqlalchemy import String, Text, DateTime, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base

class Company(Base):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    domain: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    industry: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    company_size: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    website_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    hq_phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    linkedin_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    twitter_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    extra_metadata: Mapped[Optional[dict]] = mapped_column(JSONB, default={}, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    leads: Mapped[List["Lead"]] = relationship("Lead", back_populates="company", cascade="all, delete-orphan")
    technologies: Mapped[List["CompanyTechnology"]] = relationship("CompanyTechnology", back_populates="company", cascade="all, delete-orphan")
