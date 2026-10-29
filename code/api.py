import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException
from fastapi.concurrency import run_in_threadpool

from client import RequestClient, build_request, make_client
from kafka_config import PORT_BASE, TOPIC_PARTITIONS, setup_logging

logger = logging.getLogger("api")
STATE: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    from kafka_io import ensure_topics

    setup_logging("api")
    await run_in_threadpool(ensure_topics, TOPIC_PARTITIONS)
    STATE["client"] = await run_in_threadpool(make_client, "api")
    logger.info("Server started at http://127.0.0.1:%d", PORT_BASE)
    yield
    STATE["client"].stop()


app = FastAPI(title="s8110 Listing service (Kafka)", lifespan=lifespan)


async def _call(operation: str, data: dict, correlation_id: str | None) -> dict:
    client: RequestClient = STATE["client"]
    request = build_request(operation, data, correlation_id)
    try:
        response = await run_in_threadpool(client.request, request)
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    logger.info("API RETURNED correlation_id=%s success=%s", response["correlation_id"], response["success"])
    return response


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "port": PORT_BASE}


@app.post("/listings")
async def create_listing(data: dict, x_correlation_id: str | None = Header(default=None)) -> dict:
    return await _call("CREATE_LISTING", data, x_correlation_id)


@app.get("/listings/{listing_id}")
async def get_listing(listing_id: str, x_correlation_id: str | None = Header(default=None)) -> dict:
    return await _call("GET_LISTING", {"listing_id": listing_id}, x_correlation_id)


@app.post("/request")
async def raw_request(body: dict) -> dict:
    """Send any operation/data pair (used to demonstrate the 'Unknown operation' error)."""
    return await _call(str(body.get("operation", "")), body.get("data", {}), body.get("correlation_id"))