from fastapi import FastAPI, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from typing import Optional

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

listings = [
    {
        "id": 1,
        "address": "100 Placeholder St, San Jose, CA",
        "landlordName": "Placeholder Realty",
    }
]
next_id = 2


@app.get("/listings")
def get_listings(search: Optional[str] = None):
    
    if not search:
        return listings

    search_lower = search.lower()
    return [
        item for item in listings
        if search_lower in item["address"].lower()
        or search_lower in item["landlordName"].lower()
    ]


@app.post("/listings")
def add_listing(address: str = Form(...), landlordName: str = Form(...)):
    global next_id
    new_record = {"id": next_id, "address": address, "landlordName": landlordName}
    listings.append(new_record)
    next_id += 1
    return new_record


@app.put("/listings/1")
def update_listing_1(address: str = Form(...), landlordName: str = Form(...)):
    for item in listings:
        if item["id"] == 1:
            item["address"] = address
            item["landlordName"] = landlordName
            return item
    return {"error": "Record with ID 1 not found"}


@app.delete("/listings/highest")
def delete_highest_listing():
    if not listings:
        return {"error": "No listings to delete"}

    highest = max(listings, key=lambda item: item["id"])
    listings.remove(highest)
    return {"deleted": highest}


@app.get("/")
def root():
    return {"message": "Rental Housing Listings API is running.", "port": 8010}