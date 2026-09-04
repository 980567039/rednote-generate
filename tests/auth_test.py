import hashlib
import sqlite3
from http.cookies import SimpleCookie

from flask import Flask, g, jsonify

from backend.routes.auth_routes import (
    create_auth_blueprint,
    install_auth_guard,
)


def make_app(tmp_path):
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        AUTH_TEST_FORCE=True,
        AUTH_DB_PATH=str(tmp_path / "auth.sqlite3"),
        AUTH_COOKIE_NAME="redink_session",
        AUTH_COOKIE_SECURE=False,
        CORS_ORIGINS=["http://localhost:5173"],
    )
    app.register_blueprint(create_auth_blueprint(), url_prefix="/api")
    install_auth_guard(app)

    @app.get("/api/private")
    def private_route():
        return jsonify({"user": g.auth_user.to_dict()})

    return app


def registration_payload(**overrides):
    return {
        "displayName": "RedInk 创作者",
        "email": "Creator@Example.com",
        "password": "correct-horse-123",
        **overrides,
    }


def session_token(response):
    cookie = SimpleCookie()
    cookie.load(response.headers["Set-Cookie"])
    return cookie["redink_session"].value


def test_register_creates_hashed_account_and_authenticated_session(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()

    assert client.get("/api/auth/status").get_json()["status"]["registrationOpen"] is True
    assert client.get("/api/private").status_code == 401

    response = client.post(
        "/api/auth/register",
        json=registration_payload(),
        headers={"Origin": "http://localhost:5173"},
    )

    assert response.status_code == 201
    assert response.get_json()["user"]["email"] == "creator@example.com"
    assert "HttpOnly" in response.headers["Set-Cookie"]
    assert "SameSite=Lax" in response.headers["Set-Cookie"]
    assert client.get("/api/auth/me").status_code == 200
    assert client.get("/api/private").status_code == 200
    assert client.get("/api/auth/status").get_json()["status"]["registrationOpen"] is False

    token = session_token(response)
    with sqlite3.connect(tmp_path / "auth.sqlite3") as connection:
        user = connection.execute(
            "SELECT password_hash FROM users"
        ).fetchone()
        session = connection.execute(
            "SELECT token_hash FROM sessions"
        ).fetchone()
    assert user[0].startswith("scrypt$")
    assert "correct-horse-123" not in user[0]
    assert session[0] == hashlib.sha256(token.encode("utf-8")).hexdigest()
    assert token not in session[0]


def test_duplicate_login_logout_and_expired_session_paths(tmp_path):
    app = make_app(tmp_path)
    owner = app.test_client()
    duplicate = app.test_client()

    assert owner.post(
        "/api/auth/register", json=registration_payload()
    ).status_code == 201
    closed = duplicate.post(
        "/api/auth/register",
        json=registration_payload(email="creator@example.com"),
    )
    assert closed.status_code == 409
    assert closed.get_json()["code"] == "REGISTRATION_CLOSED"
    assert duplicate.post(
        "/api/auth/login",
        json={"email": "creator@example.com", "password": "wrong-password"},
    ).status_code == 401

    login = duplicate.post(
        "/api/auth/login",
        json={
            "email": "creator@example.com",
            "password": "correct-horse-123",
        },
    )
    assert login.status_code == 200
    assert duplicate.get("/api/private").status_code == 200
    assert duplicate.post("/api/auth/logout").status_code == 200
    assert duplicate.get("/api/private").status_code == 401

    owner_token = session_token(
        owner.post(
            "/api/auth/login",
            json={
                "email": "creator@example.com",
                "password": "correct-horse-123",
            },
        )
    )
    owner.set_cookie("redink_session", owner_token)
    with sqlite3.connect(tmp_path / "auth.sqlite3") as connection:
        connection.execute(
            "UPDATE sessions SET expires_at = '2000-01-01T00:00:00+00:00' WHERE token_hash = ?",
            (hashlib.sha256(owner_token.encode("utf-8")).hexdigest(),),
        )
    assert owner.get("/api/auth/me").status_code == 401


def test_validation_and_cross_site_write_protection(tmp_path):
    client = make_app(tmp_path).test_client()

    weak_password = client.post(
        "/api/auth/register",
        json=registration_payload(password="short"),
    )
    invalid_email = client.post(
        "/api/auth/register",
        json=registration_payload(email="not-an-email"),
    )
    cross_site = client.post(
        "/api/auth/register",
        json=registration_payload(),
        headers={"Origin": "https://evil.example"},
    )

    assert weak_password.status_code == 400
    assert invalid_email.status_code == 400
    assert cross_site.status_code == 403
    assert cross_site.get_json()["code"] == "CROSS_SITE_REQUEST_BLOCKED"
