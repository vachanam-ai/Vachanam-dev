# tests/unit/test_dockerfile_lint.py
from pathlib import Path

DOCKERFILE = Path("infra/Dockerfile.agent")


def test_dockerfile_exists():
    assert DOCKERFILE.is_file(), "infra/Dockerfile.agent missing"


def test_dockerfile_python_312_base():
    content = DOCKERFILE.read_text()
    assert "FROM python:3.12-slim" in content, "base image must be python:3.12-slim"


def test_dockerfile_exposes_7860():
    content = DOCKERFILE.read_text()
    assert "EXPOSE 7860" in content


def test_dockerfile_no_livekit():
    content = DOCKERFILE.read_text().lower()
    assert "livekit" not in content, "Dockerfile must not reference livekit"
    assert "livekit-agents" not in content


def test_dockerfile_runs_uvicorn():
    content = DOCKERFILE.read_text()
    assert "uvicorn" in content
    assert "agent.server:app" in content


def test_dockerfile_installs_agent_requirements():
    content = DOCKERFILE.read_text()
    assert "agent/requirements.txt" in content
    assert "pip install" in content


def test_dockerfile_copies_agent_and_backend():
    content = DOCKERFILE.read_text()
    assert "COPY agent/" in content or "COPY agent" in content
    assert "COPY backend/" in content or "COPY backend" in content
