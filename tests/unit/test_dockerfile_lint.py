# tests/unit/test_dockerfile_lint.py
import tomllib
from pathlib import Path

DOCKERFILE = Path("infra/Dockerfile.agent")


def test_dockerfile_exists():
    assert DOCKERFILE.is_file(), "infra/Dockerfile.agent missing"


def test_dockerfile_python_312_base():
    content = DOCKERFILE.read_text()
    assert "FROM python:3.12-slim" in content, "base image must be python:3.12-slim"


def test_dockerfile_runs_livekit_worker_not_dead_server():
    """iter1 #2: the image must launch the real LiveKit Agents worker, not the
    retired Pipecat/Vobiz `uvicorn agent.server:app` path (which has been deleted).

    The old test asserted `agent.server:app` was PRESENT (it enforced the bug).
    This inverts that: the worker command must be present and the dead server
    command must be ABSENT.
    """
    content = DOCKERFILE.read_text()
    assert "agent.livekit_minimal.agent" in content, (
        "Dockerfile must launch the LiveKit worker"
    )
    assert '"start"' in content, "worker must be started via the `start` subcommand"
    assert "agent.server:app" not in content, (
        "retired Pipecat/Vobiz server path must not be referenced"
    )


def test_dockerfile_does_not_run_uvicorn():
    """The worker dials OUT and serves no inbound HTTP — no uvicorn app server."""
    content = DOCKERFILE.read_text()
    assert "uvicorn agent.server" not in content
    assert "uvicorn" not in content, "no inbound HTTP app server in the agent image"


def test_dockerfile_installs_livekit_and_backend_requirements():
    content = DOCKERFILE.read_text()
    assert "livekit_minimal/requirements.txt" in content
    assert "backend/requirements.txt" in content
    assert "pip install" in content


def test_dockerfile_copies_agent_and_backend():
    content = DOCKERFILE.read_text()
    assert "COPY agent/" in content or "COPY agent" in content
    assert "COPY backend/" in content or "COPY backend" in content


def test_dockerfile_runs_as_non_root():
    """TD-014 must survive the retirement: the worker still drops root."""
    content = DOCKERFILE.read_text()
    assert "USER appuser" in content


def test_fly_deploy_waits_for_livekit_worker_readiness():
    config = tomllib.loads(Path("infra/fly.agent.toml").read_text())
    assert config["deploy"]["strategy"] == "bluegreen"
    assert config["deploy"]["wait_timeout"] == "5m"
    ready = config["checks"]["worker_ready"]
    assert ready["type"] == "tcp"
    assert ready["port"] == 8081
    assert ready["grace_period"] == "30s"


def test_docs_only_push_does_not_restart_voice_worker():
    workflow = Path(".github/workflows/ci.yml").read_text()
    assert "Detect agent-runtime changes" in workflow
    assert "git diff --quiet" in workflow
    assert "agent backend infra/Dockerfile.agent infra/fly.agent.toml" in workflow
    assert "if: steps.agent_runtime.outputs.changed == 'true'" in workflow
