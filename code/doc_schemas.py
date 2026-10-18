from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ListingStatus(str, Enum):
    active = "active"
    pending = "pending"
    rented = "rented"
    withdrawn = "withdrawn"


class PropertyType(str, Enum):
    studio = "studio"
    one_bedroom = "one_bedroom"
    two_bedroom = "two_bedroom"
    three_plus = "three_plus"


def _clean_title(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("title must not be blank")
    return v


class ListingDocCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(default=None, max_length=2000)
    status: ListingStatus = ListingStatus.active
    property_type: PropertyType
    available_from: date

    _strip_title = field_validator("title")(_clean_title)


class ListingDocUpdate(BaseModel):
    """PUT body: any subset of fields, at least one required."""
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(default=None, min_length=1, max_length=100)
    description: Optional[str] = Field(default=None, max_length=2000)
    status: Optional[ListingStatus] = None
    property_type: Optional[PropertyType] = None
    available_from: Optional[date] = None

    @field_validator("title")
    @classmethod
    def _t(cls, v):
        return None if v is None else _clean_title(v)

    @model_validator(mode="after")
    def _at_least_one(self):
        if not self.model_fields_set:
            raise ValueError("provide at least one field to update")
        return self


class ListingDocOut(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    status: ListingStatus
    property_type: PropertyType
    available_from: date
    created_at: datetime
    updated_at: datetime