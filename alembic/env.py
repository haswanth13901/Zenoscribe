import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from voice_transcriber import config as app_config  # noqa: E402

config = context.config

# disable_existing_loggers=False is required here: fileConfig() defaults to
# True, which silently disables every logger not listed in alembic.ini's
# [loggers] section - including uvicorn's. Since db.init() runs this on every
# app startup (not just via the `alembic` CLI), the default would silence
# uvicorn's "Application startup complete"/"Uvicorn running on..." messages,
# making the app look hung even though it's already serving requests.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = None


def _sqlalchemy_url() -> str:
    """Resolve the DB URL fresh on every invocation (env.py is re-executed
    per alembic command). Always goes through app_config.DATABASE_URL rather
    than os.environ directly, so that monkeypatching app_config.DATABASE_URL
    (as tests do, to point migrations at a schema-scoped URL) reliably wins -
    an ambient DATABASE_URL env var would otherwise always shadow it.
    """
    url = app_config.DATABASE_URL
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_sqlalchemy_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _sqlalchemy_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
