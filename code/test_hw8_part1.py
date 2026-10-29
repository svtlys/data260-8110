import json
import threading
import time

from client import RequestClient, build_request
from entity_service import handle_request, validate_listing
from kafka_config import TOPIC_REQUESTS, TOPIC_RESPONSES
from kafka_io import InMemoryBroker, InMemoryConsumer, InMemoryProducer
from worker import run_worker

GOOD = {"address": "1 Main St", "available_units": 2, "landlord_name": "Acme"}


def start_system(idempotent=True):
    broker = InMemoryBroker()
    for t in (TOPIC_REQUESTS, TOPIC_RESPONSES):
        broker.create_topic(t)
    stop, store = threading.Event(), {}
    worker = threading.Thread(target=run_worker, args=(InMemoryConsumer(broker, "w", [TOPIC_REQUESTS]), InMemoryProducer(broker),
                                                     store, {}, stop, idempotent), daemon=True)
    worker.start()
    client = RequestClient(InMemoryProducer(broker), InMemoryConsumer(broker, "c", [TOPIC_RESPONSES]))
    client.start()
    return client, store, stop


def test_validation_rejects_bad_input():
    for bad in ({}, {**GOOD, "address": "  "}, {**GOOD, "available_units": 0}, {**GOOD, "available_units": "3"},
                {**GOOD, "available_units": True}, {**GOOD, "listing_code": ""}, "x"):
        assert validate_listing(bad)[0] is None


def test_create_get_roundtrip_and_errors():
    store = {}
    created = handle_request({"correlation_id": "c1", "operation": "CREATE_LISTING", "data": GOOD}, store)
    assert created["success"] and created["correlation_id"] == "c1" and created["listing_id"] in store
    got = handle_request({"correlation_id": "c2", "operation": "GET_LISTING", "data": {"listing_id": created["listing_id"]}}, store)
    assert got["success"] and got["listing"]["address"] == "1 Main St"
    missing = handle_request({"correlation_id": "c3", "operation": "GET_LISTING", "data": {"listing_id": "nope"}}, store)
    assert missing == {"success": False, "error": "Listing not found", "correlation_id": "c3"}
    unknown = handle_request({"correlation_id": "c4", "operation": "DELETE_LISTING", "data": {}}, store)
    assert unknown["error"] == "Unknown operation" and unknown["correlation_id"] == "c4"
    assert handle_request({"correlation_id": "c5", "operation": "CREATE_LISTING", "data": {}}, store)["success"] is False


def test_roundtrip_through_broker_preserves_correlation_id():
    client, store, stop = start_system()
    req = build_request("CREATE_LISTING", GOOD)
    resp = client.request(req, timeout=5)
    assert resp["correlation_id"] == req["correlation_id"] and resp["success"] and len(store) == 1
    got = client.request(build_request("GET_LISTING", {"listing_id": resp["listing_id"]}), timeout=5)
    assert got["success"] and got["listing"]["listing_id"] == resp["listing_id"]
    stop.set()


def test_replay_is_idempotent():
    client, store, stop = start_system(idempotent=True)
    req = build_request("CREATE_LISTING", GOOD)
    first, second = client.request(req, timeout=5), client.request(req, timeout=5)
    assert first["listing_id"] == second["listing_id"] and len(store) == 1
    stop.set()


def test_replay_without_idempotency_duplicates():
    client, store, stop = start_system(idempotent=False)
    req = build_request("CREATE_LISTING", GOOD)
    client.request(req, timeout=5)
    client.request(req, timeout=5)
    assert len(store) == 2
    stop.set()
    time.sleep(0.1)
    assert json.dumps(req)