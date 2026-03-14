import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from trade_proposer_app.config import settings
from trade_proposer_app.domain.models import PreflightCheck, PrototypePreflightReport
from trade_proposer_app.services.proposals import ProposalService


class PrototypePreflightService:
    REQUIRED_IMPORTS: tuple[str, ...] = ("yfinance", "pandas")
    OPTIONAL_IMPORTS: tuple[str, ...] = ("openai",)

    def run(self) -> PrototypePreflightReport:
        checks: list[PreflightCheck] = []
        repo_path = Path(settings.prototype_repo_path)
        script_path = ProposalService.get_prototype_script_path()
        python_executable = settings.prototype_python_executable

        repo_exists = repo_path.exists()
        checks.append(
            PreflightCheck(
                name="prototype_repo_path",
                status="ok" if repo_exists else "failed",
                message="prototype repository found" if repo_exists else f"prototype repository not found: {repo_path}",
            )
        )

        script_exists = script_path.exists()
        checks.append(
            PreflightCheck(
                name="prototype_script",
                status="ok" if script_exists else "failed",
                message="prototype script found" if script_exists else f"prototype script not found: {script_path}",
            )
        )

        resolved_python = self._resolve_python_executable(python_executable)
        checks.append(
            PreflightCheck(
                name="prototype_python",
                status="ok" if resolved_python else "failed",
                message=(
                    f"prototype python resolved: {resolved_python}"
                    if resolved_python
                    else f"prototype python executable not found: {python_executable}"
                ),
            )
        )

        if resolved_python and repo_exists:
            checks.extend(self._run_import_checks(resolved_python, repo_path))
        else:
            for module_name in (*self.REQUIRED_IMPORTS, *self.OPTIONAL_IMPORTS):
                checks.append(
                    PreflightCheck(
                        name=f"python_import:{module_name}",
                        status="skipped",
                        message="skipped because prototype python or repository path is unavailable",
                    )
                )

        status = "ok"
        if any(check.status == "failed" for check in checks):
            status = "failed"
        elif any(check.status == "warning" for check in checks):
            status = "warning"

        return PrototypePreflightReport(
            status=status,
            checked_at=datetime.now(timezone.utc),
            prototype_repo_path=str(repo_path),
            prototype_script_path=str(script_path),
            prototype_python_executable=python_executable,
            checks=checks,
        )

    @staticmethod
    def _resolve_python_executable(executable: str) -> str | None:
        candidate = Path(executable)
        if candidate.is_absolute() or "/" in executable:
            return str(candidate) if candidate.exists() else None
        return shutil.which(executable)

    def _run_import_checks(self, python_executable: str, repo_path: Path) -> list[PreflightCheck]:
        required_missing = self._find_missing_imports(python_executable, repo_path, self.REQUIRED_IMPORTS)
        optional_missing = self._find_missing_imports(python_executable, repo_path, self.OPTIONAL_IMPORTS)

        checks: list[PreflightCheck] = [
            PreflightCheck(
                name="python_imports:required",
                status="ok" if not required_missing else "failed",
                message=(
                    "required prototype imports available"
                    if not required_missing
                    else f"required prototype imports missing: {', '.join(required_missing)}"
                ),
                details=required_missing,
            ),
            PreflightCheck(
                name="python_imports:optional",
                status="ok" if not optional_missing else "warning",
                message=(
                    "optional prototype imports available"
                    if not optional_missing
                    else f"optional prototype imports missing: {', '.join(optional_missing)}"
                ),
                details=optional_missing,
            ),
        ]
        return checks

    @staticmethod
    def _find_missing_imports(python_executable: str, repo_path: Path, modules: tuple[str, ...]) -> list[str]:
        if not modules:
            return []
        command = [
            python_executable,
            "-c",
            (
                "import importlib.util, json; "
                f"modules = {list(modules)!r}; "
                "missing = [name for name in modules if importlib.util.find_spec(name) is None]; "
                "print(json.dumps(missing))"
            ),
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=20,
                cwd=str(repo_path),
            )
        except Exception:
            return list(modules)

        if result.returncode != 0:
            return list(modules)

        try:
            payload = json.loads((result.stdout or "").strip() or "[]")
        except json.JSONDecodeError:
            return list(modules)
        if not isinstance(payload, list):
            return list(modules)
        return [name for name in payload if isinstance(name, str) and name]
