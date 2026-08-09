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


# ------------------------------------------------------------------ pages


@app.get("/")
async def root():
    return FileResponse(f"{config.STATIC_DIR}/login.html")


@app.get("/login")
async def login_page():
    return FileResponse(f"{config.STATIC_DIR}/login.html")


@app.get("/app")
@app.get("/app/")
async def app_page():
    # The page itself is public; its JS redirects without a token and every
    # API call behind it is authenticated server-side. Both the bare and
    # trailing-slash forms are served directly so a stray slash doesn't cause
    # a 307 redirect that can compound with the client-side auth redirect.
    return FileResponse(f"{config.STATIC_DIR}/index.html")


@app.get("/admin")
@app.get("/admin/")
async def admin_page():
    return FileResponse(f"{config.STATIC_DIR}/admin.html")


@app.get("/translate")
@app.get("/translate/")
async def translate_page():
    return FileResponse(f"{config.STATIC_DIR}/translate.html")


@app.get("/api/languages")
async def language_list():
    """Options for the translator dropdowns."""
    return {
        "languages": [{"code": c, "name": n} for c, n in languages.LANGUAGES],
        "voices": ["Maya", "Adrian"],
    }


# ---------------------------------------------------------------- routers

app.include_router(routes_api.router)
app.include_router(transcribe.router)
app.include_router(translate.router)

class NoCacheStaticFiles(StaticFiles):
    """StaticFiles that forces revalidation on every request.

    Without an explicit Cache-Control header, browsers apply their own
    heuristic freshness lifetime and can keep serving an old cached copy of
    a JS/CSS file for a while without ever asking the server - which is
    exactly what let a stale header.js linger in a browser after an update.
    ETag/Last-Modified based conditional requests already work correctly
    (StaticFiles handles those), so "no-cache" (not "no-store") is enough:
    the browser still caches the body, it just always revalidates first,
    getting a cheap 304 when nothing changed and the real bytes only when
    something did.
    """

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


# NOTE: the recordings directory is deliberately NOT mounted as static.
# Serving it would let anyone with a filename bypass auth entirely.
# All access goes through /api/recordings/{id}/audio, which checks ownership.
app.mount("/static", NoCacheStaticFiles(directory=config.STATIC_DIR), name="static")