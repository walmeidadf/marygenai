import typer
from rich.console import Console

from marygenai import __version__
from marygenai.initial_load.cli import app as initial_load_app
from marygenai.persistence.cli import app as db_app
from marygenai.review.cli import app as review_app
from marygenai.review_api.cli import app as review_api_app
from marygenai.settings import get_settings

app = typer.Typer(help="MaryGenAI POC utilities.", no_args_is_help=True)
console = Console()
app.add_typer(initial_load_app, name="initial-load")
app.add_typer(db_app, name="db")
app.add_typer(review_app, name="review")
app.add_typer(review_api_app, name="review-api")


@app.callback()
def main() -> None:
    """Run MaryGenAI POC utilities."""


@app.command()
def info() -> None:
    """Show local project configuration."""
    settings = get_settings()
    console.print(
        {
            "version": __version__,
            "data_dir": str(settings.data_dir),
            "temp_dir": str(settings.temp_dir),
        }
    )


@app.command()
def version() -> None:
    """Show the package version."""
    console.print(__version__)


if __name__ == "__main__":
    app()
