import os
import re

import httpx

from controllers.admin_controller import _supabase_headers, log_admin_action

LEGAL_DOCUMENTS_TABLE = "legal_documents"
DOCUMENT_TYPES = {"privacy_policy", "terms_of_service"}
VERSION_PATTERN = re.compile(r"^\d+\.\d+$")

LEGAL_DOCUMENT_SELECT = "document_type,version,content_he,content_en,changes_summary_he,changes_summary_en,created_at"


class StaleVersionError(Exception):
    """Raised when the document changed since the admin loaded it (optimistic concurrency)."""


class DuplicateVersionError(Exception):
    """Raised when the requested version string already exists for this document type."""


def _bump_version(version: str) -> str | None:
    match = VERSION_PATTERN.match(version)
    if not match:
        return None
    major, minor = version.split(".")
    return f"{major}.{int(minor) + 1}"


def _row_to_sections(content_he: list[dict], content_en: list[dict]) -> list[dict]:
    return [
        {
            "titleHe": he.get("title") or "",
            "titleEn": en.get("title") or "",
            "bodyHe": he.get("body") or [],
            "bodyEn": en.get("body") or [],
            "itemsHe": he.get("items") or [],
            "itemsEn": en.get("items") or [],
        }
        for he, en in zip(content_he, content_en)
    ]


def _row_to_document(row: dict) -> dict:
    return {
        "documentType": row["document_type"],
        "version": row["version"],
        "sections": _row_to_sections(row.get("content_he") or [], row.get("content_en") or []),
        "changesSummaryHe": row.get("changes_summary_he") or [],
        "changesSummaryEn": row.get("changes_summary_en") or [],
        "createdAt": row["created_at"],
    }


async def _fetch_latest_row(
    client: httpx.AsyncClient, supabase_url: str, headers: dict, document_type: str
) -> dict | None:
    response = await client.get(
        f"{supabase_url}/rest/v1/{LEGAL_DOCUMENTS_TABLE}",
        params={
            "select": LEGAL_DOCUMENT_SELECT,
            "document_type": f"eq.{document_type}",
            "order": "created_at.desc",
            "limit": "1",
        },
        headers=headers,
    )
    response.raise_for_status()
    rows = response.json()
    return rows[0] if rows else None


async def get_legal_document(document_type: str) -> dict:
    supabase_url = os.getenv("SUPABASE_URL")
    headers = _supabase_headers()

    async with httpx.AsyncClient(timeout=10.0) as client:
        row = await _fetch_latest_row(client, supabase_url, headers, document_type)

    if row is None:
        raise LookupError(f"No {document_type} document found")

    document = _row_to_document(row)
    document["suggestedNextVersion"] = _bump_version(row["version"])
    return document


async def list_legal_document_history(document_type: str) -> list[dict]:
    supabase_url = os.getenv("SUPABASE_URL")
    headers = _supabase_headers()

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            f"{supabase_url}/rest/v1/{LEGAL_DOCUMENTS_TABLE}",
            params={
                "select": LEGAL_DOCUMENT_SELECT,
                "document_type": f"eq.{document_type}",
                "order": "created_at.desc",
            },
            headers=headers,
        )
        response.raise_for_status()
        rows = response.json()

    return [_row_to_document(row) for row in rows]


def _validate_sections(sections: list[dict]) -> None:
    if not sections:
        raise ValueError("At least one section is required")
    for index, section in enumerate(sections):
        if not (section.get("titleHe") or "").strip() or not (section.get("titleEn") or "").strip():
            raise ValueError(f"Section {index + 1} is missing a title")
        body_he = section.get("bodyHe") or []
        body_en = section.get("bodyEn") or []
        if not body_he or not body_en:
            raise ValueError(f"Section {index + 1} is missing body text")
        if len(body_he) != len(body_en):
            raise ValueError(f"Section {index + 1}: bodyHe/bodyEn must have the same number of paragraphs")
        items_he = section.get("itemsHe") or []
        items_en = section.get("itemsEn") or []
        if bool(items_he) != bool(items_en) or len(items_he) != len(items_en):
            raise ValueError(f"Section {index + 1}: itemsHe/itemsEn must both be set with the same length")


async def create_legal_document_version(
    document_type: str,
    version: str,
    sections: list[dict],
    changes_summary_he: list[str],
    changes_summary_en: list[str],
    expected_created_at: str | None,
    admin_id: str,
) -> dict:
    if document_type not in DOCUMENT_TYPES:
        raise ValueError("Invalid document type")
    if not VERSION_PATTERN.match(version):
        raise ValueError("version must be formatted as MAJOR.MINOR, e.g. 1.3")
    _validate_sections(sections)

    supabase_url = os.getenv("SUPABASE_URL")
    headers = _supabase_headers()

    async with httpx.AsyncClient(timeout=10.0) as client:
        current_row = await _fetch_latest_row(client, supabase_url, headers, document_type)
        current_created_at = current_row["created_at"] if current_row else None
        if current_created_at != expected_created_at:
            raise StaleVersionError(
                "This document was published again since you started editing. Reload to see the latest version."
            )

        content_he = [
            {"title": s["titleHe"], "body": s["bodyHe"], **({"items": s["itemsHe"]} if s.get("itemsHe") else {})}
            for s in sections
        ]
        content_en = [
            {"title": s["titleEn"], "body": s["bodyEn"], **({"items": s["itemsEn"]} if s.get("itemsEn") else {})}
            for s in sections
        ]

        response = await client.post(
            f"{supabase_url}/rest/v1/{LEGAL_DOCUMENTS_TABLE}",
            headers={**headers, "Content-Type": "application/json", "Prefer": "return=representation"},
            json={
                "document_type": document_type,
                "version": version,
                "content_he": content_he,
                "content_en": content_en,
                "changes_summary_he": changes_summary_he,
                "changes_summary_en": changes_summary_en,
            },
        )
        if response.status_code == 409:
            raise DuplicateVersionError(f"Version {version} already exists for {document_type}")
        response.raise_for_status()
        created_row = response.json()[0]

    await log_admin_action(admin_id, "publish_legal_document", document_type, {"version": version})

    document = _row_to_document(created_row)
    document["suggestedNextVersion"] = _bump_version(version)
    return document
