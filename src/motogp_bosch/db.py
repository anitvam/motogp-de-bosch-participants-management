"""SQLite storage and the operations the app performs on it."""
from __future__ import annotations

import json
import random
import sqlite3
from collections import defaultdict
from dataclasses import asdict, fields
from pathlib import Path

from .classes import CLASS_ORDER, DEFAULT_BANDS, UNCLASSIFIED, class_for
from .grids import Entrant, draw_class
from .models import Bike, GridRow, Rider

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS riders (
    id INTEGER PRIMARY KEY,
    first_name TEXT NOT NULL DEFAULT '',
    last_name TEXT NOT NULL DEFAULT '',
    town TEXT NOT NULL DEFAULT '',
    province TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    birth_date TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    paid INTEGER NOT NULL DEFAULT 0,
    insured INTEGER NOT NULL DEFAULT 0,
    insurance_id TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS bikes (
    id INTEGER PRIMARY KEY,
    rider_id INTEGER NOT NULL REFERENCES riders(id) ON DELETE CASCADE,
    brand TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    cc INTEGER,
    year INTEGER,
    kind TEXT NOT NULL DEFAULT 'moto',
    race_number INTEGER,
    class_override TEXT,
    withdrawn INTEGER NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS grids (
    id INTEGER PRIMARY KEY,
    class_name TEXT NOT NULL,
    turn INTEGER NOT NULL,
    locked INTEGER NOT NULL DEFAULT 0,
    seed INTEGER,
    UNIQUE (class_name, turn)
);
CREATE TABLE IF NOT EXISTS grid_entries (
    grid_id INTEGER NOT NULL REFERENCES grids(id) ON DELETE CASCADE,
    bike_id INTEGER NOT NULL UNIQUE REFERENCES bikes(id) ON DELETE CASCADE,
    position INTEGER NOT NULL
);
"""

# Columns added after the first release: added on open to databases created earlier.
MIGRATIONS = {
    "riders": {
        "address": "TEXT NOT NULL DEFAULT ''",
        "birth_date": "TEXT NOT NULL DEFAULT ''",
        "insurance_id": "TEXT NOT NULL DEFAULT ''",
    },
}

DEFAULT_SETTINGS = {
    "event_date": "",
    "max_per_grid": "8",
    "bands": json.dumps(DEFAULT_BANDS),
}


class DuplicateNumber(ValueError):
    pass


class Database:
    def __init__(self, path: str | Path = ":memory:"):
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        for table, columns in MIGRATIONS.items():
            existing = {r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})")}
            for name, definition in columns.items():
                if name not in existing:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
        for key, value in DEFAULT_SETTINGS.items():
            self.conn.execute("INSERT OR IGNORE INTO settings VALUES (?, ?)", (key, value))
        self.renumbered = self._repair_numbers()
        self.conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS bikes_race_number ON bikes(race_number)")
        self.conn.commit()

    def _repair_numbers(self) -> list[tuple[int, int]]:
        """Databases from before numbers were unique may contain duplicates: the first bike keeps
        the number, the others are left without one (and noted) so the organisers can choose.
        Returns (bike_id, removed number) for every change."""
        seen: set[int] = set()
        result = []
        for row in self.conn.execute(
            "SELECT id, race_number FROM bikes WHERE race_number IS NOT NULL ORDER BY id"
        ).fetchall():
            if row["race_number"] in seen:
                self.conn.execute(
                    "UPDATE bikes SET race_number = NULL, notes = TRIM(notes || ' [numero ' || ? || ' duplicato]') "
                    "WHERE id = ?", (row["race_number"], row["id"]),
                )
                result.append((row["id"], row["race_number"]))
            seen.add(row["race_number"])
        return result

    # ---------------------------------------------------------------- settings
    def setting(self, key: str) -> str:
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else DEFAULT_SETTINGS.get(key, "")

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, value))
        self.conn.commit()
        self.prune_grids()

    @property
    def max_per_grid(self) -> int:
        return int(self.setting("max_per_grid"))

    @property
    def bands(self) -> list[tuple[int | None, str]]:
        return [tuple(b) for b in json.loads(self.setting("bands"))]

    # ------------------------------------------------------------------ riders
    def riders(self) -> list[Rider]:
        rows = self.conn.execute("SELECT * FROM riders ORDER BY last_name, first_name").fetchall()
        return [_rider(r) for r in rows]

    def rider(self, rider_id: int) -> Rider:
        return _rider(self.conn.execute("SELECT * FROM riders WHERE id = ?", (rider_id,)).fetchone())

    def add_rider(self, rider: Rider) -> int:
        data = _row_data(rider)
        cur = self.conn.execute(
            f"INSERT INTO riders ({', '.join(data)}) VALUES ({', '.join('?' * len(data))})",
            list(data.values()),
        )
        self.conn.commit()
        return cur.lastrowid

    def update_rider(self, rider: Rider) -> None:
        data = _row_data(rider)
        self.conn.execute(
            f"UPDATE riders SET {', '.join(f'{k} = ?' for k in data)} WHERE id = ?",
            [*data.values(), rider.id],
        )
        self.conn.commit()
        self.prune_grids()

    def delete_rider(self, rider_id: int) -> None:
        self.conn.execute("DELETE FROM riders WHERE id = ?", (rider_id,))
        self.conn.commit()
        self.prune_grids()

    # ------------------------------------------------------------------- bikes
    def bikes(self, rider_id: int | None = None) -> list[Bike]:
        if rider_id is None:
            rows = self.conn.execute("SELECT * FROM bikes ORDER BY rider_id, id").fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM bikes WHERE rider_id = ? ORDER BY id", (rider_id,)).fetchall()
        return [_bike(r) for r in rows]

    # ------------------------------------------------------------ race numbers
    def bike_by_number(self, number: int) -> Bike | None:
        row = self.conn.execute("SELECT * FROM bikes WHERE race_number = ?", (number,)).fetchone()
        return _bike(row) if row else None

    def _check_number(self, bike: Bike) -> None:
        """The race number (chosen by the organisers) identifies the bike: duplicates are refused.
        A bike may still lack one, but then it cannot enter a starting grid."""
        if bike.race_number is None:
            return
        if bike.race_number <= 0:
            raise DuplicateNumber("Il numero di gara deve essere maggiore di zero")
        other = self.bike_by_number(bike.race_number)
        if other is not None and other.id != bike.id:
            owner = self.rider(other.rider_id)
            raise DuplicateNumber(
                f"Il numero {bike.race_number} è già della moto {other.display_name} di {owner.full_name}"
            )

    def add_bike(self, bike: Bike) -> int:
        self._check_number(bike)
        data = _row_data(bike)
        cur = self.conn.execute(
            f"INSERT INTO bikes ({', '.join(data)}) VALUES ({', '.join('?' * len(data))})",
            list(data.values()),
        )
        self.conn.commit()
        return cur.lastrowid

    def update_bike(self, bike: Bike) -> None:
        self._check_number(bike)
        data = _row_data(bike)
        self.conn.execute(
            f"UPDATE bikes SET {', '.join(f'{k} = ?' for k in data)} WHERE id = ?",
            [*data.values(), bike.id],
        )
        self.conn.commit()
        self.prune_grids()

    def update_bikes(self, changed: list[Bike]) -> None:
        """Save several edited bikes at once. Numbers are checked on the final result, so bikes
        can swap numbers; if any number would be duplicated nothing is saved."""
        final = {b.id: b.race_number for b in self.bikes()}
        final.update({b.id: b.race_number for b in changed})
        owners = defaultdict(list)
        for bike_id, number in final.items():
            if number is not None:
                owners[number].append(bike_id)
        by_id = {b.id: b for b in [*self.bikes(), *changed]}
        clashes = [
            f"n° {n}: " + ", ".join(f"{by_id[i].display_name} ({self.rider(by_id[i].rider_id).full_name})" for i in ids)
            for n, ids in sorted(owners.items()) if len(ids) > 1
        ]
        if clashes:
            raise DuplicateNumber("Numeri di gara doppi, nessuna modifica salvata — " + "; ".join(clashes))
        if any(b.race_number is not None and b.race_number <= 0 for b in changed):
            raise DuplicateNumber("Il numero di gara deve essere maggiore di zero")
        with self.conn:
            # Free the numbers first, so a swap does not trip the unique index halfway.
            self.conn.executemany("UPDATE bikes SET race_number = NULL WHERE id = ?", [(b.id,) for b in changed])
            for bike in changed:
                data = _row_data(bike)
                self.conn.execute(
                    f"UPDATE bikes SET {', '.join(f'{k} = ?' for k in data)} WHERE id = ?",
                    [*data.values(), bike.id],
                )
        self.prune_grids()

    def delete_bike(self, bike_id: int) -> None:
        self.conn.execute("DELETE FROM bikes WHERE id = ?", (bike_id,))
        self.conn.commit()
        self.prune_grids()

    def bike_class(self, bike: Bike) -> str | None:
        return class_for(bike.cc, bike.kind, bike.class_override, self.bands)

    # ------------------------------------------------------------- eligibility
    def exclusion_reason(self, bike: Bike, rider: Rider) -> str | None:
        """Why a bike cannot be in a grid, or None if it can."""
        reasons = []
        if bike.withdrawn:
            reasons.append("ritirata")
        if not rider.paid:
            reasons.append("non pagato")
        if not rider.insured:
            reasons.append("senza assicurazione")
        if self.bike_class(bike) is None:
            reasons.append("cilindrata mancante")
        if bike.race_number is None:
            reasons.append("numero di gara mancante")
        return ", ".join(reasons) or None

    def eligible_by_class(self) -> dict[str, list[Entrant]]:
        riders = {r.id: r for r in self.riders()}
        result: dict[str, list[Entrant]] = defaultdict(list)
        for bike in self.bikes():
            if self.exclusion_reason(bike, riders[bike.rider_id]) is None:
                result[self.bike_class(bike)].append(Entrant(bike.id, bike.rider_id))
        return dict(result)

    def excluded(self) -> list[tuple[Rider, Bike, str]]:
        riders = {r.id: r for r in self.riders()}
        out = []
        for bike in self.bikes():
            reason = self.exclusion_reason(bike, riders[bike.rider_id])
            if reason:
                out.append((riders[bike.rider_id], bike, reason))
        return out

    # ------------------------------------------------------------------- grids
    def classes_in_use(self) -> list[str]:
        names = set(self.eligible_by_class()) | {
            r[0] for r in self.conn.execute("SELECT DISTINCT class_name FROM grids")
        }
        return sorted(names, key=lambda c: (CLASS_ORDER.index(c) if c in CLASS_ORDER else 99, c))

    def is_locked(self, class_name: str) -> bool:
        row = self.conn.execute(
            "SELECT MAX(locked) FROM grids WHERE class_name = ?", (class_name,)
        ).fetchone()
        return bool(row[0])

    def set_locked(self, class_name: str, locked: bool) -> None:
        self.conn.execute("UPDATE grids SET locked = ? WHERE class_name = ?", (int(locked), class_name))
        self.conn.commit()

    def draw(self, classes: list[str] | None = None, seed: int | None = None) -> list[str]:
        """(Re)draw the grids of the given classes (all if None). Locked classes are skipped.

        Returns the classes actually drawn.
        """
        eligible = self.eligible_by_class()
        targets = classes if classes is not None else self.classes_in_use()
        drawn = []
        for class_name in targets:
            if self.is_locked(class_name):
                continue
            class_seed = seed if seed is not None else random.SystemRandom().randrange(2**31)
            turns = draw_class(eligible.get(class_name, []), self.max_per_grid, random.Random(class_seed))
            self._store_class(class_name, turns, class_seed)
            drawn.append(class_name)
        return drawn

    def _store_class(self, class_name: str, turns: list[list[int]], seed: int | None) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM grids WHERE class_name = ?", (class_name,))
            for t, bike_ids in enumerate(turns, start=1):
                grid_id = self.conn.execute(
                    "INSERT INTO grids (class_name, turn, seed) VALUES (?, ?, ?)", (class_name, t, seed)
                ).lastrowid
                self.conn.executemany(
                    "INSERT INTO grid_entries VALUES (?, ?, ?)",
                    [(grid_id, b, p) for p, b in enumerate(bike_ids, start=1)],
                )

    def draft(self, seed: int) -> tuple[dict[str, list[list[GridRow]]], dict[int, str]]:
        """Draft grids for double checking, never saved: every bike that is not withdrawn takes
        part, even with missing details (unpaid, uninsured, no number, no cc). Bikes without cc
        go in a separate 'to classify' group. Same rules as the real draw.

        Returns (class -> turns -> rows, bike_id -> what still has to be checked)."""
        riders = {r.id: r for r in self.riders()}
        bikes = [b for b in self.bikes() if not b.withdrawn]
        by_class: dict[str, list[Entrant]] = defaultdict(list)
        issues: dict[int, str] = {}
        for b in bikes:
            r = riders[b.rider_id]
            problems = [text for missing, text in (
                (not r.paid, "non pagato"), (not r.insured, "senza assicurazione"),
                (b.race_number is None, "manca n° gara"), (self.bike_class(b) is None, "manca cilindrata"),
                (b.year is None, "manca anno"),
            ) if missing]
            if problems:
                issues[b.id] = ", ".join(problems)
            by_class[self.bike_class(b) or UNCLASSIFIED].append(Entrant(b.id, b.rider_id))
        bike_of = {b.id: b for b in bikes}
        result = {}
        rng = random.Random(seed)
        for class_name in sorted(by_class, key=_class_sort_key):
            turns = draw_class(by_class[class_name], self.max_per_grid, rng)
            result[class_name] = [[
                GridRow(bike_id=bid, rider_id=bike_of[bid].rider_id, position=pos,
                        race_number=bike_of[bid].race_number, first_name=riders[bike_of[bid].rider_id].first_name,
                        last_name=riders[bike_of[bid].rider_id].last_name, bike=bike_of[bid].display_name,
                        year=bike_of[bid].year)
                for pos, bid in enumerate(turn, start=1)
            ] for turn in turns]
        return result, issues

    def grids(self) -> dict[str, list[list[GridRow]]]:
        """class -> turns -> rows in starting order."""
        rows = self.conn.execute(
            """
            SELECT g.class_name, g.turn, e.position, b.*, r.first_name, r.last_name
            FROM grids g
            LEFT JOIN grid_entries e ON e.grid_id = g.id
            LEFT JOIN bikes b ON b.id = e.bike_id
            LEFT JOIN riders r ON r.id = b.rider_id
            ORDER BY g.class_name, g.turn, e.position
            """
        ).fetchall()
        result: dict[str, dict[int, list[GridRow]]] = defaultdict(dict)
        for row in rows:
            turn = result[row["class_name"]].setdefault(row["turn"], [])
            if row["position"] is None:
                continue
            bike = _bike(row)
            turn.append(GridRow(
                bike_id=bike.id, rider_id=bike.rider_id, position=row["position"],
                race_number=bike.race_number, first_name=row["first_name"],
                last_name=row["last_name"], bike=bike.display_name, year=bike.year,
            ))
        ordered = sorted(result, key=lambda c: (CLASS_ORDER.index(c) if c in CLASS_ORDER else 99, c))
        return {c: [result[c][t] for t in sorted(result[c])] for c in ordered}

    def save_class_layout(self, class_name: str, layout: list[tuple[int, int, int]]) -> None:
        """Manual edit: layout is a list of (bike_id, turn, position)."""
        locked = self.is_locked(class_name)
        turns: dict[int, list[tuple[int, int]]] = defaultdict(list)
        for bike_id, turn, position in layout:
            turns[turn].append((position, bike_id))
        ordered = [[b for _, b in sorted(turns[t])] for t in sorted(turns)]
        seed = self.conn.execute(
            "SELECT seed FROM grids WHERE class_name = ? LIMIT 1", (class_name,)
        ).fetchone()
        self._store_class(class_name, ordered, seed[0] if seed else None)
        self.set_locked(class_name, locked)

    def unplaced(self) -> dict[str, list[Entrant]]:
        """Eligible bikes not yet in a grid (e.g. registered or paid after the draw)."""
        placed = {r[0] for r in self.conn.execute("SELECT bike_id FROM grid_entries")}
        out = {}
        for class_name, entrants in self.eligible_by_class().items():
            missing = [e for e in entrants if e.bike_id not in placed]
            if missing:
                out[class_name] = missing
        return out

    def place_unplaced(self, class_name: str) -> list[int]:
        """Add late bikes to the emptiest turn without the same rider; does not reshuffle others.

        Returns the bike ids that could not be placed.
        """
        missing = self.unplaced().get(class_name, [])
        grids = self.conn.execute(
            "SELECT id FROM grids WHERE class_name = ? ORDER BY turn", (class_name,)
        ).fetchall()
        if not grids:
            self.draw([class_name])
            return []
        failed = []
        for entrant in missing:
            options = []
            for g in grids:
                members = self.conn.execute(
                    "SELECT b.rider_id FROM grid_entries e JOIN bikes b ON b.id = e.bike_id WHERE e.grid_id = ?",
                    (g["id"],),
                ).fetchall()
                riders = [m[0] for m in members]
                if len(riders) < self.max_per_grid and entrant.rider_id not in riders:
                    options.append((len(riders), g["id"]))
            if not options:
                failed.append(entrant.bike_id)
                continue
            size, grid_id = min(options)
            self.conn.execute("INSERT INTO grid_entries VALUES (?, ?, ?)", (grid_id, entrant.bike_id, size + 1))
        self.conn.commit()
        return failed

    def add_turn(self, class_name: str) -> None:
        turn = self.conn.execute(
            "SELECT COALESCE(MAX(turn), 0) + 1 FROM grids WHERE class_name = ?", (class_name,)
        ).fetchone()[0]
        self.conn.execute(
            "INSERT INTO grids (class_name, turn, locked) VALUES (?, ?, ?)",
            (class_name, turn, int(self.is_locked(class_name))),
        )
        self.conn.commit()

    def prune_grids(self) -> None:
        """Drop grid entries that are no longer valid (withdrawn, unpaid, class changed),
        then close the gaps in the starting positions without reshuffling anyone."""
        riders = {r.id: r for r in self.riders()}
        bikes = {b.id: b for b in self.bikes()}
        entries = self.conn.execute(
            "SELECT e.bike_id, e.grid_id, g.class_name FROM grid_entries e JOIN grids g ON g.id = e.grid_id"
        ).fetchall()
        with self.conn:
            for e in entries:
                bike = bikes.get(e["bike_id"])
                if (
                    bike is None
                    or self.exclusion_reason(bike, riders[bike.rider_id]) is not None
                    or self.bike_class(bike) != e["class_name"]
                ):
                    self.conn.execute("DELETE FROM grid_entries WHERE bike_id = ?", (e["bike_id"],))
            for g in self.conn.execute("SELECT id FROM grids").fetchall():
                ids = self.conn.execute(
                    "SELECT bike_id FROM grid_entries WHERE grid_id = ? ORDER BY position", (g["id"],)
                ).fetchall()
                for pos, row in enumerate(ids, start=1):
                    self.conn.execute(
                        "UPDATE grid_entries SET position = ? WHERE bike_id = ?", (pos, row["bike_id"])
                    )
            # Remove grids of classes that have nothing left in them.
            self.conn.execute(
                """DELETE FROM grids WHERE class_name IN (
                       SELECT g.class_name FROM grids g LEFT JOIN grid_entries e ON e.grid_id = g.id
                       GROUP BY g.class_name HAVING COUNT(e.bike_id) = 0)"""
            )

    def clear_all(self) -> None:
        with self.conn:
            for table in ("grid_entries", "grids", "bikes", "riders"):
                self.conn.execute(f"DELETE FROM {table}")


def _class_sort_key(name: str):
    return (CLASS_ORDER.index(name) if name in CLASS_ORDER else 99, name)


def _row_data(obj) -> dict:
    data = asdict(obj)
    data.pop("id")
    return {k: (int(v) if isinstance(v, bool) else v) for k, v in data.items()}


def _rider(row: sqlite3.Row) -> Rider:
    names = {f.name for f in fields(Rider)}
    data = {k: row[k] for k in row.keys() if k in names}
    data["paid"] = bool(data["paid"])
    data["insured"] = bool(data["insured"])
    return Rider(**data)


def _bike(row: sqlite3.Row) -> Bike:
    names = {f.name for f in fields(Bike)}
    data = {k: row[k] for k in row.keys() if k in names}
    data["withdrawn"] = bool(data["withdrawn"])
    return Bike(**data)
