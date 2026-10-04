import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, field_validator


class LandlordCreate(BaseModel):
    name: str
    contact_info: str
    email: EmailStr


class LandlordUpdate(BaseModel):
    name: str
    contact_info: str
    email: EmailStr


class LandlordOut(BaseModel):
    id: int
    name: str
    contact_info: str
    email: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


LISTING_CODE_PATTERN = re.compile(r"^[A-Z]{2}-\d{4,6}$")  


class ListingCreate(BaseModel):
    address: str
    landlord_id: Optional[int] = None
    listing_code: Optional[str] = None
    available_units: int = 1

    @field_validator("listing_code")
    @classmethod
    def validate_listing_code(cls, v):
        if v is not None and not LISTING_CODE_PATTERN.match(v):
            raise ValueError(
                "listing_code must match the format XX-NNNN (e.g. 'SJ-10234')"
            )
        return v


class ListingUpdate(BaseModel):
    address: str
    landlord_id: Optional[int] = None
    listing_code: Optional[str] = None
    available_units: int = 1

    @field_validator("listing_code")
    @classmethod
    def validate_listing_code(cls, v):
        if v is not None and not LISTING_CODE_PATTERN.match(v):
            raise ValueError(
                "listing_code must match the format XX-NNNN (e.g. 'SJ-10234')"
            )
        return v


class ListingOut(BaseModel):
    id: int
    address: str
    landlord_id: Optional[int]
    listing_code: Optional[str]
    available_units: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True