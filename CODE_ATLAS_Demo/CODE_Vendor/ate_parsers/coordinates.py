"""MAP coordinate validity shared by every parser and consumer.

Rule: when a file carries MAP coordinates, only DUTs with a valid coordinate
are analysed. DUTs recorded with a missing-coordinate sentinel (STDF -32768,
DataLog -99999) or without coordinates are excluded from Yield, MAP, Histogram
and statistics. Files without any coordinates (FT) are left unchanged.
"""
from __future__ import annotations

MISSING_COORDINATES = frozenset({-32768, -99999})


def is_map_coordinate(x, y) -> bool:
    return (
        x is not None and y is not None
        and x not in MISSING_COORDINATES and y not in MISSING_COORDINATES
    )


def apply_map_coordinate_rule(dataset) -> int:
    """Drop DUTs without a valid coordinate from a coordinate-bearing dataset.

    Returns the number of removed DUTs. Remaining rows are re-indexed so
    ``PartRow.index`` stays a contiguous 0-based sequence.
    """
    parts = dataset.parts
    if not any(is_map_coordinate(part.x, part.y) for part in parts):
        return 0
    kept = [part for part in parts if is_map_coordinate(part.x, part.y)]
    removed = len(parts) - len(kept)
    if removed:
        for index, part in enumerate(kept):
            part.index = index
        dataset.parts = kept
        dataset.metadata["excluded_without_coordinate"] = str(removed)
        dataset.warnings.append(
            f"Excluded {removed} DUT(s) without a valid MAP coordinate (e.g. -99999)"
        )
    return removed
