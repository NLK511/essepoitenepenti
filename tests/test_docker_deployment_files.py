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


def test_long_lived_services_do_not_depend_on_one_shot_migrate_completion() -> None:
    compose = Path("docker-compose.yml").read_text()
    assert "condition: service_completed_successfully" not in compose
    assert "condition: service_healthy" in compose


def test_docker_up_runs_from_repo_root_and_migrates_before_app_services() -> None:
    script = Path("scripts/docker-up.sh").read_text()
    assert "ROOT_DIR" in script
    assert "cd \"$ROOT_DIR\"" in script
    assert "up -d --wait postgres" in script
    assert "run --rm migrate" in script
    assert "up -d --wait \"$@\" api worker scheduler" in script


def test_dockerfile_builds_frontend_installs_pi_and_installs_app_at_build_time() -> None:
    dockerfile = Path("Dockerfile").read_text()
    assert "AS frontend-build" in dockerfile
    assert "npm run build" in dockerfile
    assert "AS pi-cli" in dockerfile
    assert "@earendil-works/pi-coding-agent" in dockerfile
    assert "/usr/local/bin/pi" in dockerfile
    assert "pip install -e ." in dockerfile
    assert "uvicorn" in dockerfile


def test_compose_mounts_pi_agent_auth_for_app_containers() -> None:
    compose = Path("docker-compose.yml").read_text()
    assert "PI_AGENT_HOST_DIR" in compose
    assert compose.count("/home/appuser/.pi/agent:rw") == 3
    env_example = Path(".env.docker.example").read_text()
    assert "PI_AGENT_HOST_DIR=/home/tradeapp/.pi/agent" in env_example


def test_compose_allows_app_containers_to_reach_host_published_nitter() -> None:
    compose = Path("docker-compose.yml").read_text()
    assert compose.count("host.docker.internal:host-gateway") == 3
