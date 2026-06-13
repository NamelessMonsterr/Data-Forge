"""FastAPI adapter for the provider-key vault (Account / Provider Settings).

Imports FastAPI lazily, mirroring ``backend.auth.web``. Every route requires an
authenticated user (reuse ``make_current_user_dependency`` from auth) and is
user-scoped. Status/list responses report only configured/unconfigured state --
raw keys and secrets are NEVER returned to the client.

Graceful degradation when ``DATAFORGE_VAULT_KEY`` is not configured:
the app should still boot. Pass ``None`` (or a factory that returns ``None``)
as the vault, and every settings route returns ``503`` for authenticated users
with a clear message -- the auth dependency still runs first, so logged-out
callers continue to get ``401``.

The ``vault`` argument may be:
  * a ready ``ProviderVault`` instance, or
  * ``None`` (vault unavailable -> 503 on every route), or
  * a zero-arg callable returning a ``ProviderVault`` or ``None`` (resolved per
    request, useful for lazy initialization).

Wiring example (in your FastAPI app factory)::

    from backend.auth import AuthService, AuthStore
    from backend.auth.web import make_current_user_dependency
    from backend.vault import ProviderVault, VaultStore
    from backend.vault.crypto import SecretBox, VaultKeyMissing
    from backend.vault.web import build_settings_router

    auth = AuthService(AuthStore())
    try:
        vault = ProviderVault(VaultStore(), SecretBox.from_env())
    except VaultKeyMissing:
        vault = None  # app still boots; settings routes return 503

    current_user = make_current_user_dependency(auth)
    app.include_router(build_settings_router(vault, current_user))

To actually use a stored key for a live request, decrypt it on the backend only::

    creds = vault.get_secrets(user, "nvidia")
    if creds:
        config = LLMConfig(live=True, api_key=creds["api_key"], ...)
"""

from .service import MissingApiKey, MissingSecret, UnknownProvider


def build_settings_router(vault, current_user):
    """Build the ``/settings`` router (list/set/delete provider credentials).

    ``vault`` may be a ``ProviderVault`` instance, ``None``, or a zero-arg
    callable returning either. When it resolves to ``None`` the routes return
    ``503`` (vault not configured) -- after the auth dependency has run.
    """
    from fastapi import APIRouter, Depends, HTTPException, status
    from pydantic import BaseModel

    router = APIRouter(prefix="/settings", tags=["settings"])

    class CredentialBody(BaseModel):
        api_key: str
        secret: str | None = None

    def _resolve():
        resolved = vault() if callable(vault) else vault
        if resolved is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="provider vault is not configured (DATAFORGE_VAULT_KEY is not set)",
            )
        return resolved

    @router.get("/providers")
    def list_providers(user=Depends(current_user)):
        return {"providers": [s.to_dict() for s in _resolve().list_status(user)]}

    @router.post("/providers/{provider}")
    def set_provider(provider: str, body: CredentialBody, user=Depends(current_user)):
        active = _resolve()
        try:
            st = active.set_credential(user, provider, body.api_key, body.secret)
        except UnknownProvider:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="unknown provider"
            )
        except (MissingApiKey, MissingSecret) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            )
        return st.to_dict()

    @router.delete("/providers/{provider}")
    def delete_provider(provider: str, user=Depends(current_user)):
        active = _resolve()
        try:
            removed = active.delete_credential(user, provider)
        except UnknownProvider:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="unknown provider"
            )
        if not removed:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="not configured"
            )
        return {"ok": True, "provider": provider.strip().lower(), "removed": True}

    return router
