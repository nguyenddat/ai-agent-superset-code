from collections.abc import Container, Mapping
from typing import Any

EdgeKey = tuple[int, int, str]


def flipped_key(key: EdgeKey) -> EdgeKey:
    """The key the same foreign key gets once its datasets' layers reorder.

    A reference is a ``relation`` from the referencing dataset to the referenced one, or a ``flow`` the other way
    round, so a flip swaps both the direction and the kind.
    """
    source_id, target_id, kind = key
    return target_id, source_id, "relation" if kind == "flow" else "flow"


def match_override(key: EdgeKey, inferred: Container[EdgeKey], rows: Mapping[EdgeKey, Any]) -> Any | None:
    """Find the override row for an inferred edge.

    Hidden and colour-only rows are stored under the kind the edge had when they were made. When a layer change flips
    the edge, the row is still found under the flipped key, unless that key is an inferred edge of its own. Manual
    edges are never remapped, because they do not follow the dictionary.
    """
    row = rows.get(key)
    if row is not None or key not in inferred:
        return row
    flipped = flipped_key(key)
    candidate = rows.get(flipped)
    if candidate is not None and flipped not in inferred and (candidate.is_hidden or not candidate.is_manual):
        return candidate
    return None
