from alembic import context
from app.config import get_settings
from app.db import Base, engine
from app import models  # noqa: F401

target_metadata = Base.metadata


def run():
    with engine().connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, render_as_batch=conn.dialect.name == "sqlite")
        with context.begin_transaction():
            context.run_migrations()


run()
