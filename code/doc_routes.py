from datetime import date, datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException, Response
from pymongo.errors import PyMongoError, WriteError

import doc_mongo
from doc_schemas import ListingDocCreate, ListingDocOut, ListingDocUpdate

router = APIRouter(prefix="/api/listing-docs", tags=["listing-docs"])


def _now():
    return datetime.now(timezone.utc)


def _to_dt(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def _oid(doc_id: str) -> ObjectId:
    try:
        return ObjectId(doc_id)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail=f"'{doc_id}' is not a valid id")


def _out(doc: dict) -> ListingDocOut:
    return ListingDocOut(
        id=str(doc["_id"]), title=doc["title"], description=doc.get("description"),
        status=doc["status"], property_type=doc["property_type"],
        available_from=doc["available_from"].date(),
        created_at=doc["created_at"], updated_at=doc["updated_at"])


def _db_error(e: Exception):
    if isinstance(e, WriteError) and e.code == 121:
        raise HTTPException(422, f"MongoDB schema validation failed: {e.details}")
    raise HTTPException(503, f"database error: {e.__class__.__name__}")


@router.post("", response_model=ListingDocOut, status_code=201)
def create_listing(body: ListingDocCreate):
    now = _now()
    doc = {"title": body.title, "description": body.description,
           "status": body.status.value, "property_type": body.property_type.value,
           "available_from": _to_dt(body.available_from),
           "created_at": now, "updated_at": now}
    try:
        res = doc_mongo.listing_collection().insert_one(doc)
    except PyMongoError as e:
        _db_error(e)
    doc["_id"] = res.inserted_id
    return _out(doc)


@router.get("", response_model=list[ListingDocOut])
def list_listings():
    try:
        docs = doc_mongo.listing_collection().find().sort("created_at", -1)
        return [_out(d) for d in docs]
    except PyMongoError as e:
        _db_error(e)


@router.get("/{doc_id}", response_model=ListingDocOut)
def get_listing(doc_id: str):
    oid = _oid(doc_id)
    try:
        doc = doc_mongo.listing_collection().find_one({"_id": oid})
    except PyMongoError as e:
        _db_error(e)
    if doc is None:
        raise HTTPException(404, "listing not found")
    return _out(doc)


@router.put("/{doc_id}", response_model=ListingDocOut)
def update_listing(doc_id: str, body: ListingDocUpdate):
    oid = _oid(doc_id)
    changes = {}
    for field in body.model_fields_set:
        v = getattr(body, field)
        if v is None and field != "description":
            raise HTTPException(422, f"{field} cannot be null")
        if field == "available_from":
            v = _to_dt(v)
        elif hasattr(v, "value"):
            v = v.value
        changes[field] = v
    changes["updated_at"] = _now()
    try:
        doc = doc_mongo.listing_collection().find_one_and_update(
            {"_id": oid}, {"$set": changes}, return_document=True)
    except PyMongoError as e:
        _db_error(e)
    if doc is None:
        raise HTTPException(404, "listing not found")
    return _out(doc)


@router.delete("/{doc_id}", status_code=204)
def delete_listing(doc_id: str):
    oid = _oid(doc_id)
    try:
        res = doc_mongo.listing_collection().delete_one({"_id": oid})
    except PyMongoError as e:
        _db_error(e)
    if res.deleted_count == 0:
        raise HTTPException(404, "listing not found")
    return Response(status_code=204)