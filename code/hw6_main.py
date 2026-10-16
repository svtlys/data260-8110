from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import doc_config as cfg
import doc_mongo
from doc_routes import router as doc_router
from memory_routes import router as memory_router
from memory_store import ensure_memory_collections


@asynccontextmanager
async def lifespan(app):
    if doc_mongo.ping():
        doc_mongo.ensure_collection()
        ensure_memory_collections()
        print(f"[hw6] MongoDB ok, collection {cfg.DB_NAME}.{cfg.COLLECTION_NAME} ready")
    else:
        print("[hw6] WARNING: MongoDB not reachable; start it with "
              "'brew services start mongodb-community@8.0'")
    yield


app = FastAPI(title="HW6 Listing Docs (s8110)", lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=cfg.CORS_ORIGINS,
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def require_json(request: Request, call_next):
    """JSON middleware: write requests with a body must be application/json."""
    if request.method in ("POST", "PUT", "PATCH"):
        ctype = request.headers.get("content-type", "")
        if int(request.headers.get("content-length", "0") or 0) > 0 \
                and "application/json" not in ctype:
            return JSONResponse(status_code=415,
                                content={"detail": "Content-Type must be application/json"})
    return await call_next(request)


app.include_router(doc_router)
app.include_router(memory_router)


@app.get("/health")
def health():
    return {"status": "ok", "mongo": doc_mongo.ping(), "db": cfg.DB_NAME}