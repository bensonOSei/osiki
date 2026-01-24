from typing import Annotated

import typer

from cli.generators.model import generate_model
from cli.generators.repository import generate_repository
from cli.generators.route import generate_route
from cli.generators.service import generate_service

app = typer.Typer(no_args_is_help=True)


@app.command("model")  # type: ignore[misc]
def model(
    name: Annotated[
        str, typer.Argument(help="Model name in PascalCase (e.g., Product)")
    ],
    fields: Annotated[
        str | None,
        typer.Option(
            "--fields",
            "-f",
            help="Fields: 'name:type,name:type:unique'",
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite existing files"),
    ] = False,
) -> None:
    """Generate a new Beanie model."""
    generate_model(name, fields, force)


@app.command("repository")  # type: ignore[misc]
def repository(
    name: Annotated[
        str, typer.Argument(help="Entity name in PascalCase (e.g., Product)")
    ],
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite existing files"),
    ] = False,
) -> None:
    """Generate a repository with base and MongoDB implementation."""
    generate_repository(name, force)


@app.command("service")  # type: ignore[misc]
def service(
    name: Annotated[
        str, typer.Argument(help="Service name in PascalCase (e.g., ProductCatalog)")
    ],
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite existing files"),
    ] = False,
) -> None:
    """Generate a service with base and implementation."""
    generate_service(name, force)


@app.command("route")  # type: ignore[misc]
def route(
    name: Annotated[str, typer.Argument(help="Route name (e.g., products)")],
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite existing files"),
    ] = False,
) -> None:
    """Generate an API route module."""
    generate_route(name, force)


@app.command("all")  # type: ignore[misc]
def all_scaffolds(
    name: Annotated[
        str, typer.Argument(help="Entity name in PascalCase (e.g., Product)")
    ],
    fields: Annotated[
        str | None,
        typer.Option(
            "--fields", "-f", help="Fields in format 'name:type,name:type:unique'"
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite existing files"),
    ] = False,
) -> None:
    """Generate model, repository, service, and route for an entity."""
    typer.echo(f"\nGenerating full stack for {name}...\n")
    generate_model(name, fields, force)
    generate_repository(name, force)
    generate_service(name, force)
    generate_route(name, force)
    typer.echo(
        typer.style(
            "\nAll scaffolds generated successfully!", fg=typer.colors.GREEN, bold=True
        )
    )
