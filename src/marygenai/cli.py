import typer
from rich.console import Console

from marygenai import __version__
from marygenai.access_enrichment.cli import app as access_enrichment_app
from marygenai.analytics.cli import app as analytics_app
from marygenai.classification.cli import app as classification_app
from marygenai.classification_corpus.cli import app as classification_corpus_app
from marygenai.deployment.cli import app as deployment_app
from marygenai.initial_load.cli import app as initial_load_app
from marygenai.mcp_server.cli import app as mcp_app
from marygenai.persistence.cli import app as db_app
from marygenai.pubmed_discovery.cli import app as pubmed_discovery_app
from marygenai.retrieval.cli import app as retrieval_app
from marygenai.review.cli import app as review_app
from marygenai.review_api.cli import app as review_api_app
from marygenai.review_ui.cli import app as review_ui_app
from marygenai.settings import get_settings

app = typer.Typer(
    help="MaryGenAI scientific source-intelligence and candidate-classification workflows.",
    no_args_is_help=True,
)
console = Console()
app.add_typer(initial_load_app, name="initial-load")
app.add_typer(db_app, name="db")
app.add_typer(pubmed_discovery_app, name="pubmed-discovery")
app.add_typer(access_enrichment_app, name="access-enrichment")
app.add_typer(classification_corpus_app, name="classification-corpus")
app.add_typer(classification_app, name="classification")
app.add_typer(analytics_app, name="analytics")
app.add_typer(review_app, name="review")
app.add_typer(review_api_app, name="review-api")
app.add_typer(review_ui_app, name="review-ui")
app.add_typer(retrieval_app, name="retrieval")
app.add_typer(mcp_app, name="mcp")
app.add_typer(deployment_app, name="deployment")


@app.callback()
def main() -> None:
    """Run MaryGenAI supported workflows."""


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
