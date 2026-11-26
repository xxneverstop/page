"""On-demand loading for simple ``skills/<name>/SKILL.md`` directories."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SkillMetadata:
    name: str
    description: str
    path: Path
    source_hash: str


@dataclass(frozen=True, slots=True)
class Skill:
    metadata: SkillMetadata
    body: str


class SkillStore:
    """Discover metadata cheaply and read bodies only when selected."""

    def __init__(self, root: str | Path = "skills"):
        self.root = Path(root).resolve()

    def discover(self) -> list[SkillMetadata]:
        if not self.root.is_dir():
            return []
        result: list[SkillMetadata] = []
        for directory in sorted(self.root.iterdir()):
            path = directory / "SKILL.md"
            if not directory.is_dir() or not path.is_file():
                continue
            body = path.read_text(encoding="utf-8")
            description = _description(body)
            result.append(SkillMetadata(directory.name, description, path, _hash(body)))
        return result

    def load(self, name: str) -> Skill:
        metadata = next((item for item in self.discover() if item.name == name), None)
        if metadata is None:
            raise KeyError(f"unknown skill: {name}")
        body = metadata.path.read_text(encoding="utf-8")
        return Skill(metadata, body)

    def select(self, names: list[str] | tuple[str, ...]) -> list[Skill]:
        return [self.load(name) for name in names]


def render_skill_context(skills: list[Skill]) -> str:
    """Render selected skills without bypassing tool or approval boundaries."""
    sections = []
    for skill in skills:
        sections.append(f"## Skill: {skill.metadata.name}\n{skill.body.rstrip()}")
    return "\n\n".join(sections)


def _description(body: str) -> str:
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("description:"):
            return line.partition(":")[2].strip().strip("'\"")
    for line in body.splitlines():
        if line.strip() and not line.startswith("#"):
            return line.strip()[:200]
    return ""


def _hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()

