from pathlib import Path


def test_docker_deployment_files_exist() -> None:
    assert Path("Dockerfile").exists()
    assert Path("docker-compose.yml").exists()
    assert Path(".dockerignore").exists()
    assert Path(".env.docker.example").exists()


def test_compose_contains_required_services_and_restart_policies() -> None:
    compose = Path("docker-compose.yml").read_text()
    for service in ("postgres:", "api:", "worker:", "scheduler:"):
        assert service in compose
    assert compose.count("restart: unless-stopped") >= 4
    assert "container_name:" not in compose
    assert "postgres_data:/var/lib/postgresql/data" in compose
    assert "./backups:/backups" in compose
    assert "healthcheck:" in compose
    assert "5432:5432" not in compose


def test_dockerfile_builds_frontend_and_installs_app_at_build_time() -> None:
    dockerfile = Path("Dockerfile").read_text()
    assert "AS frontend-build" in dockerfile
    assert "npm run build" in dockerfile
    assert "pip install -e ." in dockerfile
    assert "uvicorn" in dockerfile
