from datetime import datetime, timezone

import bcrypt
from fastapi import APIRouter, Depends, Response, Request, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession, joinedload

from db import get_db
from models import Listing, Landlord, User, Session as SessionModel, ListingEvent
from schemas import LandlordCreate, LandlordUpdate, LandlordOut, ListingCreate, ListingUpdate, ListingOut
from query_counter import CountQueries

router = APIRouter(prefix="/api")


class LoginRequest(BaseModel):
    email: str
    password: str


def get_current_user(request: Request, db: OrmSession = Depends(get_db)):
    token = request.cookies.get("session_token")
    if not token:
        return None
    session = db.query(SessionModel).filter(SessionModel.id == token).first()
    if not session:
        return None
    if session.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        return None
    return session.user


def require_login(user=Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="Login required")
    return user


@router.post("/login")
def login(payload: LoginRequest, response: Response, db: OrmSession = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not bcrypt.checkpw(payload.password.encode(), user.password_hash.encode()):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    session = SessionModel(user_id=user.id)
    db.add(session)
    db.commit()
    db.refresh(session)
    response.set_cookie(
        key="session_token", value=session.id, httponly=True,
        secure=False, samesite="lax", max_age=7200,
    )
    return {"message": "Logged in", "user": {"id": user.id, "name": user.name, "email": user.email}}


@router.post("/logout")
def logout(request: Request, response: Response, db: OrmSession = Depends(get_db)):
    token = request.cookies.get("session_token")
    if token:
        db.query(SessionModel).filter(SessionModel.id == token).delete()
        db.commit()
    response.delete_cookie("session_token")
    return {"message": "Logged out"}


@router.get("/me")
def me(user: User = Depends(require_login)):
    return {"id": user.id, "name": user.name, "email": user.email}


@router.post("/landlords", response_model=LandlordOut, status_code=201)
def create_landlord(payload: LandlordCreate, db: OrmSession = Depends(get_db), user=Depends(require_login)):
    existing = db.query(Landlord).filter(Landlord.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="A landlord with this email already exists.")

    landlord = Landlord(name=payload.name, contact_info=payload.contact_info, email=payload.email)
    db.add(landlord)
    db.commit()
    db.refresh(landlord)
    return landlord


@router.get("/landlords", response_model=list[LandlordOut])
def list_landlords(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: OrmSession = Depends(get_db),
    user=Depends(require_login),
):
    offset = (page - 1) * page_size
    return db.query(Landlord).offset(offset).limit(page_size).all()


@router.get("/landlords/{landlord_id}", response_model=LandlordOut)
def get_landlord(landlord_id: int, db: OrmSession = Depends(get_db), user=Depends(require_login)):
    landlord = db.query(Landlord).filter(Landlord.id == landlord_id).first()
    if not landlord:
        raise HTTPException(status_code=404, detail="Landlord not found")
    return landlord


@router.put("/landlords/{landlord_id}", response_model=LandlordOut)
def update_landlord(
    landlord_id: int, payload: LandlordUpdate,
    db: OrmSession = Depends(get_db), user=Depends(require_login),
):
    landlord = db.query(Landlord).filter(Landlord.id == landlord_id).first()
    if not landlord:
        raise HTTPException(status_code=404, detail="Landlord not found")

    conflict = db.query(Landlord).filter(Landlord.email == payload.email, Landlord.id != landlord_id).first()
    if conflict:
        raise HTTPException(status_code=409, detail="Another landlord already uses this email.")

    landlord.name = payload.name
    landlord.contact_info = payload.contact_info
    landlord.email = payload.email
    db.commit()
    db.refresh(landlord)
    return landlord


@router.delete("/landlords/{landlord_id}")
def delete_landlord(landlord_id: int, db: OrmSession = Depends(get_db), user=Depends(require_login)):
    landlord = db.query(Landlord).filter(Landlord.id == landlord_id).first()
    if not landlord:
        raise HTTPException(status_code=404, detail="Landlord not found")

    # Prevent deletion while related Listing rows still reference this landlord
    dependent_count = db.query(Listing).filter(Listing.landlord_id == landlord_id).count()
    if dependent_count > 0:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete landlord: {dependent_count} listing(s) still reference this landlord.",
        )

    db.delete(landlord)
    db.commit()
    return {"deleted": landlord_id}


