"""Catalogue persistence helpers with organisation guards.

Heavy catalogue write paths still live in ``catalogue.datasets``. This module
wraps the common publish entry so callers can pass ``organisation_id``.
"""
from __future__ import annotations

import uuid
from typing import Any

from catalogue import datasets as _datasets


def push_to_catalogue(
    conn,
    *,
    organisation_id: uuid.UUID | str | None = None,
    **kwargs: Any,
):
    """Delegate to ``catalogue.datasets.push_to_catalogue`` with tenant tagging.

    When ``organisation_id`` is provided and the underlying function accepts it,
    it is forwarded; otherwise it is applied after insert via a best-effort
    UPDATE on the new dataset/group rows (additive tenancy).
    """
    import inspect

    sig = inspect.signature(_datasets.push_to_catalogue)
    if organisation_id is not None and "organisation_id" in sig.parameters:
        return _datasets.push_to_catalogue(
            conn, organisation_id=organisation_id, **kwargs
        )

    result = _datasets.push_to_catalogue(conn, **kwargs)
    if organisation_id is None:
        return result

    org = str(organisation_id)
    try:
        metadata_id = None
        if isinstance(result, dict):
            metadata_id = result.get("metadata_id") or result.get("group_id")
        if metadata_id:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE metadata_groups
                    SET organisation_id = %s::uuid
                    WHERE metadata_id = %s
                      AND organisation_id IS NULL
                    """,
                    (org, metadata_id),
                )
                cur.execute(
                    """
                    UPDATE datasets
                    SET organisation_id = %s::uuid
                    WHERE metadata_id = %s
                      AND organisation_id IS NULL
                    """,
                    (org, metadata_id),
                )
            conn.commit()
    except Exception as e:
        print(f"Warning: could not tag catalogue publish with organisation_id: {e}", flush=True)
    return result
