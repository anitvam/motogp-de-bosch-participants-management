import random
from collections import Counter

import pytest

from motogp_bosch.classes import class_for
from motogp_bosch.db import Database, DuplicateNumber
from motogp_bosch.export_xlsx import build_workbook, italian_date
from motogp_bosch.grids import Entrant, draw_class, turn_sizes
from motogp_bosch.parsing import parse_bike
from motogp_bosch.models import Bike, Rider

@pytest.mark.parametrize("cc, expected", [
    (50, "50"), (100, "50"), (101, "125"), (175, "125"), (176, "250"), (250, "250"),
    (251, "350"), (399, "350"), (400, "500"), (500, "500"), (501, "OPEN"), (1000, "OPEN"),
])
def test_class_bands(cc, expected):
    assert class_for(cc) == expected


def test_class_kind_and_override():
    assert class_for(None, "sidecar") == "SIDECAR"
    assert class_for(125, "vespa") == "VESPA-LAMBR"
    assert class_for(175, override="250") == "250"
    assert class_for(None) is None


@pytest.mark.parametrize("n, turns, sizes", [(8, 1, [8]), (9, 2, [5, 4]), (17, 3, [6, 6, 5])])
def test_even_split(n, turns, sizes):
    entrants = [Entrant(i, i) for i in range(n)]
    grid = draw_class(entrants, 8, random.Random(1))
    assert [len(t) for t in grid] == sizes
    assert turn_sizes(n, turns) == sizes
    assert sorted(b for t in grid for b in t) == list(range(n))


@pytest.mark.parametrize("seed", range(50))
def test_rider_never_twice_in_a_turn(seed):
    # 3 riders with 3 bikes, 2 with 2 bikes, 6 singles = 19 bikes -> 3 turns
    entrants, bike = [], 0
    for rider, count in enumerate([3, 3, 3, 2, 2, 1, 1, 1, 1, 1, 1]):
        for _ in range(count):
            entrants.append(Entrant(bike, rider))
            bike += 1
    rider_of = {e.bike_id: e.rider_id for e in entrants}
    grid = draw_class(entrants, 8, random.Random(seed))
    for turn in grid:
        assert len(turn) <= 8
        assert max(Counter(rider_of[b] for b in turn).values()) == 1


def test_small_class_split_for_multi_bike_rider():
    # Only 3 bikes but one rider owns 2: needs two turns.
    grid = draw_class([Entrant(1, 1), Entrant(2, 1), Entrant(3, 2)], 8, random.Random(0))
    assert len(grid) == 2


