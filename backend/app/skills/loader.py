"""Safe loader for project-local SKILL.md files."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SKILLS_ROOT = (PROJECT_ROOT / "skills").resolve()


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    description: str
    version: str
    path: str
    source: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _read_frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}
    _, frontmatter, _ = text.split("---", 2)
    values: dict[str, str] = {}
    for line in frontmatter.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _safe_path(path: Path) -> Path:
    resolved = path.resolve()
    if SKILLS_ROOT not in resolved.parents and resolved != SKILLS_ROOT:
        raise ValueError("Skill path is outside the project skills directory")
    return resolved


def discover_skills() -> list[SkillDefinition]:
    if not SKILLS_ROOT.is_dir():
        return []
    skills: list[SkillDefinition] = []
    for skill_file in sorted(SKILLS_ROOT.rglob("SKILL.md")):
        try:
            path = _safe_path(skill_file)
            meta = _read_frontmatter(path)
            relative = path.relative_to(PROJECT_ROOT).as_posix()
            source = "local" if relative.startswith("skills/local/") else "vendor"
            skills.append(
                SkillDefinition(
                    name=meta.get("name") or path.parent.name,
                    description=meta.get("description", ""),
                    version=meta.get("version", "unversioned"),
                    path=relative,
                    source=source,
                )
            )
        except (OSError, ValueError):
            continue
    return skills
