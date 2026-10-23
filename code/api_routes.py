from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession, joinedload

from db import get_db
from jwt_auth import any_role, moderator_only, writer_or_moderator
from models import Listing, Landlord, ListingEvent
from schemas import LandlordCreate, LandlordUpdate, LandlordOut, ListingCreate, ListingUpdate, ListingOut
from query_counter import CountQueries

router = APIRouter(prefix="/api")


# =====================================================================
# Landlord CRUD (related entity)
# =====================================================================

@router.post("/landlords", response_model=LandlordOut, status_code=201)
def create_landlord(payload: LandlordCreate, db: OrmSession = Depends(get_db), user=Depends(writer_or_moderator)):
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
    user=Depends(any_role),
):
    offset = (page - 1) * page_size
    return db.query(Landlord).offset(offset).limit(page_size).all()


@router.get("/landlords/{landlord_id}", response_model=LandlordOut)
def get_landlord(landlord_id: int, db: OrmSession = Depends(get_db), user=Depends(any_role)):
    landlord = db.query(Landlord).filter(Landlord.id == landlord_id).first()
    if not landlord:
        raise HTTPException(status_code=404, detail="Landlord not found")
    return landlord


@router.put("/landlords/{landlord_id}", response_model=LandlordOut)
def update_landlord(
    landlord_id: int, payload: LandlordUpdate,
    db: OrmSession = Depends(get_db), user=Depends(writer_or_moderator),
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
def delete_landlord(landlord_id: int, db: OrmSession = Depends(get_db), user=Depends(moderator_only)):
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
def get_listings_for_landlord(landlord_id: int, db: OrmSession = Depends(get_db), user=Depends(any_role)):
    landlord = db.query(Landlord).filter(Landlord.id == landlord_id).first()
    if not landlord:
        raise HTTPException(status_code=404, detail="Landlord not found")
    return db.query(Listing).filter(Listing.landlord_id == landlord_id).all()


# =====================================================================
# Listing CRUD (primary entity)
# =====================================================================

@router.post("/listings", response_model=ListingOut, status_code=201)
def create_listing(payload: ListingCreate, db: OrmSession = Depends(get_db), user=Depends(writer_or_moderator)):
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
    user=Depends(any_role),
):
    offset = (page - 1) * page_size
    return db.query(Listing).offset(offset).limit(page_size).all()


@router.get("/listings/{listing_id}", response_model=ListingOut)
def get_listing(listing_id: int, db: OrmSession = Depends(get_db), user=Depends(any_role)):
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    return listing


@router.put("/listings/{listing_id}", response_model=ListingOut)
def update_listing(
    listing_id: int, payload: ListingUpdate,
    db: OrmSession = Depends(get_db), user=Depends(writer_or_moderator),
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
def delete_listing(listing_id: int, db: OrmSession = Depends(get_db), user=Depends(moderator_only)):
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    db.delete(listing)
    db.commit()
    return {"deleted": listing_id}


# =====================================================================
# HW4 Part 3 -- N+1 demonstration endpoints (unchanged)
# =====================================================================

@router.get("/listings-naive")
def get_listings_naive(
    page: int = 1, page_size: int = 10,
    db: OrmSession = Depends(get_db), user=Depends(any_role),
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
    db: OrmSession = Depends(get_db), user=Depends(any_role),
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