from __future__ import annotations

from contextlib import contextmanager
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from marygenai.persistence.sqlite import sqlite_database_path
from marygenai.review.models import ReviewItemStatusUpdate
from marygenai.review.repository import (
    PublicationNotFoundError,
    ReviewDatabaseNotInitializedError,
    ReviewItemNotFoundError,
    connect_initialized_review_database,
    get_publication_detail,
    get_publication_detail_for_review_item,
    list_open_review_items,
    list_review_queues,
    update_review_item_status,
)
from marygenai.settings import get_settings

app = typer.Typer(help="Inspect and advance MaryGenAI review queues.")
console = Console()


@app.callback()
def main() -> None:
    """Run review queue commands."""


@app.command("queues")
def queues() -> None:
    """List available review queues."""
    with _connect_or_exit() as connection:
        summaries = list_review_queues(connection)

    if not summaries:
        console.print("No review queues found.")
        return

    table = Table(title="Review queues")
    table.add_column("Queue")
    table.add_column("Total", justify="right")
    table.add_column("Open", justify="right")
    table.add_column("In review", justify="right")
    table.add_column("Resolved", justify="right")
    table.add_column("Dismissed", justify="right")
    for summary in summaries:
        table.add_row(
            summary.queue_type,
            str(summary.total_items),
            str(summary.open_items),
            str(summary.in_review_items),
            str(summary.resolved_items),
            str(summary.dismissed_items),
        )
    console.print(table)


@app.command("list")
def list_items(
    queue_type: Annotated[
        str,
        typer.Option("--queue", help="Review queue type to inspect."),
    ] = "legacy_identity_review",
    limit: Annotated[
        int,
        typer.Option("--limit", min=1, help="Maximum open items to show."),
    ] = 20,
) -> None:
    """List open review items ordered by priority."""
    with _connect_or_exit() as connection:
        items = list_open_review_items(connection, queue_type=queue_type, limit=limit)

    if not items:
        console.print(f"No open review items found for queue `{queue_type}`.")
        return

    table = Table(title=f"Open review items: {queue_type}")
    table.add_column("Review item")
    table.add_column("Score", justify="right")
    table.add_column("Tier")
    table.add_column("Document")
    table.add_column("Legacy ID")
    table.add_column("Title")
    for item in items:
        table.add_row(
            item.review_item_id,
            f"{item.priority_score:.1f}",
            item.priority_tier,
            item.publication.document_id,
            item.publication.legacy_study_id,
            item.publication.primary_title or "",
        )
    console.print(table)


@app.command("show")
def show(
    identifier: Annotated[
        str,
        typer.Argument(help="Review item id or publication document id."),
    ],
) -> None:
    """Show publication detail for a review item or document."""
    with _connect_or_exit() as connection:
        try:
            if identifier.startswith("review_item:"):
                detail = get_publication_detail_for_review_item(
                    connection,
                    review_item_id=identifier,
                )
            else:
                detail = get_publication_detail(connection, document_id=identifier)
        except (PublicationNotFoundError, ReviewItemNotFoundError) as error:
            console.print(str(error))
            raise typer.Exit(1) from error

    publication = detail.publication
    console.print(
        {
            "document_id": publication.document_id,
            "title": publication.primary_title,
            "publication_year": publication.publication_year,
            "legacy_study_id": publication.legacy_study_id,
            "canonical_url": publication.canonical_url,
            "pmid": publication.pmid,
            "pmcid": publication.pmcid,
            "doi": publication.doi,
        }
    )
    console.print({"legacy_reference": detail.legacy_reference.model_dump(mode="json")})

    identity_table = Table(title="Identities")
    identity_table.add_column("Type")
    identity_table.add_column("Value")
    identity_table.add_column("State")
    identity_table.add_column("Confidence", justify="right")
    for identity in detail.identities:
        identity_table.add_row(
            identity.identifier_type,
            identity.identifier_value,
            identity.association_state,
            f"{identity.confidence:.2f}",
        )
    console.print(identity_table)

    ontology_table = Table(title="Ontology links")
    ontology_table.add_column("Type")
    ontology_table.add_column("Label")
    ontology_table.add_column("English label")
    ontology_table.add_column("State")
    for link in detail.ontology_links:
        ontology_table.add_row(
            link.entity_type,
            link.canonical_label,
            link.canonical_label_en or "",
            link.review_state,
        )
    console.print(ontology_table)

    review_table = Table(title="Review items")
    review_table.add_column("Review item")
    review_table.add_column("Queue")
    review_table.add_column("Status")
    review_table.add_column("Score", justify="right")
    for item in detail.review_items:
        review_table.add_row(
            item.review_item_id,
            item.queue_type,
            item.status,
            f"{item.priority_score:.1f}",
        )
    console.print(review_table)


@app.command("update")
def update(
    review_item_id: Annotated[str, typer.Argument(help="Review item id to update.")],
    status: Annotated[str, typer.Option("--status", help="New review status.")],
    note: Annotated[str | None, typer.Option("--note", help="Optional status note.")] = None,
) -> None:
    """Update a review item status."""
    with _connect_or_exit() as connection:
        try:
            result = update_review_item_status(
                connection,
                update=ReviewItemStatusUpdate(
                    review_item_id=review_item_id,
                    status=status,
                    note=note,
                ),
            )
        except ReviewItemNotFoundError as error:
            console.print(str(error))
            raise typer.Exit(1) from error
        except ValidationError as error:
            console.print(
                "Invalid status. Use one of: open, in_review, resolved, dismissed."
            )
            raise typer.Exit(1) from error

    console.print(
        {
            "review_item_id": result.review_item_id,
            "previous_status": result.previous_status,
            "status": result.status,
            "note": result.note,
            "updated_at": result.updated_at,
        }
    )


@contextmanager
def _connect_or_exit():
    settings = get_settings()
    database_path = sqlite_database_path(settings.data_dir)
    try:
        with connect_initialized_review_database(database_path) as connection:
            yield connection
    except ReviewDatabaseNotInitializedError as error:
        console.print(str(error))
        raise typer.Exit(1) from error
