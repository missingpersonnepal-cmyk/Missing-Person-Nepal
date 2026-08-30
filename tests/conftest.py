import os
import uuid
from pathlib import Path

TEST_DB_NAME = f"test_missing_person_{uuid.uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite:///./{TEST_DB_NAME}"
os.environ["SESSION_SECRET"] = "test-session-secret"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "test-password"
os.environ["AUTO_CREATE_TABLES"] = "true"
os.environ["UPLOAD_DIR"] = "test_uploads"
os.environ["EXPORT_DIR"] = "test_exports"

import pytest
from fastapi.testclient import TestClient

from app.database import Base, engine
from app.main import app, seed_admin


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    seed_admin()
    yield
    Base.metadata.drop_all(engine)
    engine.dispose()
    db_path = Path(TEST_DB_NAME)
    if db_path.exists():
        db_path.unlink()
    for folder in (Path("test_uploads"), Path("test_exports")):
        if folder.exists():
            for child in folder.iterdir():
                if child.is_file():
                    child.unlink()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def admin_client(client):
    response = client.post("/admin/login", data={"username": "admin", "password": "test-password"}, follow_redirects=False)
    assert response.status_code == 303
    return client
