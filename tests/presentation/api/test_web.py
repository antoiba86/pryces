import pytest
from fastapi.testclient import TestClient

from pryces.presentation.api.main import WEB_DIR_ENV_VAR, create_app, resolve_web_dir


@pytest.fixture
def web_dir(tmp_path, monkeypatch):
    directory = tmp_path / "web"
    directory.mkdir()
    (directory / "index.html").write_text("<!doctype html><title>CaudalNet</title>")
    monkeypatch.setenv(WEB_DIR_ENV_VAR, str(directory))
    return directory


class TestResolveWebDir:
    def test_uses_env_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv(WEB_DIR_ENV_VAR, str(tmp_path))
        assert resolve_web_dir() == tmp_path

    def test_expands_user(self, monkeypatch):
        monkeypatch.setenv(WEB_DIR_ENV_VAR, "~/dashboard")
        assert "~" not in str(resolve_web_dir())


class TestBundledDashboard:
    def test_serves_index_at_root(self, web_dir):
        client = TestClient(create_app())
        response = client.get("/")

        assert response.status_code == 200
        assert "CaudalNet" in response.text

    def test_api_still_reachable_under_prefix(self, web_dir):
        client = TestClient(create_app())

        assert client.get("/api/health").json() == {"status": "ok"}


class TestHeadlessDeployment:
    def test_root_is_absent_without_a_web_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv(WEB_DIR_ENV_VAR, str(tmp_path / "missing"))
        client = TestClient(create_app())

        assert client.get("/").status_code == 404

    def test_api_unaffected_without_a_web_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv(WEB_DIR_ENV_VAR, str(tmp_path / "missing"))
        client = TestClient(create_app())

        assert client.get("/api/health").json() == {"status": "ok"}
