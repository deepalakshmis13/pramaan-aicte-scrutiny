"""Test configuration: an isolated PostgreSQL database and storage directory, seeded once
per session through the same seed script (which itself drives the real API)."""
import os
import tempfile

os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://aicte:aicte_dev@localhost:5432/aicte_verify_test")
os.environ["STORAGE_DIR"] = tempfile.mkdtemp(prefix="pramaan-test-")
os.environ["JOBS_MODE"] = "sync"
os.environ["CROSSREF_MODE"] = "disabled"  # tests never depend on the network
os.environ["LOGIN_RATE_LIMIT_PER_MINUTE"] = "1000"
os.environ["SCOPUS_API_KEY"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.security import login_limiter  # noqa: E402

PW = {"reviewer": "Reviewer@2026", "institution": "Institution@2026", "admin": "Admin@2026"}


@pytest.fixture(scope="session", autouse=True)
def seeded():
    from seed import seed

    assert seed.main(["--reset"]) == 0
    yield


class Client:
    def __init__(self, email: str, password: str):
        self.c = TestClient(app)
        r = self.c.post("/api/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        self.user = r.json()["user"]

    def get(self, path, **kw):
        return self.c.get(path, **kw)

    def post(self, path, json=None, **kw):
        return self.c.post(path, json=json, headers={"X-Requested-With": "pramaan"}, **kw)

    def patch(self, path, json=None):
        return self.c.patch(path, json=json, headers={"X-Requested-With": "pramaan"})

    def delete(self, path):
        return self.c.delete(path, headers={"X-Requested-With": "pramaan"})


@pytest.fixture
def anitha():
    login_limiter.reset()
    return Client("anitha.raman@scrutiny.test", PW["reviewer"])


@pytest.fixture
def vikram():
    return Client("vikram.sethi@scrutiny.test", PW["reviewer"])


@pytest.fixture
def admin():
    return Client("admin@scrutiny.test", PW["admin"])


def inst(email):
    return Client(email, PW["institution"])


def app_id(client, reference_suffix: str) -> int:
    items = client.get("/api/reviewer/applications", params={"page_size": 100}).json()["items"]
    return next(a["id"] for a in items if a["reference"].endswith(reference_suffix))