def test_same_seed_same_draw():
    entrants = [Entrant(i, i // 2) for i in range(20)]
    assert draw_class(entrants, 8, random.Random(42)) == draw_class(entrants, 8, random.Random(42))


def _db_with(n_riders=10, cc=125, paid=True, insured=True):
    db = Database()
    for i in range(n_riders):
        rid = db.add_rider(Rider(None, f"Nome{i}", f"Cognome{i}", paid=paid, insured=insured))
        db.add_bike(Bike(None, rid, "HONDA", "CB", cc, 1970, race_number=i + 1))
    return db


def test_only_paid_and_insured_in_grids():
    db = Database()
    for i, (paid, insured) in enumerate([(True, True), (True, False), (False, True), (False, False)]):
        rid = db.add_rider(Rider(None, f"N{i}", f"C{i}", paid=paid, insured=insured))
        db.add_bike(Bike(None, rid, "HONDA", "CB", 125, 1970, race_number=i + 1))
    db.draw(seed=1)
    rows = [r for turns in db.grids().values() for t in turns for r in t]
    assert [r.first_name for r in rows] == ["N0"]


def test_unpaying_removes_without_reshuffle():
    db = _db_with(6)
    db.draw(seed=3)
    before = [r.bike_id for r in db.grids()["125"][0]]
    victim = db.rider(db.grids()["125"][0][2].rider_id)
    victim.paid = False
    db.update_rider(victim)
    after = [r.bike_id for r in db.grids()["125"][0]]
    assert after == [b for b in before if b != before[2]]
    assert [r.position for r in db.grids()["125"][0]] == list(range(1, 6))


def test_locked_class_survives_redraw():
    db = _db_with(10)
    db.draw(seed=1)
    before = db.grids()
    db.set_locked("125", True)
    assert db.draw(seed=2) == []
    assert db.grids() == before


def test_late_bike_is_placed_without_reshuffle():
    db = _db_with(9)
    db.draw(seed=1)
    before = {r.bike_id: (t, r.position) for t, rows in enumerate(db.grids()["125"]) for r in rows}
    rid = db.add_rider(Rider(None, "Late", "Comer", paid=True, insured=True))
    db.add_bike(Bike(None, rid, "DUCATI", "", 125, 1968, race_number=99))
    assert "125" in db.unplaced()
    assert db.place_unplaced("125") == []
    after = {r.bike_id: (t, r.position) for t, rows in enumerate(db.grids()["125"]) for r in rows}
    assert all(after[b] == pos for b, pos in before.items())
    assert len(after) == 10


def test_no_limit_on_bikes_per_rider():
    db = Database()
    rid = db.add_rider(Rider(None, "A", "B", paid=True, insured=True))
    for n in range(1, 6):
        db.add_bike(Bike(None, rid, "X", cc=125, race_number=n))
    assert len(db.bikes(rid)) == 5
    db.draw(seed=1)
    turns = db.grids()["125"]
    assert len(turns) == 5 and all(len(t) == 1 for t in turns)  # still never two in the same turn


def test_duplicate_numbers_refused():
    db = _db_with(2)  # numbers 1 and 2
    rid = db.add_rider(Rider(None, "X", "Y"))
    with pytest.raises(DuplicateNumber):
        db.add_bike(Bike(None, rid, "DUCATI", cc=250, race_number=1))
    second = db.bikes()[1]
    second.race_number = 1
    with pytest.raises(DuplicateNumber):
        db.update_bike(second)


def test_number_never_assigned_automatically():
    db = Database()
    rid = db.add_rider(Rider(None, "A", "B", paid=True, insured=True))
    db.add_bike(Bike(None, rid, "X", cc=125))
    assert db.bikes()[0].race_number is None
    db.draw(seed=1)
    assert db.grids() == {}
    assert any("numero di gara mancante" in reason for _, _, reason in db.excluded())


def test_withdrawn_bike_keeps_its_number():
    db = _db_with(1)
    bike = db.bikes()[0]
    bike.withdrawn = True
    db.update_bike(bike)
    rid = db.add_rider(Rider(None, "X", "Y"))
    with pytest.raises(DuplicateNumber):
        db.add_bike(Bike(None, rid, "X", cc=125, race_number=bike.race_number))


def test_old_database_numbers_repaired(tmp_path):
    import sqlite3
    path = tmp_path / "old.sqlite"
    Database(path)  # create schema
    conn = sqlite3.connect(path)
    conn.execute("DROP INDEX bikes_race_number")
    conn.execute("INSERT INTO riders (first_name, last_name) VALUES ('A', 'B')")
    conn.executemany("INSERT INTO bikes (rider_id, brand, race_number) VALUES (1, 'X', ?)", [(5,), (5,), (None,)])
    conn.commit()
    conn.close()
    db = Database(path)
    assert [b.race_number for b in db.bikes()] == [5, None, None]
    assert db.renumbered == [(2, 5)]
    assert "numero 5 duplicato" in db.bikes()[1].notes


@pytest.mark.parametrize("text, brand, cc, year", [
    ("honda cb 500 1974", "HONDA", 500, 1974),
    ("MOTO MORINI GTI 250 1966 ", "MOTO MORINI", 250, 1966),
    ("benelli 250 2C 1974", "BENELLI", 250, 1974),
    ("MV AGUSTA 350 S", "MV AGUSTA", 350, None),
    ("suzuki 380", "SUZUKI", 380, None),
    ("honda supermono 56rr 600 1984", "HONDA", 600, 1984),
    ("LAVERDA RATANTINA 75 1952", "LAVERDA", 75, 1952),
])
def test_parse_bike(text, brand, cc, year):
    p = parse_bike(text)
    assert (p["brand"], p["cc"], p["year"]) == (brand, cc, year)


def test_italian_date():
    from datetime import date
    assert italian_date(date(2025, 9, 14)) == "Domenica 14 Settembre 2025"


def test_rider_personal_fields_roundtrip():
    db = Database()
    rid = db.add_rider(Rider(None, "Mario", "Rossi", address="Via Roma 1", birth_date="1950-03-21",
                             insurance_id="POL-123"))
    r = db.rider(rid)
    assert (r.address, r.birth_date, r.insurance_id) == ("Via Roma 1", "1950-03-21", "POL-123")


def test_old_database_gets_new_columns(tmp_path):
    import sqlite3
    path = tmp_path / "old.sqlite"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE riders (id INTEGER PRIMARY KEY, first_name TEXT NOT NULL DEFAULT '', "
                 "last_name TEXT NOT NULL DEFAULT '', town TEXT NOT NULL DEFAULT '', province TEXT NOT NULL DEFAULT '', "
                 "phone TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '', paid INTEGER NOT NULL DEFAULT 0, "
                 "insured INTEGER NOT NULL DEFAULT 0, notes TEXT NOT NULL DEFAULT '')")
    conn.execute("INSERT INTO riders (first_name, last_name, paid) VALUES ('Old', 'Rider', 1)")
    conn.commit()
    conn.close()
    r = Database(path).riders()[0]
    assert (r.first_name, r.paid, r.birth_date, r.insurance_id) == ("Old", True, "", "")


def test_bikes_can_swap_numbers():
    db = _db_with(3)  # numbers 1, 2, 3
    a, b, c = db.bikes()
    a.race_number, b.race_number = 2, 1
    db.update_bikes([a, b])
    assert [x.race_number for x in db.bikes()] == [2, 1, 3]


def test_bulk_update_with_duplicate_saves_nothing():
    db = _db_with(3)
    a, b, c = db.bikes()
    a.race_number, a.brand = 3, "CHANGED"
    with pytest.raises(DuplicateNumber):
        db.update_bikes([a])
    assert db.bikes()[0].race_number == 1 and db.bikes()[0].brand == "HONDA"


def test_delete_rider_removes_bikes_frees_numbers_keeps_grid_order():
    db = _db_with(6)
    db.draw(seed=5)
    order = [r.bike_id for r in db.grids()["125"][0]]
    victim = db.grids()["125"][0][1]
    db.delete_rider(victim.rider_id)
    assert all(r.id != victim.rider_id for r in db.riders())
    assert db.bike_by_number(victim.race_number) is None
    assert [r.bike_id for r in db.grids()["125"][0]] == [b for b in order if b != victim.bike_id]


def test_full_export_layout():
    from motogp_bosch.export_data import COLUMNS, TOP_ROWS, build_export
    db = Database()
    rid = db.add_rider(Rider(None, "Mario", "Rossi", town="Gambettola", address="Via Roma 1",
                             birth_date="1950-03-21", paid=True, insured=True, insurance_id="POL-1",
                             notes="porta il caffè"))
    db.add_bike(Bike(None, rid, "HONDA", "CB 500", 500, 1974, race_number=13))
    db.add_bike(Bike(None, rid, "LAMBRETTA", "LI", 150, 1960, kind="vespa", race_number=7))
    db.add_bike(Bike(None, rid, "DUCATI", "MACH 1", 250, 1964, notes="freni da rifare"))  # no number yet
    db.add_rider(Rider(None, "Senza", "Moto"))

    wb = build_export(db)
    ws = wb["Iscritti"]
    col = {name: i + 1 for i, (name, _, _) in enumerate(COLUMNS)}
    first = TOP_ROWS + 2
    # Moto Senza (no bikes) comes first alphabetically, then Rossi with 3 bike rows.
    assert ws.cell(first, col["COGNOME"]).value == "Moto"
    rossi = first + 1
    assert ws.cell(rossi, col["COGNOME"]).value == "Rossi"
    assert ws.cell(rossi + 1, col["COGNOME"]).value is None  # written once, merged
    assert f"A{rossi}:A{rossi + 2}" in {str(m) for m in ws.merged_cells.ranges}
    pairs = [(ws.cell(r, col["N°"]).value, ws.cell(r, col["MARCA"]).value) for r in range(rossi, rossi + 3)]
    assert pairs == [(7, "LAMBRETTA"), (13, "HONDA"), (None, "DUCATI")]
    assert ws.cell(rossi + 2, col["N°"]).fill.fgColor.rgb.endswith("FFE699")  # missing number highlighted
    assert ws.cell(rossi, col["PAGATO"]).value is None  # left to fill in by hand
    assert ws.cell(rossi, col["NOTE"]).value == "porta il caffè; n° ?: freni da rifare"
    assert ws.cell(rossi, col["ASSICURATO"]).value == "Sì"
    lookup = wb["Moto per numero"]
    assert [lookup.cell(r, 1).value for r in range(TOP_ROWS + 2, TOP_ROWS + 5)] == [7, 13, None]


def test_draft_includes_incomplete_bikes_and_saves_nothing():
    from motogp_bosch.classes import UNCLASSIFIED
    db = Database()
    ok = db.add_rider(Rider(None, "Ok", "Rider", paid=True, insured=True))
    db.add_bike(Bike(None, ok, "HONDA", "", 125, 1970, race_number=1))
    unpaid = db.add_rider(Rider(None, "Non", "Pagato", insured=True))
    db.add_bike(Bike(None, unpaid, "DUCATI", "", 125, None, race_number=2))
    db.add_bike(Bike(None, unpaid, "BENELLI", "", 125, 1960))  # no number, same rider, same class
    db.add_bike(Bike(None, unpaid, "MISTERO", "", None, 1950, race_number=3))  # no cc
    db.add_bike(Bike(None, ok, "RITIRATA", "", 125, 1970, race_number=4, withdrawn=True))

    draft, issues = db.draft(seed=1)
    assert db.grids() == {}  # nothing saved, official grids untouched
    in_draft = {r.bike: r for turns in draft.values() for t in turns for r in t}
    assert set(in_draft) == {"HONDA 125", "DUCATI 125", "BENELLI 125", "MISTERO"}
    assert UNCLASSIFIED in draft
    assert in_draft["HONDA 125"].bike_id not in issues
    assert issues[in_draft["DUCATI 125"].bike_id] == "non pagato, manca anno"
    assert "manca n° gara" in issues[in_draft["BENELLI 125"].bike_id]
    assert "manca cilindrata" in issues[in_draft["MISTERO"].bike_id]
    # rider rule still holds: the two 125s of the unpaid rider are in different turns
    turns = draft["125"]
    assert all(sum(r.rider_id == unpaid for r in t) <= 1 for t in turns)
    assert db.draft(seed=1) == (draft, issues)

    wb = build_workbook(draft, "Domenica 13 Settembre 2026", draft_issues=issues)
    ws = wb["125"]
    assert ws["F5"].value == "DA VERIFICARE" and "BOZZA" in ws["D4"].value
