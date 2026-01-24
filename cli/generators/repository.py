from pathlib import Path

import typer
from jinja2 import Environment, FileSystemLoader

from cli.utils import (
    ensure_directory,
    file_exists,
    get_osiki_path,
    to_plural,
    to_snake_case,
)


def get_template_env() -> Environment:
    """Get Jinja2 environment with templates directory."""
    templates_dir = Path(__file__).parent.parent / "templates"
    return Environment(loader=FileSystemLoader(templates_dir))


def generate_repository(name: str, force: bool) -> None:
    """Generate repository files (base + MongoDB implementation)."""
    snake_name = to_snake_case(name)
    plural_snake = to_plural(snake_name)
    var_name = snake_name

    # Prepare template context
    context = {
        "class_name": name,
        "snake_name": snake_name,
        "plural_snake": plural_snake,
        "var_name": var_name,
        "model_file": snake_name,
    }

    # Create repository directory
    repos_path = get_osiki_path() / "repositories" / plural_snake
    ensure_directory(repos_path)

    env = get_template_env()
    files_to_create = [
        ("__init__.py", "repository_init.py.j2"),
        (f"base_{snake_name}_repository.py", "base_repository.py.j2"),
        (f"mongodb_{snake_name}_repository.py", "mongodb_repository.py.j2"),
    ]

    for filename, template_name in files_to_create:
        file_path = repos_path / filename

        if file_exists(file_path) and not force:
            typer.echo(
                typer.style(
                    f"  Repository file already exists: {file_path}",
                    fg=typer.colors.YELLOW,
                )
            )
            typer.echo("  Use --force to overwrite")
            raise typer.Exit(1)

        template = env.get_template(template_name)
        content = template.render(**context)
        file_path.write_text(content)
        typer.echo(
            typer.style(f"  Created repository: {file_path}", fg=typer.colors.GREEN)
        )
