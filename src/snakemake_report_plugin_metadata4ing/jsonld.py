"""Shared helpers and aliases for JSON-LD-like data structures.

The rest of the package manipulates JSON-LD payloads heavily. This module keeps
the most common structural aliases and tiny helper functions in one place so
that provenance extraction and crate-building code stay consistent.
"""

from __future__ import annotations

import uuid
from typing import Any, TypeAlias

JsonLdNode: TypeAlias = dict[str, Any]
JsonLdDocument: TypeAlias = JsonLdNode
JsonLdNodeMap: TypeAlias = dict[str, JsonLdNode]


def as_list(value: Any) -> list[Any]:
    """Return ``value`` as a list while preserving existing lists.

    Args:
        value: A scalar value, list, or ``None``.

    Returns:
        ``[]`` when ``value`` is ``None``, the original list when ``value`` is a
        list, otherwise a single-item list containing ``value``.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def reference_id(value: Any) -> str | None:
    """Extract an ``@id`` from a JSON-LD reference or plain string.

    Args:
        value: Either a JSON-LD reference dictionary, a plain string ID, or any
            other object.

    Returns:
        The referenced identifier when one can be extracted, otherwise ``None``.
    """
    if isinstance(value, dict):
        return value.get("@id")
    if isinstance(value, str):
        return value
    return None


def crate_safe_id(entity_id: str | None) -> str:
    """Convert local identifiers into RO-Crate-safe hash identifiers.

    Args:
        entity_id: Original identifier from provenance data.

    Returns:
        A crate-safe identifier. ``local:`` identifiers are rewritten as
        fragment identifiers and missing identifiers are replaced with a random
        UUID fragment.
    """
    if not entity_id:
        return f"#{uuid.uuid4()}"
    if entity_id.startswith("local:"):
        return f"#{entity_id.removeprefix('local:')}"
    return entity_id
