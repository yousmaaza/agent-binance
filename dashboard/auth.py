"""Authentification simple par variable d'environnement (#432) — une URL non devinable ne
suffit pas à protéger une page qui expose la valeur du portefeuille."""
import hmac
from functools import wraps
from urllib.parse import urlsplit

import settings
from flask import redirect, request, session, url_for


def is_configured() -> bool:
    return bool(settings.DASHBOARD_PASSWORD and settings.DASHBOARD_SECRET_KEY)


def check_password(candidate: str) -> bool:
    return hmac.compare_digest(candidate or "", settings.DASHBOARD_PASSWORD)


def safe_next_path(value):
    """Liste blanche : n'accepte qu'un chemin relatif interne (#435 — redirection ouverte)."""
    if not value or not value.startswith("/") or value.startswith(("//", "/\\")):
        return None
    parts = urlsplit(value)
    if parts.scheme or parts.netloc:
        return None
    return value


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped
