"""Consistency checks shown in the 'Controlli' page."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from .db import Database


@dataclass
class Issue:
    level: str  # severity label shown in the UI: "errore" (error) | "attenzione" (warning) | "info"
    message: str


def check(db: Database) -> list[Issue]:
    issues: list[Issue] = []
    riders = {r.id: r for r in db.riders()}
    bikes = db.bikes()
    active = [b for b in bikes if not b.withdrawn]

    numbers = defaultdict(list)
    for b in active:
        if b.race_number is not None:
            numbers[b.race_number].append(b)
    for number, same in sorted(numbers.items()):
        if len(same) > 1:
            who = "; ".join(f"{riders[b.rider_id].full_name} ({b.display_name})" for b in same)
            issues.append(Issue("errore", f"Numero {number} assegnato a più moto: {who}"))

    for b in active:
        r = riders[b.rider_id]
        label = f"{r.full_name} – {b.display_name}"
        if b.race_number is None:
            issues.append(Issue("errore", f"{label}: numero di gara mancante (esclusa dalle batterie)"))
        if db.bike_class(b) is None:
            issues.append(Issue("errore", f"{label}: cilindrata mancante, impossibile assegnare la classe"))
        if b.year is None:
            issues.append(Issue("attenzione", f"{label}: anno di produzione mancante"))

    per_rider = Counter(b.rider_id for b in bikes)

    by_name = defaultdict(list)
    for r in riders.values():
        by_name[frozenset(f"{r.first_name} {r.last_name}".lower().split())].append(r)
    for same in by_name.values():
        if len(same) > 1:
            issues.append(Issue("attenzione", f"Possibile iscritto duplicato: {', '.join(r.full_name for r in same)}"))

    for r in riders.values():
        if per_rider.get(r.id, 0) == 0:
            issues.append(Issue("info", f"{r.full_name}: nessuna moto iscritta"))
        if not r.paid:
            issues.append(Issue("info", f"{r.full_name}: iscrizione non pagata (escluso dalle batterie)"))
        if not r.insured:
            issues.append(Issue("info", f"{r.full_name}: assicurazione mancante (escluso dalle batterie)"))

    for class_name, turns in db.grids().items():
        for t, rows in enumerate(turns, start=1):
            where = f"Batteria {class_name}, turno {t}"
            if len(rows) > db.max_per_grid:
                issues.append(Issue("errore", f"{where}: {len(rows)} moto (massimo {db.max_per_grid})"))
            dup = [rid for rid, n in Counter(r.rider_id for r in rows).items() if n > 1]
            for rid in dup:
                issues.append(Issue("errore", f"{where}: {riders[rid].full_name} compare con più moto"))
    for class_name, missing in db.unplaced().items():
        issues.append(Issue("attenzione", f"Batteria {class_name}: {len(missing)} moto non ancora inserite"))

    order = {"errore": 0, "attenzione": 1, "info": 2}
    return sorted(issues, key=lambda i: order[i.level])
