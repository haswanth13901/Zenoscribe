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
        username, generated_pw = seeded
        if generated_pw:
            log.warning(
                "Created admin '%s' with generated password: %s  "
                "(change it after first login)",
                username, generated_pw,
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
async def app_page():
    # The page itself is public; its JS redirects without a token and every
    # API call behind it is authenticated server-side.
    return FileResponse(f"{config.STATIC_DIR}/index.html")


@app.get("/admin")
async def admin_page():
    return FileResponse(f"{config.STATIC_DIR}/admin.html")


@app.get("/translate")
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

# NOTE: the recordings directory is deliberately NOT mounted as static.
# Serving it would let anyone with a filename bypass auth entirely.
# All access goes through /api/recordings/{id}/audio, which checks ownership.
app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")