from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from apps.api.db.models import QuoteReleaseManifest, QuoteSourceGeneration
from apps.api.services import source_status_service


def publish_quote_release(
    db: Session,
    *,
    release_id: str,
    service_version: str,
    rule_version: str,
    data_version: str,
    published_at: datetime | str,
    valid_from: date,
    valid_to: date,
    test_data: bool | None = None,
) -> QuoteReleaseManifest:
    reasons: list[str] = []
    if not isinstance(test_data, bool):
        reasons.append("test_data_declaration_required")
    values = {
        field: source_status_service._manifest_text(value, field, reasons)
        for field, value in {
            "release_id": release_id,
            "service_version": service_version,
            "rule_version": rule_version,
            "data_version": data_version,
        }.items()
    }
    normalized_published_at = source_status_service._manifest_published_at(published_at, reasons)
    source_status_service._deployment_release_reasons(values["release_id"], reasons)
    installed_service_version = source_status_service._installed_service_version()
    if installed_service_version is None:
        reasons.append("service_version_metadata_unavailable")
    elif values["service_version"] != installed_service_version:
        reasons.append("release_manifest_service_version_mismatch")
    if valid_to < valid_from:
        reasons.append("release_manifest_invalid:effective_window")
    if reasons:
        raise ValueError(",".join(reasons))

    generation = db.scalar(
        select(QuoteSourceGeneration)
        .where(QuoteSourceGeneration.id == 1)
        .with_for_update()
    )
    if generation is None:
        raise ValueError("source_generation_unavailable")
    db.scalars(
        select(QuoteReleaseManifest)
        .where(QuoteReleaseManifest.active.is_(True))
        .with_for_update()
    ).all()

    try:
        snapshot_hash = source_status_service.source_data_hash(db)
        detected_test_data = source_status_service._source_data_is_test_data(db)
        db.execute(
            update(QuoteReleaseManifest)
            .where(QuoteReleaseManifest.active.is_(True))
            .values(active=False)
        )
        manifest = QuoteReleaseManifest(
            release_id=values["release_id"],
            snapshot_hash=snapshot_hash,
            source_generation=generation.generation,
            service_version=values["service_version"],
            rule_version=values["rule_version"],
            data_version=values["data_version"],
            published_at=datetime.fromisoformat(normalized_published_at),
            valid_from=valid_from,
            valid_to=valid_to,
            test_data=test_data or detected_test_data,
            active=True,
        )
        db.add(manifest)
        db.commit()
        db.refresh(manifest)
        return manifest
    except Exception:
        db.rollback()
        raise
