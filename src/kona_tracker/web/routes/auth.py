"""Signing in and out, the health check, and where "/" goes.

The passcode gate itself is the `gate` middleware in app.py; these are the
routes it lets through and the one that issues the cookie it checks.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from kona_tracker.web.auth import COOKIE_NAME, client_key
from kona_tracker.web.deps import HOME, AppDeps


def make_auth_router(deps: AppDeps) -> APIRouter:
    router = APIRouter()
    settings, templates, auth, health_summary = (
        deps.settings,
        deps.templates,
        deps.auth,
        deps.health_summary,
    )

    def authed(request: Request) -> bool:
        return auth.valid_cookie(request.cookies.get(COOKIE_NAME))

    @router.get("/healthz")
    def healthz() -> dict[str, Any]:
        return health_summary()

    @router.get("/login", response_class=HTMLResponse)
    def login_page(request: Request):
        if authed(request):
            return RedirectResponse(HOME, status_code=303)
        return templates.TemplateResponse(request, "login.html", {"error": None})

    @router.post("/login", response_class=HTMLResponse)
    def login(request: Request, passcode: str = Form("")):
        key = client_key(
            request.headers,
            request.client.host if request.client else "?",
            settings.trusted_proxy_header,
            settings.trusted_proxy_ips,
        )
        if auth.lockout.blocked(key):
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": "Too many tries. Wait a moment."},
                status_code=429,
            )
        if not auth.check(passcode):
            auth.lockout.fail(key)
            return templates.TemplateResponse(
                request, "login.html", {"error": "That's not it."}, status_code=401
            )
        auth.lockout.clear(key)
        resp = RedirectResponse(HOME, status_code=303)
        resp.set_cookie(
            COOKIE_NAME,
            auth.issue_cookie(),
            max_age=settings.cookie_max_age,
            httponly=True,
            samesite="lax",
            secure=settings.secure_cookies,
        )
        return resp

    @router.post("/logout")
    def logout():
        resp = RedirectResponse("/login", status_code=303)
        # Same attributes as when it was set, or the browser keeps the old one.
        resp.delete_cookie(
            COOKIE_NAME, httponly=True, samesite="lax", secure=settings.secure_cookies
        )
        return resp

    @router.get("/")
    def root():
        return RedirectResponse(HOME, status_code=303)

    return router