# Relationship query: all listings for a given landlord
@router.get("/landlords/{landlord_id}/listings", response_model=list[ListingOut])
def get_listings_for_landlord(landlord_id: int, db: OrmSession = Depends(get_db), user=Depends(require_login)):
    landlord = db.query(Landlord).filter(Landlord.id == landlord_id).first()
    if not landlord:
        raise HTTPException(status_code=404, detail="Landlord not found")
    return db.query(Listing).filter(Listing.landlord_id == landlord_id).all()



@router.post("/listings", response_model=ListingOut, status_code=201)
def create_listing(payload: ListingCreate, db: OrmSession = Depends(get_db), user=Depends(require_login)):
    if payload.landlord_id is not None:
        landlord = db.query(Landlord).filter(Landlord.id == payload.landlord_id).first()
        if not landlord:
            raise HTTPException(status_code=404, detail="landlord_id does not reference an existing landlord")

    listing = Listing(
        address=payload.address,
        landlord_id=payload.landlord_id,
        listing_code=payload.listing_code,
        available_units=payload.available_units,
    )
    db.add(listing)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="listing_code must be unique.")
    db.refresh(listing)
    return listing


@router.get("/listings", response_model=list[ListingOut])
def list_listings(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: OrmSession = Depends(get_db),
    user=Depends(require_login),
):
    offset = (page - 1) * page_size
    return db.query(Listing).offset(offset).limit(page_size).all()


@router.get("/listings/{listing_id}", response_model=ListingOut)
def get_listing(listing_id: int, db: OrmSession = Depends(get_db), user=Depends(require_login)):
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    return listing


@router.put("/listings/{listing_id}", response_model=ListingOut)
def update_listing(
    listing_id: int, payload: ListingUpdate,
    db: OrmSession = Depends(get_db), user=Depends(require_login),
):
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    if payload.landlord_id is not None:
        landlord = db.query(Landlord).filter(Landlord.id == payload.landlord_id).first()
        if not landlord:
            raise HTTPException(status_code=404, detail="landlord_id does not reference an existing landlord")

    listing.address = payload.address
    listing.landlord_id = payload.landlord_id
    listing.listing_code = payload.listing_code
    listing.available_units = payload.available_units
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="listing_code must be unique.")
    db.refresh(listing)
    return listing


@router.delete("/listings/{listing_id}")
def delete_listing(listing_id: int, db: OrmSession = Depends(get_db), user=Depends(require_login)):
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    db.delete(listing)
    db.commit()
    return {"deleted": listing_id}



@router.get("/listings-naive")
def get_listings_naive(
    page: int = 1, page_size: int = 10,
    db: OrmSession = Depends(get_db), user=Depends(require_login),
):
    with CountQueries() as counter:
        offset = (page - 1) * page_size
        listings = db.query(Listing).offset(offset).limit(page_size).all()
        results = []
        for listing in listings:
            events = db.query(ListingEvent).filter(ListingEvent.listing_id == listing.id).all()
            results.append({
                "id": listing.id, "address": listing.address,
                "landlordName": listing.landlord_name,
                "events": [{"id": e.id, "note": e.note} for e in events],
            })
    return {"data": results, "sql_query_count": counter.count}


@router.get("/listings-fixed")
def get_listings_fixed(
    page: int = 1, page_size: int = 10,
    db: OrmSession = Depends(get_db), user=Depends(require_login),
):
    with CountQueries() as counter:
        offset = (page - 1) * page_size
        listings = (
            db.query(Listing)
            .options(joinedload(Listing.events))
            .offset(offset).limit(page_size).all()
        )
        results = []
        for listing in listings:
            results.append({
                "id": listing.id, "address": listing.address,
                "landlordName": listing.landlord_name,
                "events": [{"id": e.id, "note": e.note} for e in listing.events],
            })
    return {"data": results, "sql_query_count": counter.count}