"""Mechanically synchronize per-skill data-file entries in pyproject.toml."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = ROOT / "pyproject.toml"
START = "# BEGIN GENERATED OPERATIONAL SKILL DATA FILES"
END = "# END GENERATED OPERATIONAL SKILL DATA FILES"


def main() -> None:
    text = PYPROJECT.read_text(encoding="utf-8")
    if START in text:
        text = text[: text.index(START)].rstrip() + "\n"
    lines = [START]
    existing = {
        "admit-capability", "commission-project", "diagnose-python-repair", "enforce-governance-controls",
        "orchestrate-engineering-loop", "research-to-capability", "validate-engineering-outcomes", "verify-outcome",
    }
    for path in sorted((ROOT / ".agents" / "skills").iterdir(), key=lambda item: item.name):
        if not path.is_dir() or path.name in existing:
            continue
        skill_id = path.name
        lines.append(
            f'"share/engineering-bootstrap/.agents/skills/{skill_id}" = '
            f'[".agents/skills/{skill_id}/SKILL.md"]'
        )
        lines.append(
            f'"share/engineering-bootstrap/.agents/skills/{skill_id}/agents" = '
            f'[".agents/skills/{skill_id}/agents/openai.yaml"]'
        )
        references = sorted((path / "references").glob("*.md")) if (path / "references").is_dir() else []
        if references:
            values = ", ".join(f'"{item.relative_to(ROOT).as_posix()}"' for item in references)
            lines.append(
                f'"share/engineering-bootstrap/.agents/skills/{skill_id}/references" = [{values}]'
            )
        scripts = sorted((path / "scripts").glob("*.py")) if (path / "scripts").is_dir() else []
        if scripts:
            values = ", ".join(f'"{item.relative_to(ROOT).as_posix()}"' for item in scripts)
            lines.append(
                f'"share/engineering-bootstrap/.agents/skills/{skill_id}/scripts" = [{values}]'
            )
        assets = sorted(item for item in (path / "assets").rglob("*") if item.is_file()) if (path / "assets").is_dir() else []
        if assets:
            values = ", ".join(f'"{item.relative_to(ROOT).as_posix()}"' for item in assets)
            lines.append(
                f'"share/engineering-bootstrap/.agents/skills/{skill_id}/assets" = [{values}]'
            )
    lines.append(END)
    PYPROJECT.write_text(text.rstrip() + "\n" + "\n".join(lines) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
