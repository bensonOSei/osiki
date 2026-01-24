import typer

from cli.commands import generate

app = typer.Typer(
    name="osiki",
    help="Osiki CLI - Code generation tools for the Osiki authorization service",
    no_args_is_help=True,
    rich_markup_mode=None,  # Disable rich to avoid click compatibility issues
)

app.add_typer(generate.app, name="generate", help="Generate code scaffolds")


if __name__ == "__main__":
    app()
