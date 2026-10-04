import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from db import Base


class Landlord(Base):
    __tablename__ = "landlords"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)              # primary field
    contact_info = Column(String(255), nullable=False)       # secondary field
    email = Column(String(255), unique=True, nullable=False)  # unique field
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    listings = relationship("Listing", back_populates="landlord")


class Listing(Base):
    __tablename__ = "listings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    address = Column(String(255), nullable=False)              # primary field
    listing_code = Column(String(50), unique=True, nullable=True)  # unique field
    available_units = Column(Integer, nullable=False, default=1)   # numeric, defaulted
    landlord_id = Column(Integer, ForeignKey("landlords.id"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


    landlord_name = Column(String(255), nullable=True)

    landlord = relationship("Landlord", back_populates="listings")
    events = relationship("ListingEvent")


class ListingEvent(Base):
    """Test data only, per HW4's assignment -- the N+1 demonstration table."""
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