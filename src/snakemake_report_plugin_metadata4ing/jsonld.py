from __future__ import annotations

import uuid
from typing import Any, TypeAlias

JsonLdNode: TypeAlias = dict[str, Any]
JsonLdDocument: TypeAlias = JsonLdNode
JsonLdNodeMap: TypeAlias = dict[str, JsonLdNode]


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def reference_id(value: Any) -> str | None:
    if isinstance(value, dict):
        return value.get("@id")
    if isinstance(value, str):
        return value
    return None


def crate_safe_id(entity_id: str | None) -> str:
    if not entity_id:
        return f"#{uuid.uuid4()}"
    if entity_id.startswith("local:"):
        return f"#{entity_id.removeprefix('local:')}"
    return entity_id
