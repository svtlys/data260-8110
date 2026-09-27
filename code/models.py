"""
models.py

SQLAlchemy ORM models: the primary domain entity (rental listings),
a related test-data table (listing_events, for the N+1 exercise),
plus users and sessions tables for authentication.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from db import Base


class Listing(Base):
    __tablename__ = "listings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    address = Column(String(255), nullable=False)          # primary field
    landlord_name = Column(String(255), nullable=False)    # secondary field

    events = relationship("ListingEvent")


class ListingEvent(Base):
    """
    Test data only for now, per the assignment -- a minimal related table
    just to create the N+1 pattern. A full related entity with its own
    CRUD comes in a later homework.
    """
    __tablename__ = "listing_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    listing_id = Column(Integer, ForeignKey("listings.id"), nullable=False)
    note = Column(String(255), nullable=False)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)

    sessions = relationship("Session", back_populates="user")


class Session(Base):
    __tablename__ = "sessions"

    id = Column(String(64), primary_key=True, default=lambda: uuid.uuid4().hex)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc) + timedelta(hours=2),
    )

    user = relationship("User", back_populates="sessions")