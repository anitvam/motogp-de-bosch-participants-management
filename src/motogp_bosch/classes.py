"""Assignment of bikes to race classes."""
from __future__ import annotations

KINDS = {
    "moto": "Moto",
    "sidecar": "Sidecar",
    "vespa": "Vespa / Lambretta",
    "rullo": "A rullo",
}

# Classes decided by the bike type rather than by its displacement.
KIND_CLASS = {"sidecar": "SIDECAR", "vespa": "VESPA-LAMBR", "rullo": "RULLO"}

# (max cc included, class); None = no upper limit.
DEFAULT_BANDS: list[tuple[int | None, str]] = [
    (100, "50"),
    (175, "125"),
    (250, "250"),
    (399, "350"),
    (500, "500"),
    (None, "OPEN"),
]

# Order of the sheets in the printed workbook (same as the 2025 file).
CLASS_ORDER = ["RULLO", "50", "125", "250", "350", "500", "OPEN", "SIDECAR", "VESPA-LAMBR"]

# Draft-only group for bikes whose class cannot be decided yet (no cc).
UNCLASSIFIED = "DA CLASSIFICARE"

CLASS_TITLES = {
    "RULLO": "A RULLO",
    "50": "50 cc",
    "125": "125 cc",
    "250": "250 cc",
    "350": "350 cc",
    "500": "500 cc",
    "OPEN": "OPEN",
    "SIDECAR": "SIDECAR",
    "VESPA-LAMBR": "VESPA E LAMBRETTA",
    UNCLASSIFIED: "DA CLASSIFICARE (manca la cilindrata)",
}


def class_for(
    cc: int | None,
    kind: str = "moto",
    override: str | None = None,
    bands: list[tuple[int | None, str]] = DEFAULT_BANDS,
) -> str | None:
    """Return the class a bike races in, or None if it cannot be decided (missing cc)."""
    if override:
        return override
    if kind in KIND_CLASS:
        return KIND_CLASS[kind]
    if cc is None:
        return None
    for max_cc, name in bands:
        if max_cc is None or cc <= max_cc:
            return name
    return bands[-1][1]
