from pathlib import Path

import typer
from jinja2 import Environment, FileSystemLoader

from cli.utils import ensure_directory, file_exists, get_osiki_path, to_snake_case


def get_template_env() -> Environment:
    """Get Jinja2 environment with templates directory."""
    templates_dir = Path(__file__).parent.parent / "templates"
    return Environment(loader=FileSystemLoader(templates_dir))


def generate_service(name: str, force: bool) -> None:
    """Generate service files (base + implementation)."""
    snake_name = to_snake_case(name)

    # Prepare template context
    context = {
        "class_name": name,
        "snake_name": snake_name,
    }

    # Create service directory
    services_path = get_osiki_path() / "services" / snake_name
    ensure_directory(services_path)

    env = get_template_env()
    files_to_create = [
        ("__init__.py", "service_init.py.j2"),
        (f"base_{snake_name}_service.py", "base_service.py.j2"),
        (f"{snake_name}_service.py", "service.py.j2"),
    ]

    for filename, template_name in files_to_create:
        file_path = services_path / filename

        if file_exists(file_path) and not force:
            typer.echo(
                typer.style(
                    f"  Service file already exists: {file_path}",
                    fg=typer.colors.YELLOW,
                )
            )
            typer.echo("  Use --force to overwrite")
            raise typer.Exit(1)

        template = env.get_template(template_name)
        content = template.render(**context)
        file_path.write_text(content)
        typer.echo(
            typer.style(f"  Created service: {file_path}", fg=typer.colors.GREEN)
        )
