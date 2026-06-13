"""FastAPI adapter for cookie-based auth.

Imports FastAPI lazily (only inside the builder functions) so importing this
module, or the auth package, never requires the web framework -- the tested core
stays stdlib-only, matching ``backend.app.security``.

Sessions use an HTTP-only, ``SameSite=Lax`` cookie that is ``Secure`` by default
(disable in local dev with ``DATAFORGE_COOKIE_SECURE=false``). The cookie holds
only an opaque server-side session token -- never a JWT in JS-readable storage.

Wiring example (in your FastAPI app factory)::

    from backend.auth import AuthService, AuthStore
    from backend.auth.web import build_auth_router, make_current_user_dependency

    auth = AuthService(AuthStore(os.getenv("DATAFORGE_AUTH_DB", "tmp/dataforge_auth.db")))
    app.include_router(build_auth_router(auth))
    current_user = make_current_user_dependency(auth)

    @app.get("/datasets/catalog")
    def catalog(user = Depends(current_user)):
        return filter_owned(repo.list_datasets(), user)
"""

import os

from .service import (
    AuthService,
    EmailAlreadyExists,
    InvalidCredentials,
    InvalidEmail,
    WeakPassword,
)

SESSION_COOKIE = os.getenv("DATAFORGE_SESSION_COOKIE", "dataforge_session")


def _cookie_is_secure() -> bool:
    return os.getenv("DATAFORGE_COOKIE_SECURE", "true").strip().lower() != "false"


def cookie_params(*, max_age: int | None = None) -> dict:
    """Attributes for the session cookie (HTTP-only, Secure, SameSite=Lax)."""
    return {
        "key": SESSION_COOKIE,
        "httponly": True,
        "secure": _cookie_is_secure(),
        "samesite": "lax",
        "path": "/",
        "max_age": max_age,
    }


def make_current_user_dependency(service: AuthService):
    """Return a FastAPI dependency that yields the authenticated user or 401."""
    from fastapi import HTTPException, Request, status

    def current_user(request: Request):
        token = request.cookies.get(SESSION_COOKIE)
        user = service.authenticate(token)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated"
            )
        return user

    return current_user


def build_auth_router(service: AuthService):
    """Build the ``/auth`` router (register, login, logout, me)."""
    from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
    from pydantic import BaseModel

    router = APIRouter(prefix="/auth", tags=["auth"])
    current_user = make_current_user_dependency(service)

    class Credentials(BaseModel):
        email: str
        password: str

    def _user_json(user) -> dict:
        return {
            "id": user.id,
            "email": user.email,
            "role": user.role,
            "created_at": user.created_at,
        }

    @router.post("/register", status_code=status.HTTP_201_CREATED)
    def register(body: Credentials):
        try:
            user = service.register(body.email, body.password)
        except EmailAlreadyExists:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="email already registered"
            )
        except (InvalidEmail, WeakPassword) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            )
        return _user_json(user)

    @router.post("/login")
    def login(body: Credentials, response: Response):
        try:
            result = service.login(body.email, body.password)
        except InvalidCredentials:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid email or password",
            )
        max_age = int(service.session_ttl.total_seconds())
        response.set_cookie(value=result.token, **cookie_params(max_age=max_age))
        return _user_json(result.user)

    @router.post("/logout")
    def logout(request: Request, response: Response):
        service.logout(request.cookies.get(SESSION_COOKIE))
        response.delete_cookie(key=SESSION_COOKIE, path="/")
        return {"ok": True}

    @router.get("/me")
    def me(user=Depends(current_user)):
        return _user_json(user)

    return router
