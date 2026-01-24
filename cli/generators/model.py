from pathlib import Path

import typer
from jinja2 import Environment, FileSystemLoader

from cli.utils import (
    file_exists,
    get_osiki_path,
    parse_fields,
    to_plural,
    to_snake_case,
)


def get_template_env() -> Environment:
    """Get Jinja2 environment with templates directory."""
    templates_dir = Path(__file__).parent.parent / "templates"
    return Environment(loader=FileSystemLoader(templates_dir))


def generate_model(name: str, fields_str: str | None, force: bool) -> None:
    """Generate a Beanie model file."""
    snake_name = to_snake_case(name)
    collection_name = to_plural(snake_name)
    fields = parse_fields(fields_str)

    # Check for indexed/unique fields
    has_indexed_fields = any(f.get("unique") or f.get("indexed") for f in fields)
    has_object_id_fields = any(
        "PydanticObjectId" in str(f.get("type", "")) for f in fields
    )
    has_indexes = True  # Always include the is_active index

    # Prepare template context
    context = {
        "class_name": name,
        "collection_name": collection_name,
        "fields": fields,
        "has_indexed_fields": has_indexed_fields,
        "has_object_id_fields": has_object_id_fields,
        "has_indexes": has_indexes,
    }

    # Generate file
    models_path = get_osiki_path() / "models"
    file_path = models_path / f"{snake_name}.py"

    if file_exists(file_path) and not force:
        typer.echo(
            typer.style(f"  Model already exists: {file_path}", fg=typer.colors.YELLOW)
        )
        typer.echo("  Use --force to overwrite")
        raise typer.Exit(1)

    env = get_template_env()
    template = env.get_template("model.py.j2")
    content = template.render(**context)

    file_path.write_text(content)
    typer.echo(typer.style(f"  Created model: {file_path}", fg=typer.colors.GREEN))
