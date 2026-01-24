import re
from pathlib import Path


def to_snake_case(name: str) -> str:
    """Convert PascalCase or camelCase to snake_case."""
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def to_pascal_case(name: str) -> str:
    """Convert snake_case to PascalCase."""
    return "".join(word.capitalize() for word in name.split("_"))


def to_plural(name: str) -> str:
    """Simple pluralization for collection names."""
    if name.endswith("y") and name[-2] not in "aeiou":
        return name[:-1] + "ies"
    if name.endswith(("s", "x", "z", "ch", "sh")):
        return name + "es"
    return name + "s"


def get_project_root() -> Path:
    """Get the project root directory."""
    current = Path.cwd()
    while current != current.parent:
        if (current / "pyproject.toml").exists():
            return current
        current = current.parent
    return Path.cwd()


def get_osiki_path() -> Path:
    """Get the osiki package directory."""
    return get_project_root() / "osiki"


def ensure_directory(path: Path) -> None:
    """Create directory if it doesn't exist."""
    path.mkdir(parents=True, exist_ok=True)


def file_exists(path: Path) -> bool:
    """Check if a file already exists."""
    return path.exists()


def parse_fields(fields_str: str | None) -> list[dict[str, str | bool]]:
    """Parse fields string into list of field definitions.

    Format: 'name:type,name:type:unique'
    Returns: [{'name': 'field_name', 'type': 'str', 'unique': False}, ...]
    """
    if not fields_str:
        return []

    fields = []
    for field in fields_str.split(","):
        parts = field.strip().split(":")
        if len(parts) >= 2:
            field_def: dict[str, str | bool] = {
                "name": parts[0].strip(),
                "type": parts[1].strip(),
                "unique": len(parts) > 2 and parts[2].strip().lower() == "unique",
            }
            fields.append(field_def)
    return fields
