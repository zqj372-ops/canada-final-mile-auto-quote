from __future__ import annotations

from datetime import date, datetime
import re

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
    deployment_sha: str | None = None,
    deployment_ref: str | None = None,
) -> QuoteReleaseManifest:
    validated = validate_quote_release_inputs(
        release_id=release_id,
        service_version=service_version,
        rule_version=rule_version,
        data_version=data_version,
        published_at=published_at,
        valid_from=valid_from,
        valid_to=valid_to,
        test_data=test_data,
        deployment_sha=deployment_sha,
        deployment_ref=deployment_ref,
    )
    reasons: list[str] = []
    values = {field: validated[field] for field in ("release_id", "service_version", "rule_version", "data_version")}
    normalized_published_at = validated["published_at"]
    source_status_service._deployment_release_reasons(values["release_id"], reasons)
    installed_service_version = source_status_service._installed_service_version()
    if installed_service_version is None:
        reasons.append("service_version_metadata_unavailable")
    elif values["service_version"] != installed_service_version:
        reasons.append("release_manifest_service_version_mismatch")
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
            valid_from=validated["valid_from"],
            valid_to=validated["valid_to"],
            test_data=validated["test_data"] or detected_test_data,
            active=True,
        )
        db.add(manifest)
        db.commit()
        db.refresh(manifest)
        return manifest
    except Exception:
        db.rollback()
        raise


def validate_quote_release_inputs(
    *,
    release_id: object,
    service_version: object,
    rule_version: object,
    data_version: object,
    published_at: object,
    valid_from: object,
    valid_to: object,
    test_data: object,
    deployment_sha: str | None = None,
    deployment_ref: str | None = None,
) -> dict[str, object]:
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
    if not isinstance(valid_from, date) or isinstance(valid_from, datetime):
        reasons.append("release_manifest_invalid:valid_from")
    if not isinstance(valid_to, date) or isinstance(valid_to, datetime):
        reasons.append("release_manifest_invalid:valid_to")
    if (
        isinstance(valid_from, date)
        and not isinstance(valid_from, datetime)
        and isinstance(valid_to, date)
        and not isinstance(valid_to, datetime)
    ):
        if valid_to < valid_from:
            reasons.append("release_manifest_invalid:effective_window")
    if deployment_sha is not None:
        normalized_sha = deployment_sha.strip()
        if re.fullmatch(r"[0-9a-f]{40}", normalized_sha) is None:
            reasons.append("deployment_config_invalid:DEPLOY_SHA")
        elif values["release_id"] != normalized_sha:
            reasons.append("deployment_config_mismatch:DEPLOY_SHA")
    if deployment_ref is not None and deployment_ref.strip() != "refs/heads/main":
        reasons.append("deployment_ref_not_allowed")
    if reasons:
        raise ValueError(",".join(reasons))
    return {
        **values,
        "published_at": normalized_published_at,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "test_data": test_data,
    }
