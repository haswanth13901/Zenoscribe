"""Application entrypoint.

Deliberately thin. It creates the app and mounts two independent routers:

    routes_api.py   auth, user administration, recording access - itself a
                    thin aggregator over routers/ (one module per domain)
    transcribe.py   the realtime Soniox bridge and turn-detection engine

Neither router imports the other. Both depend only on auth.py, db.py, and
config.py, so the transcription engine can be reworked without touching
login behaviour, and vice versa.

Page-serving (the SPA shell, login.html, /static, service-worker.js) is
registered only when frontend/dist/ actually exists on disk - see
SERVE_FRONTEND below. It's absent by design in the production backend
image (frontend/Dockerfile's nginx container serves pages there instead),
but present in dev (docker-compose.yml, a plain `npm run build` +
`uvicorn --reload`) and in the Vite-dev-server proxy workflow, so both
keep working unchanged.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

try:
    from . import auth
    from . import config
    from . import db
    from . import languages
    from . import live_sessions
    from . import rate_limit
    from . import redis_client
    from . import routes_api
    from . import transcribe
    from . import translate
except ImportError:  # run flat from inside the package dir
    import auth
    import config
    import db
    import languages
    import live_sessions
    import rate_limit
    import redis_client
    import routes_api
    import transcribe
    import translate

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("server")

_ready = True

# How long a graceful shutdown waits for active live sessions (transcribe.py
# /ws, translate.py /ws/translate) to wrap up and persist their recording
# before the process exits. Whatever's still running the process exits
# behaves like today's un-graceful restart already does (session lost) -
# this is a best-effort improvement, not a hard guarantee (see
# live_sessions.py). Must be shorter than however long the container
# orchestrator waits before SIGKILL-ing the process (Docker Compose's
# `stop_grace_period`, set accordingly in docker-compose.prod.yml) or the
# drain gets killed mid-wait with no benefit over not draining at all.
GRACEFUL_SHUTDOWN_GRACE_SEC = int(os.environ.get("GRACEFUL_SHUTDOWN_GRACE_SEC", "30"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown for the whole app, in one place.

    Replaces the deprecated @app.on_event("startup"/"shutdown") pair.
    Everything before the `yield` runs before uvicorn accepts its first
    connection; everything after runs once uvicorn begins its shutdown
    sequence (SIGTERM). Startup work here is blocking and deliberately
    so - nothing is being served yet, and the app must not come up at
    all if the schema check or the seed-admin step fails.
    """
    global _ready

    # Reset explicitly: a real production process only starts once, but
    # TestClient (see conftest.py's `client` fixture) runs a full
    # startup/shutdown cycle per test against this same shared `app`
    # instance, and the post-yield half below flips this to False -
    # without resetting it here, every test after the first would see
    # /healthz permanently report "shutting_down".
    _ready = True

    # Migrations are NOT run here (see db.init()'s docstring) - this only
    # verifies the schema a deploy-time migration step already applied is
    # the one this code expects, and refuses to serve otherwise. Required
    # once more than one replica can start concurrently (see
    # SCALABILITY_AUDIT.md finding F4); harmless for a single instance too.
    db.verify_schema_current()
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

    yield

    # Flip /healthz to unready immediately so an external load balancer/
    # orchestrator stops routing new requests and new WS connection
    # attempts here - see the /healthz handler below. This is the FastAPI/
    # Starlette "lifespan shutdown" hook, which fires as soon as uvicorn
    # begins its own shutdown sequence (SIGTERM), independent of however
    # long the rest of this function takes.
    _ready = False

    still_active = await live_sessions.request_shutdown_and_wait(GRACEFUL_SHUTDOWN_GRACE_SEC)
    if still_active:
        log.warning(
            "shutdown: %d live session(s) still active after %ds grace period; "
            "exiting anyway (matches an ordinary ungraceful restart's behavior)",
            still_active, GRACEFUL_SHUTDOWN_GRACE_SEC,
        )

    db.close_pool()
    redis_client.close_client()


app = FastAPI(title="Zenoscribe", lifespan=lifespan)
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
    behind nginx with zero CORS surface either way."""

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


# See the module docstring: absent in the production backend image (its own
# frontend/nginx container serves pages instead), present in dev/Compose-dev,
# where a build has actually produced this directory.
SERVE_FRONTEND = Path(config.FRONTEND_DIST_DIR).is_dir()

if SERVE_FRONTEND:

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
        # Both bare and trailing-slash forms are served directly so a stray
        # slash doesn't cause a 307 redirect.
        return FileResponse(f"{config.FRONTEND_DIST_DIR}/index.html")

    @app.get("/admin")
    @app.get("/admin/")
    async def admin_page():
        # Gated to admins client-side - see RequireAuth's adminOnly prop in
        # frontend/.
        return FileResponse(f"{config.FRONTEND_DIST_DIR}/index.html")

    @app.get("/translate")
    @app.get("/translate/")
    async def translate_page():
        return FileResponse(f"{config.FRONTEND_DIST_DIR}/index.html")

    @app.get("/recordings")
    @app.get("/recordings/")
    async def recordings_page():
        # Distinct from GET /api/recordings (routes_api.py).
        return FileResponse(f"{config.FRONTEND_DIST_DIR}/index.html")

    @app.get("/upload")
    @app.get("/upload/")
    async def upload_page():
        # Distinct from POST /api/transcribe/translate (transcribe.py), which
        # this page's form submits to.
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
    """Liveness + readiness probe for nginx/Compose/monitoring.
    Unauthenticated by design. Reports ok/degraded plus which build is
    running (version/git_sha, baked in at image build time - see
    config.APP_VERSION/GIT_SHA) - no other config is exposed here.

    Checked first, before touching the database at all: once a graceful
    shutdown has started (the post-yield half of lifespan() in this
    module), this immediately reports unready so an external load balancer
    stops routing new requests/WS connections here - see
    GRACEFUL_SHUTDOWN_GRACE_SEC's
    docstring above for why this needs to happen before, not during, the
    session-drain wait.
    """
    version_fields = {"version": config.APP_VERSION, "git_sha": config.GIT_SHA}
    if not _ready:
        response.status_code = 503
        return {"status": "shutting_down", "database": "unknown", **version_fields}
    try:
        await asyncio.to_thread(db.ping)
    except Exception:
        log.exception("healthz: database readiness check failed")
        response.status_code = 503
        return {"status": "degraded", "database": "unreachable", **version_fields}
    return {"status": "ok", "database": "ok", **version_fields}


@app.get("/api/languages")
async def language_list():
    return {
        "languages": [{"code": c, "name": n} for c, n in languages.LANGUAGES],
        "voices": ["Maya", "Adrian"],
    }


app.include_router(routes_api.router)
app.include_router(transcribe.router)
app.include_router(translate.router)


if SERVE_FRONTEND:

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
