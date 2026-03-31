import re
from pathlib import Path

from fastapi import APIRouter

router = APIRouter(prefix="/docs", tags=["docs"])

REPO_ROOT = Path(__file__).resolve().parents[4]
DOC_PATHS = [REPO_ROOT / "README.md", *sorted((REPO_ROOT / "docs").rglob("*.md"))]
HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def slugify_heading(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return normalized.strip("-") or "section"


def extract_title(content: str, fallback: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return fallback


def extract_sections(content: str) -> list[dict[str, object]]:
    sections: list[dict[str, object]] = []
    seen_ids: dict[str, int] = {}
    for line in content.splitlines():
        match = HEADING_PATTERN.match(line.strip())
        if match is None:
            continue
        level = len(match.group(1))
        if level <= 1:
            continue
        title = match.group(2).strip()
        base_id = slugify_heading(title)
        duplicate_index = seen_ids.get(base_id, 0)
        seen_ids[base_id] = duplicate_index + 1
        section_id = base_id if duplicate_index == 0 else f"{base_id}-{duplicate_index + 1}"
        sections.append({"id": section_id, "title": title, "level": level})
    return sections


def build_slug(path: Path) -> str:
    if path == REPO_ROOT / "README.md":
        return "readme"

    relative_path = path.relative_to(REPO_ROOT)
    if relative_path.parts and relative_path.parts[0] == "docs":
        relative_path = Path(*relative_path.parts[1:])

    stem_path = relative_path.with_suffix("")
    parts = [part.lower() for part in stem_path.parts]
    return "-".join(parts)


@router.get("")
async def list_docs() -> dict[str, object]:
    documents: list[dict[str, object]] = []
    for path in DOC_PATHS:
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8")
        documents.append(
            {
                "slug": build_slug(path),
                "title": extract_title(content, path.stem.replace("-", " ").title()),
                "path": str(path.relative_to(REPO_ROOT)),
                "content": content,
                "sections": extract_sections(content),
            }
        )
    return {"documents": documents}
