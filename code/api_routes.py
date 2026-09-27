
from datetime import datetime, timezone

import bcrypt
from fastapi import APIRouter, Depends, Response, Request, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as OrmSession, joinedload

from db import get_db
from models import Listing, User, Session as SessionModel, ListingEvent
from query_counter import CountQueries

router = APIRouter(prefix="/api")


# --- Schemas ---
class LoginRequest(BaseModel):
    email: str
    password: str


class ListingRequest(BaseModel):
    address: str
    landlordName: str


# --- Auth helper ---
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


# --- Auth routes ---
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
        key="session_token",
        value=session.id,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=7200,
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
def me(user: User = Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="Not logged in")
    return {"id": user.id, "name": user.name, "email": user.email}


# --- Listing CRUD routes ---
@router.post("/listings")
def create_listing(
    payload: ListingRequest,
    db: OrmSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Login required")

    listing = Listing(address=payload.address, landlord_name=payload.landlordName)
    db.add(listing)
    db.commit()
    db.refresh(listing)
    return {"id": listing.id, "address": listing.address, "landlordName": listing.landlord_name}


@router.get("/listings")
def get_listings(db: OrmSession = Depends(get_db), user: User = Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="Login required")

    listings = db.query(Listing).all()
    return [
        {"id": l.id, "address": l.address, "landlordName": l.landlord_name}
        for l in listings
    ]


@router.get("/listings/{listing_id}")
def get_listing(listing_id: int, db: OrmSession = Depends(get_db), user: User = Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="Login required")

    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    return {"id": listing.id, "address": listing.address, "landlordName": listing.landlord_name}


@router.put("/listings/{listing_id}")
def update_listing(
    listing_id: int,
    payload: ListingRequest,
    db: OrmSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not user:
        raise HTTPException(status_code=401, detail="Login required")

    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    listing.address = payload.address
    listing.landlord_name = payload.landlordName
    db.commit()
    db.refresh(listing)
    return {"id": listing.id, "address": listing.address, "landlordName": listing.landlord_name}


@router.delete("/listings/{listing_id}")
def delete_listing(listing_id: int, db: OrmSession = Depends(get_db), user: User = Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="Login required")

    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    db.delete(listing)
    db.commit()
    return {"deleted": listing_id}


# --- N+1 demonstration endpoints (Part 3) ---
@router.get("/listings-naive")
def get_listings_naive(
    page: int = 1,
    page_size: int = 10,
    db: OrmSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Intentionally naive: one query for the page of listings, then one
    SEPARATE query per listing to fetch its related events -- the
    classic N+1 pattern.
    """
    if not user:
        raise HTTPException(status_code=401, detail="Login required")

    with CountQueries() as counter:
        offset = (page - 1) * page_size
        listings = db.query(Listing).offset(offset).limit(page_size).all()

        results = []
        for listing in listings:
            events = db.query(ListingEvent).filter(ListingEvent.listing_id == listing.id).all()
            results.append({
                "id": listing.id,
                "address": listing.address,
                "landlordName": listing.landlord_name,
                "events": [{"id": e.id, "note": e.note} for e in events],
            })

    return {"data": results, "sql_query_count": counter.count}


@router.get("/listings-fixed")
def get_listings_fixed(
    page: int = 1,
    page_size: int = 10,
    db: OrmSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Fixed version: eager-loads related events for the whole page in
    a single additional query (via joinedload), instead of one query
    per listing.
    """
    if not user:
        raise HTTPException(status_code=401, detail="Login required")

    with CountQueries() as counter:
        offset = (page - 1) * page_size
        listings = (
            db.query(Listing)
            .options(joinedload(Listing.events))
            .offset(offset)
            .limit(page_size)
            .all()
        )

        results = []
        for listing in listings:
            results.append({
                "id": listing.id,
                "address": listing.address,
                "landlordName": listing.landlord_name,
                "events": [{"id": e.id, "note": e.note} for e in listing.events],
            })

    return {"data": results, "sql_query_count": counter.count}