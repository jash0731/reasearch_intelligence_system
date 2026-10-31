import os
from contextlib import contextmanager
from uuid import uuid4
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
import pytest


@pytest.fixture(scope='session')
def postgres_database_factory():
    raw = os.getenv('TEST_DATABASE_URL', '')
    if not raw:
        raise pytest.UsageError('Set TEST_DATABASE_URL to a dedicated PostgreSQL *_test database. See README.md.')
    target = make_url(raw)
    if target.get_backend_name() != 'postgresql' or not (target.database or '').endswith('_test'):
        raise pytest.UsageError('Tests require a PostgreSQL database whose name ends with _test; demo databases are refused.')
    target = target.set(drivername='postgresql+psycopg')
    admin = create_engine(target, pool_pre_ping=True)

    @contextmanager
    def isolated_schema():
        name = 'vit_test_' + uuid4().hex
        with admin.begin() as conn:
            conn.exec_driver_sql(f'CREATE SCHEMA "{name}"')
        uri = target.update_query_dict({'options': '-csearch_path=' + name}).render_as_string(hide_password=False)
        try:
            yield uri
        finally:
            with admin.begin() as conn:
                conn.exec_driver_sql(f'DROP SCHEMA "{name}" CASCADE')
    yield isolated_schema
    admin.dispose()

