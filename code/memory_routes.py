from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from pymongo.errors import PyMongoError

from memory_embed import Embedder
from memory_llm import call_model
from memory_service import MemoryService
from memory_store import MongoStore

router = APIRouter(prefix="/api", tags=["memory-chat"])
_svc = None


def service() -> MemoryService:
    global _svc
    if _svc is None:
        _svc = MemoryService(MongoStore(), Embedder(), call_model)
    return _svc


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str = Field(..., min_length=1, max_length=64)
    message: str = Field(..., min_length=1, max_length=4000)
    session_id: Optional[str] = Field(default=None, max_length=64)
    persist: bool = True


@router.post("/chat")
def chat(body: ChatRequest):
    try:
        return service().chat(body.user_id, body.message, body.session_id, body.persist)
    except PyMongoError as e:
        raise HTTPException(503, f"database error: {e.__class__.__name__}")
    except Exception as e:   # model / embedding failure
        raise HTTPException(502, f"chat pipeline failed: {e.__class__.__name__}: {e}")


@router.get("/memory/{user_id}")
def memory(user_id: str):
    try:
        return service().memory_view(user_id)
    except PyMongoError as e:
        raise HTTPException(503, f"database error: {e.__class__.__name__}")


@router.get("/aggregate/{user_id}")
def aggregate(user_id: str):
    try:
        return service().aggregate(user_id)
    except PyMongoError as e:
        raise HTTPException(503, f"database error: {e.__class__.__name__}")