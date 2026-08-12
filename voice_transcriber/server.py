"""Application entrypoint.

Deliberately thin. It creates the app, serves the three pages, and mounts
two independent routers:

    routes_api.py   auth, user administration, recording access
    transcribe.py   the realtime Soniox bridge and turn-detection engine

Neither router imports the other. Both depend only on auth.py, db.py, and
config.py, so the transcription engine can be reworked without touching
login behaviour, and vice versa.
"""

import logging

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

try:
    from . import auth
    from . import config
    from . import db
    from . import languages
    from . import routes_api
    from . import transcribe
    from . import translate
except ImportError:  # run flat from inside the package dir
    import auth
    import config
    import db
    import languages
    import routes_api
    import transcribe
    import translate

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("server")

app = FastAPI(title="Zenoscribe")


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


@app.get("/")
async def root():
    return FileResponse(f"{config.STATIC_DIR}/login.html")


@app.get("/login")
async def login_page():
    return FileResponse(f"{config.STATIC_DIR}/login.html")


@app.get("/home")
@app.get("/home/")
async def home_page():
    # /home and /app are both client-side routes of the one React SPA built
    # by frontend/ into static/spa_dist/ - see the repo README's "Frontend"
    # section to build it. More routes join this same shell as more pages
    # migrate (admin, translate).
    return FileResponse(f"{config.STATIC_DIR}/spa_dist/index.html")


@app.get("/app")
@app.get("/app/")
async def app_page():
    # Same built SPA shell as /home (see above); react-router decides what
    # renders client-side. Both the bare and trailing-slash forms are served
    # directly so a stray slash doesn't cause a 307 redirect.
    return FileResponse(f"{config.STATIC_DIR}/spa_dist/index.html")


@app.get("/admin")
@app.get("/admin/")
async def admin_page():
    # Same built SPA shell as /home and /app; react-router decides what
    # renders client-side (and gates it to admins - see RequireAuth's
    # adminOnly prop in frontend/).
    return FileResponse(f"{config.STATIC_DIR}/spa_dist/index.html")


@app.get("/translate")
@app.get("/translate/")
async def translate_page():
    # Same built SPA shell as /home, /app and /admin; react-router decides
    # what renders client-side.
    return FileResponse(f"{config.STATIC_DIR}/spa_dist/index.html")


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
app.mount("/static", NoCacheStaticFiles(directory=config.STATIC_DIR), name="static")