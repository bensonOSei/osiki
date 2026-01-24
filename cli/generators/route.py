from pathlib import Path

import typer
from jinja2 import Environment, FileSystemLoader

from cli.utils import file_exists, get_osiki_path, to_plural, to_snake_case


def get_template_env() -> Environment:
    """Get Jinja2 environment with templates directory."""
    templates_dir = Path(__file__).parent.parent / "templates"
    return Environment(loader=FileSystemLoader(templates_dir))


def generate_route(name: str, force: bool) -> None:
    """Generate an API route file.

    Args:
        name: Entity name in PascalCase (e.g., Product, UserGroup)
    """
    # Convert to snake_case for file/variable names
    snake_name = to_snake_case(name)
    plural_snake = to_plural(snake_name)

    # Ensure PascalCase for class name
    class_name = "".join(word.capitalize() for word in snake_name.split("_"))

    # Prepare template context
    context = {
        "class_name": class_name,
        "snake_name": snake_name,
        "plural_snake": plural_snake,
        "var_name": snake_name,
        "route_prefix": plural_snake,
        "tag": plural_snake.replace("_", " ").title().replace(" ", ""),
    }

    # Create route file
    routes_path = get_osiki_path() / "api" / "routes"
    file_path = routes_path / f"{plural_snake}.py"

    if file_exists(file_path) and not force:
        typer.echo(
            typer.style(f"  Route already exists: {file_path}", fg=typer.colors.YELLOW)
        )
        typer.echo("  Use --force to overwrite")
        raise typer.Exit(1)

    env = get_template_env()
    template = env.get_template("route.py.j2")
    content = template.render(**context)

    file_path.write_text(content)
    typer.echo(typer.style(f"  Created route: {file_path}", fg=typer.colors.GREEN))
