import os
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["JWT_SECRET"] = secrets.token_hex(32)   # random per run, never committed

import jwt_auth  # noqa: E402
from api_routes import router as api_router  # noqa: E402
from db import Base, get_db  # noqa: E402
from models import User  # noqa: E402

PASSWORD = secrets.token_urlsafe(12)


@pytest.fixture()
def client() -> TestClient:
    """Build an app with the real routers on a fresh in-memory database with one user per role."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False)
    hashed = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt()).decode()
    with session_factory() as db:
        for name in ("reader", "writer", "moderator"):
            db.add(User(name=name, email=f"{name}@example.com", username=name, password_hash=hashed, role=name))
        db.commit()

    def override_db():
        with session_factory() as db:
            yield db

    app = FastAPI()
    app.include_router(jwt_auth.router)
    app.include_router(api_router)
    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def login_header(client: TestClient, username: str) -> dict:
    """Log in as `username` and return the Authorization header."""
    r = client.post("/auth/login", json={"username": username, "password": PASSWORD})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_login_returns_token_for_valid_credentials(client):
    r = client.post("/auth/login", json={"username": "writer", "password": PASSWORD})
    assert r.status_code == 200
    assert r.json()["token_type"] == "bearer" and r.json()["access_token"]


def test_login_rejects_wrong_password_and_unknown_user(client):
    assert client.post("/auth/login", json={"username": "writer", "password": "wrong"}).status_code == 401
    assert client.post("/auth/login", json={"username": "nobody", "password": PASSWORD}).status_code == 401


def test_me_requires_a_valid_token(client):
    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers={"Authorization": "Bearer not.a.token"}).status_code == 401
    me = client.get("/auth/me", headers=login_header(client, "reader"))
    assert me.status_code == 200 and me.json()["role"] == "reader"


def test_expired_token_is_rejected(client):
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    claims = {"sub": "writer", "role": "writer", "exp": past}
    token = jwt.encode(claims, jwt_auth.get_secret(), algorithm=jwt_auth.ALGORITHM)
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401 and "expired" in r.json()["detail"].lower()


def test_any_role_can_list(client):
    for name in ("reader", "writer", "moderator"):
        assert client.get("/api/listings", headers=login_header(client, name)).status_code == 200


def test_create_needs_writer_or_moderator(client):
    body = {"address": "1 Test St, San Jose, CA", "listing_code": "SJ-10001", "available_units": 2}
    assert client.post("/api/listings", json=body, headers=login_header(client, "reader")).status_code == 403
    assert client.post("/api/listings", json=body, headers=login_header(client, "writer")).status_code == 201
    other = {**body, "listing_code": "SJ-10002"}
    assert client.post("/api/listings", json=other, headers=login_header(client, "moderator")).status_code == 201


def test_delete_needs_moderator(client):
    body = {"address": "2 Test St, San Jose, CA", "listing_code": "SJ-20001", "available_units": 1}
    created = client.post("/api/listings", json=body, headers=login_header(client, "writer")).json()
    url = f"/api/listings/{created['id']}"
    assert client.delete(url, headers=login_header(client, "writer")).status_code == 403
    assert client.delete(url, headers=login_header(client, "moderator")).status_code == 200
    assert client.get(url, headers=login_header(client, "reader")).status_code == 404


def test_missing_token_is_401_not_403(client):
    assert client.get("/api/listings").status_code == 401