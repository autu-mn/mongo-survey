import os

os.environ["MONGO_DB"] = "survey_system_test"

import pytest

from app.db import get_client, init_db
from app.config import settings


@pytest.fixture
def db():
    client = get_client()
    client.drop_database(settings.mongo_db)
    database = client[settings.mongo_db]
    init_db(database)
    yield database
    client.drop_database(settings.mongo_db)
