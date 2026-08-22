"""Application entrypoint.

Deliberately thin. It creates the app, serves the three pages, and mounts
two independent routers:

    routes_api.py   auth, user administration, recording access
    transcribe.py   the realtime Soniox bridge and turn-detection engine

Neither router imports the other. Both depend only on auth.py, db.py, and
config.py, so the transcription engine can be reworked without touching
login behaviour, and vice versa.
"""

import asyncio
import logging

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

try:
    from . import auth
    from . import config
    from . import db
    from . import languages
    from . import rate_limit
    from . import routes_api
    from . import transcribe
    from . import translate
except ImportError:  # run flat from inside the package dir
    import auth
    import config
    import db
    import languages
    import rate_limit
    import routes_api
    import transcribe
    import translate

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("server")

app = FastAPI(title="Zenoscribe")
# Per-IP safety net on every request/WS handshake - see rate_limit.py.
# Specific expensive endpoints (uploads, WS connects) have their own
# tighter per-user limits declared where they're defined.
app.add_middleware(rate_limit.GlobalRateLimitMiddleware)


class _DevOnlyCORSMiddleware:
    """Forwards to Starlette's CORSMiddleware only when config.PRODUCTION is
    False - read fresh on every request rather than captured once when this
    middleware is constructed, the same way config.ALLOW_TEST_HOOKS is
    re-checked per-request elsewhere in this repo (routes_api.py), so tests
    can flip config.PRODUCTION via monkeypatch and see the change take
    effect on the same app/TestClient instance. Production stays same-origin
    behind Caddy with zero CORS surface either way."""

    def __init__(self, app, **cors_kwargs):
        self._app = app
        self._cors_app = CORSMiddleware(app, **cors_kwargs)

    async def __call__(self, scope, receive, send):
        target = self._app if config.PRODUCTION else self._cors_app
        await target(scope, receive, send)


# Dev-only: lets the browser call this app directly at its dev port (e.g.
# while iterating without going through the Vite proxy at :8000). Gated off
# entirely in production - see _DevOnlyCORSMiddleware above.
app.add_middleware(
    _DevOnlyCORSMiddleware,
    allow_origins=[config.DEV_FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.on_event("startup")
def _startup():
    db.init()
    seeded = auth.ensure_seed_admin()
    if seeded:
        username, generated_flag = seeded
        if generated_flag:
            # In non-production, a generated password was used. Avoid logging the
            # actual password so it doesn't leak into logs; instruct the operator
            # to rotate it after first login.
            log.warning(
                "Created admin '%s' with a generated password (development/testing only). Change it after first login.",
                username,
            )
        else:
            log.info("Created admin '%s' from ADMIN_PASSWORD", username)


@app.on_event("shutdown")
def _shutdown():
    db.close_pool()


@app.get("/")
async def root():
    # login.html is sourced from frontend/public/ (single source of truth
    # for all frontend files - see the repo README's "Frontend" section)
    # and lands here via Vite's public-dir copy when frontend/ is built.
    return FileResponse(f"{config.FRONTEND_DIST_DIR}/login.html")


@app.get("/login")
async def login_page():
    return FileResponse(f"{config.FRONTEND_DIST_DIR}/login.html")


@app.get("/home")
@app.get("/home/")
async def home_page():
    # /home and /app are both client-side routes of the one React SPA built
    # by frontend/ into frontend/dist/ - see the repo README's "Frontend"
    # section to build it. More routes join this same shell as more pages
    # migrate (admin, translate).
    return FileResponse(f"{config.FRONTEND_DIST_DIR}/index.html")


@app.get("/app")
@app.get("/app/")
async def app_page():
    # Same built SPA shell as /home (see above); react-router decides what
    # renders client-side. Both the bare and trailing-slash forms are served
    # directly so a stray slash doesn't cause a 307 redirect.
    return FileResponse(f"{config.FRONTEND_DIST_DIR}/index.html")


@app.get("/admin")
@app.get("/admin/")
async def admin_page():
    # Same built SPA shell as /home and /app; react-router decides what
    # renders client-side (and gates it to admins - see RequireAuth's
    # adminOnly prop in frontend/).
    return FileResponse(f"{config.FRONTEND_DIST_DIR}/index.html")


@app.get("/translate")
@app.get("/translate/")
async def translate_page():
    # Same built SPA shell as /home, /app and /admin; react-router decides
    # what renders client-side.
    return FileResponse(f"{config.FRONTEND_DIST_DIR}/index.html")


@app.get("/recordings")
@app.get("/recordings/")
async def recordings_page():
    # Same built SPA shell as the other four; the current user's own
    # recordings, filterable by date - formerly a slide-out drawer over
    # /app, now its own route. Distinct from GET /api/recordings (routes_api.py).
    return FileResponse(f"{config.FRONTEND_DIST_DIR}/index.html")


@app.get("/upload")
@app.get("/upload/")
async def upload_page():
    # Same built SPA shell as the other five; the batch transcribe form -
    # formerly opened as a panel over /app or /admin via a ?upload=1
    # deep-link, now its own route so it isn't rendered on top of either
    # page's leftover content. Distinct from POST /api/transcribe/translate
    # (transcribe.py), which this page's form submits to.
    return FileResponse(f"{config.FRONTEND_DIST_DIR}/index.html")


@app.get("/service-worker.js")
async def service_worker():
    # Served from "/" rather than under the /static mount below: a service
    # worker's default scope is capped at the directory it's served from,
    # so serving it from /static/ would only ever let it control /static/
    # requests. Service-Worker-Allowed widens that to the whole app - the
    # file itself still lands in frontend/dist/ via Vite's public-dir copy,
    # same mechanism as login.html/theme.css, just read from a second route.
    return FileResponse(
        f"{config.FRONTEND_DIST_DIR}/service-worker.js",
        media_type="text/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )


@app.get("/healthz")
async def healthz(response: Response):
    """Liveness + readiness probe for Caddy/Compose/monitoring.
    Unauthenticated by design, but reports nothing beyond ok/degraded - no
    version, no config - so it's safe to leave open on the public path.
    """
    try:
        await asyncio.to_thread(db.ping)
    except Exception:
        log.exception("healthz: database readiness check failed")
        response.status_code = 503
        return {"status": "degraded", "database": "unreachable"}
    return {"status": "ok", "database": "ok"}


@app.get("/api/languages")
async def language_list():
    return {
        "languages": [{"code": c, "name": n} for c, n in languages.LANGUAGES],
        "voices": ["Maya", "Adrian"],
    }


app.include_router(routes_api.router)
app.include_router(transcribe.router)
app.include_router(translate.router)


class NoCacheStaticFiles(StaticFiles):
    """Forces revalidation on every request so browsers can't keep serving
    a stale cached JS/CSS file after an update (ETag-based conditional
    requests already work, so this costs only a cheap 304 when unchanged).
    """

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


# NOTE: the recordings directory is deliberately NOT mounted as static.
# Serving it would let anyone with a filename bypass auth entirely.
# All access goes through /api/recordings/{id}/audio, which checks ownership.
app.mount("/static", NoCacheStaticFiles(directory=config.FRONTEND_DIST_DIR), name="static")
