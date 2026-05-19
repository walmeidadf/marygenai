import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from marygenai.persistence.sqlite import sqlite_database_path
from marygenai.review.models import (
    IdentityDecisionApplicationResult,
    IdentityReviewDecision,
    IdentityReviewDecisionCreate,
    PublicationCandidateDiscoverySummary,
    PublicationCandidateProvenance,
    PublicationDetail,
    ReviewItemStatus,
    ReviewItemStatusResult,
    ReviewItemStatusUpdate,
    ReviewQueueItem,
    ReviewQueueSummary,
)
from marygenai.review.repository import (
    IdentityDecisionNotApplicableError,
    IdentityDecisionNotFoundError,
    PublicationNotFoundError,
    ReviewDatabaseNotInitializedError,
    ReviewItemNotFoundError,
    apply_latest_identity_review_decision,
    connect_initialized_review_database,
    create_identity_review_decision,
    get_publication_candidate_provenance,
    get_publication_detail,
    get_publication_detail_for_review_item,
    list_identity_review_decisions_for_item,
    list_identity_review_decisions_for_publication,
    list_open_review_items,
    list_publication_candidate_discoveries,
    list_review_queues,
    update_review_item_status,
)
from marygenai.review_ui.routes import mount_review_ui
from marygenai.settings import get_settings


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    database_path: str
    database_initialized: bool


class ReviewItemStatusPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ReviewItemStatus
    note: str | None = None


def create_app(database_path: Path | None = None) -> FastAPI:
    """Create the local review API application."""
    resolved_database_path = database_path or sqlite_database_path(get_settings().data_dir)
    app = FastAPI(
        title="MaryGenAI Review API",
        summary="Local API for MaryGenAI review queues and publication details.",
        version="0.1.0",
    )
    mount_review_ui(app)

    def get_connection() -> Iterator[sqlite3.Connection]:
        with _connect_or_http_error(resolved_database_path) as connection:
            yield connection

    Connection = Annotated[sqlite3.Connection, Depends(get_connection)]

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            database_path=str(resolved_database_path),
            database_initialized=_database_is_initialized(resolved_database_path),
        )

    @app.get("/review/queues", response_model=list[ReviewQueueSummary])
    def review_queues(connection: Connection) -> list[ReviewQueueSummary]:
        return list_review_queues(connection)

    @app.get("/review/queues/{queue_type}/items", response_model=list[ReviewQueueItem])
    def review_queue_items(
        queue_type: str,
        connection: Connection,
        status: Annotated[ReviewItemStatus, Query()] = "open",
        limit: Annotated[int, Query(ge=1, le=500)] = 20,
        identity_status: Annotated[str | None, Query()] = None,
        priority_tier: Annotated[str | None, Query()] = None,
        full_text_review_priority: Annotated[str | None, Query()] = None,
    ) -> list[ReviewQueueItem]:
        if status != "open":
            raise HTTPException(
                status_code=400,
                detail="Only status=open is supported for review queue item listing.",
            )
        return list_open_review_items(
            connection,
            queue_type=queue_type,
            limit=limit,
            identity_status=identity_status,
            priority_tier=priority_tier,
            full_text_review_priority=full_text_review_priority,
        )

    @app.get(
        "/publication-candidates",
        response_model=list[PublicationCandidateDiscoverySummary],
    )
    def publication_candidates(
        connection: Connection,
        identity_status: Annotated[str | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 20,
    ) -> list[PublicationCandidateDiscoverySummary]:
        return list_publication_candidate_discoveries(
            connection,
            identity_status=identity_status,
            limit=limit,
        )

    @app.get(
        "/publication-candidates/{document_id:path}/provenance",
        response_model=PublicationCandidateProvenance,
    )
    def publication_candidate_provenance(
        document_id: str,
        connection: Connection,
    ) -> PublicationCandidateProvenance:
        try:
            return get_publication_candidate_provenance(connection, document_id=document_id)
        except PublicationNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/review/items/{review_item_id}", response_model=PublicationDetail)
    def review_item_detail(review_item_id: str, connection: Connection) -> PublicationDetail:
        try:
            return get_publication_detail_for_review_item(
                connection,
                review_item_id=review_item_id,
            )
        except ReviewItemNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.patch(
        "/review/items/{review_item_id}/status",
        response_model=ReviewItemStatusResult,
    )
    def patch_review_item_status(
        review_item_id: str,
        patch: ReviewItemStatusPatch,
        connection: Connection,
    ) -> ReviewItemStatusResult:
        try:
            return update_review_item_status(
                connection,
                update=ReviewItemStatusUpdate(
                    review_item_id=review_item_id,
                    status=patch.status,
                    note=patch.note,
                ),
            )
        except ReviewItemNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.post(
        "/review/items/{review_item_id}/identity-decisions",
        response_model=IdentityReviewDecision,
    )
    def post_identity_review_decision(
        review_item_id: str,
        decision: IdentityReviewDecisionCreate,
        connection: Connection,
    ) -> IdentityReviewDecision:
        if decision.review_item_id != review_item_id:
            raise HTTPException(
                status_code=400,
                detail="Payload review_item_id must match the URL review item id.",
            )
        try:
            return create_identity_review_decision(connection, decision=decision)
        except ReviewItemNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except PublicationNotFoundError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post(
        "/review/items/{review_item_id}/identity-decisions/apply",
        response_model=IdentityDecisionApplicationResult,
    )
    def apply_identity_review_decision(
        review_item_id: str,
        connection: Connection,
    ) -> IdentityDecisionApplicationResult:
        try:
            return apply_latest_identity_review_decision(
                connection,
                review_item_id=review_item_id,
                source="marygenai.review_api",
            )
        except ReviewItemNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except IdentityDecisionNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except IdentityDecisionNotApplicableError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get(
        "/review/items/{review_item_id}/identity-decisions",
        response_model=list[IdentityReviewDecision],
    )
    def review_item_identity_decisions(
        review_item_id: str,
        connection: Connection,
    ) -> list[IdentityReviewDecision]:
        try:
            return list_identity_review_decisions_for_item(
                connection,
                review_item_id=review_item_id,
            )
        except ReviewItemNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get(
        "/publications/{document_id:path}/identity-decisions",
        response_model=list[IdentityReviewDecision],
    )
    def publication_identity_decisions(
        document_id: str,
        connection: Connection,
    ) -> list[IdentityReviewDecision]:
        try:
            return list_identity_review_decisions_for_publication(
                connection,
                document_id=document_id,
            )
        except PublicationNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/publications/{document_id:path}", response_model=PublicationDetail)
    def publication_detail(document_id: str, connection: Connection) -> PublicationDetail:
        try:
            return get_publication_detail(connection, document_id=document_id)
        except PublicationNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    return app


@contextmanager
def _connect_or_http_error(database_path: Path) -> Iterator[sqlite3.Connection]:
    try:
        with connect_initialized_review_database(
            database_path,
            check_same_thread=False,
        ) as connection:
            yield connection
    except ReviewDatabaseNotInitializedError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


def _database_is_initialized(database_path: Path) -> bool:
    try:
        with connect_initialized_review_database(database_path, check_same_thread=False):
            return True
    except ReviewDatabaseNotInitializedError:
        return False
