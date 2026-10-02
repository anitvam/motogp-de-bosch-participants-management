"""Free-text bike descriptions ('Honda CB 500 1974') split into brand, model, cc and year."""
from __future__ import annotations

import re

MULTI_WORD_BRANDS = ["moto morini", "moto guzzi", "mv agusta", "moto bi", "harley davidson"]
YEAR_RE = re.compile(r"^(19|20)\d\d$")
CC_RE = re.compile(r"^\d{2,4}$")


def parse_bike(text: str) -> dict:
    """'honda cb 500 1974' -> brand HONDA, model CB 500, cc 500, year 1974."""
    clean = " ".join(str(text).split())
    tokens = clean.split(" ")
    lower = clean.lower()
    brand_len = 1
    for brand in MULTI_WORD_BRANDS:
        if lower.startswith(brand + " ") or lower == brand:
            brand_len = len(brand.split())
            break
    brand = " ".join(tokens[:brand_len])
    rest = tokens[brand_len:]

    year = None
    if rest and YEAR_RE.match(rest[-1]):
        year = int(rest.pop())
    cc = None
    for tok in reversed(rest):
        if CC_RE.match(tok) and 40 <= int(tok) <= 2500:
            cc = int(tok)
            break
    kind = "moto"
    if brand.lower() in ("vespa", "lambretta"):
        kind = "vespa"
    elif "sidecar" in lower:
        kind = "sidecar"
    return {"brand": brand.upper(), "model": " ".join(rest).upper(), "cc": cc, "year": year, "kind": kind}
