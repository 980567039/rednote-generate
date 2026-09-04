"""注册、登录和会话 API。"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from flask import Blueprint, current_app, g, jsonify, request

from backend.services.auth import (
    SESSION_TTL_SECONDS,
    AuthError,
    AuthService,
)


PUBLIC_API_PATHS = {
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/me",
    "/api/auth/register",
    "/api/auth/status",
    "/api/health",
}
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def get_auth_service() -> AuthService:
    service = current_app.extensions.get("redink_auth_service")
    if isinstance(service, AuthService):
        return service
    database_path = Path(current_app.config["AUTH_DB_PATH"])
    service = AuthService(database_path)
    current_app.extensions["redink_auth_service"] = service
    return service


def _cookie_name() -> str:
    return str(current_app.config.get("AUTH_COOKIE_NAME", "redink_session"))


def _session_token() -> str | None:
    return request.cookies.get(_cookie_name())


def _no_store_json(body: dict, status: int = 200):
    response = jsonify(body)
    response.status_code = status
    response.headers["Cache-Control"] = "no-store"
    return response


def _auth_error_response(error: Exception):
    if isinstance(error, AuthError):
        return _no_store_json(
            {"code": error.code, "error": str(error)}, error.status
        )
    current_app.logger.exception("认证请求失败")
    return _no_store_json(
        {"code": "AUTH_SERVICE_UNAVAILABLE", "error": "认证服务暂不可用，请稍后重试。"},
        503,
    )


def _set_session_cookie(response, token: str) -> None:
    response.set_cookie(
        _cookie_name(),
        token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=bool(current_app.config.get("AUTH_COOKIE_SECURE", False)),
        samesite="Lax",
        path="/",
    )


def _clear_session_cookie(response) -> None:
    response.delete_cookie(
        _cookie_name(),
        httponly=True,
        secure=bool(current_app.config.get("AUTH_COOKIE_SECURE", False)),
        samesite="Lax",
        path="/",
    )


def _request_origin_allowed() -> bool:
    origin = request.headers.get("Origin", "").strip()
    if not origin:
        return True
    parsed = urlsplit(origin)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    normalized = f"{parsed.scheme}://{parsed.netloc}"
    allowed = set(current_app.config.get("CORS_ORIGINS", []))
    allowed.add(request.host_url.rstrip("/"))
    return normalized in allowed


def install_auth_guard(app) -> None:
    @app.before_request
    def require_api_authentication():
        if request.method == "OPTIONS" or not request.path.startswith("/api/"):
            return None
        if request.method in UNSAFE_METHODS and not _request_origin_allowed():
            return _no_store_json(
                {"code": "CROSS_SITE_REQUEST_BLOCKED", "error": "跨站写入请求已被拒绝。"},
                403,
            )
        if request.path in PUBLIC_API_PATHS:
            return None
        if current_app.config.get("TESTING") and not current_app.config.get(
            "AUTH_TEST_FORCE", False
        ):
            return None
        user = get_auth_service().authenticated_user(_session_token())
        if not user:
            return _no_store_json(
                {"code": "UNAUTHORIZED", "error": "请先登录。"}, 401
            )
        g.auth_user = user
        return None


def create_auth_blueprint():
    auth_bp = Blueprint("auth", __name__)

    @auth_bp.get("/auth/status")
    def auth_status():
        return _no_store_json({"status": get_auth_service().registration_status()})

    @auth_bp.post("/auth/register")
    def register():
        try:
            result = get_auth_service().register(request.get_json(silent=True))
            response = _no_store_json({"user": result.user.to_dict()}, 201)
            _set_session_cookie(response, result.session_token)
            return response
        except Exception as error:
            return _auth_error_response(error)

    @auth_bp.post("/auth/login")
    def login():
        try:
            result = get_auth_service().login(request.get_json(silent=True))
            response = _no_store_json({"user": result.user.to_dict()})
            _set_session_cookie(response, result.session_token)
            return response
        except Exception as error:
            return _auth_error_response(error)

    @auth_bp.get("/auth/me")
    def current_user():
        user = get_auth_service().authenticated_user(_session_token())
        if not user:
            return _no_store_json(
                {"code": "UNAUTHORIZED", "error": "请先登录。"}, 401
            )
        return _no_store_json({"user": user.to_dict()})

    @auth_bp.post("/auth/logout")
    def logout():
        token = _session_token()
        user = get_auth_service().authenticated_user(token)
        get_auth_service().revoke_session(token)
        response = _no_store_json(
            {"user": user.to_dict() if user else None}
            if user
            else {"code": "UNAUTHORIZED", "error": "请先登录。"},
            200 if user else 401,
        )
        _clear_session_cookie(response)
        return response

    return auth_bp
