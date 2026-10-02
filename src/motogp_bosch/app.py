"""Streamlit UI.

Launch with ``./start.sh`` (or ``streamlit run src/motogp_bosch/app.py``).
User-facing text is in Italian, for the event volunteers; code and comments are in English.
Set ``MOTOGP_DB`` to use a different database file (e.g. for testing).
"""
from __future__ import annotations

import json
import os
import random
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from motogp_bosch.parsing import parse_bike
from motogp_bosch.classes import CLASS_ORDER, CLASS_TITLES, KINDS
from motogp_bosch.db import Database, DuplicateNumber
from motogp_bosch.export_data import build_export
from motogp_bosch.export_pdf import find_soffice, xlsx_to_pdf
from motogp_bosch.export_xlsx import build_workbook, italian_date, to_bytes
from motogp_bosch.models import Bike, Rider
from motogp_bosch.validate import check

DB_PATH = Path(os.environ.get("MOTOGP_DB", Path(__file__).resolve().parents[2] / "data" / "motogp.sqlite"))
KIND_BY_LABEL = {label: code for code, label in KINDS.items()}
AUTO = "(automatica)"

st.set_page_config(page_title="MotoGP de Bosch", page_icon="🏍️", layout="wide")


@st.cache_resource
def get_db() -> Database:
    DB_PATH.parent.mkdir(exist_ok=True)
    return Database(DB_PATH)


db = get_db()
if db.renumbered and not st.session_state.get("renumbered_seen"):
    st.session_state["renumbered_seen"] = True
    st.warning(f"{len(db.renumbered)} moto avevano un numero di gara già usato da un'altra: "
               "ora sono senza numero (vedi **Controlli**). Assegnalo tu dalla pagina Iscritti.")


def as_int(value) -> int | None:
    if value is None or (isinstance(value, float) and pd.isna(value)) or value == "":
        return None
    return int(value)


def as_str(value) -> str:
    return "" if value is None or (isinstance(value, float) and pd.isna(value)) else str(value).strip()


def as_iso(value) -> str:
    """Date from a table cell -> 'yyyy-mm-dd' ('' if empty)."""
    if value is None or (not isinstance(value, (date, str)) and pd.isna(value)):
        return ""
    return value.strftime("%Y-%m-%d") if hasattr(value, "strftime") else str(value)[:10]


def go_to(page: str) -> None:
    st.session_state["page"] = page


def event_date() -> date | None:
    text = db.setting("event_date")
    return date.fromisoformat(text) if text else None


def editor_key(name: str, df: pd.DataFrame) -> str:
    """Key that changes with the data, so stale edits are never applied to new rows."""
    return f"{name}_{int(pd.util.hash_pandas_object(df, index=False).sum()) if len(df) else 0}"


def flash(message: str, kind: str = "success") -> None:
    st.session_state["flash"] = (kind, message)


def show_flash() -> None:
    if "flash" in st.session_state:
        kind, message = st.session_state.pop("flash")
        getattr(st, kind)(message)


# ================================================ Participants page (Iscritti)
def page_riders() -> None:
    st.header("Iscritti")
    show_flash()
    riders = db.riders()
    bikes = db.bikes()
    n_bikes = {r.id: 0 for r in riders}
    for b in bikes:
        n_bikes[b.rider_id] += 1

    c1, c2, c3, c4 = st.columns([3, 1, 1, 1])
    search = c1.text_input("Cerca", placeholder="nome, cognome, comune o n° di gara…").lower().strip()
    only_unpaid = c2.checkbox("Solo non pagati")
    only_uninsured = c3.checkbox("Solo senza assicurazione")
    c4.metric("In regola", f"{sum(r.eligible for r in riders)} / {len(riders)}")

    numbers = {r.id: [] for r in riders}
    for b in bikes:
        if b.race_number is not None:
            numbers[b.rider_id].append(str(b.race_number))
    shown = [
        r for r in riders
        if (search in f"{r.first_name} {r.last_name} {r.town}".lower() or search in numbers[r.id])
        and (not only_unpaid or not r.paid)
        and (not only_uninsured or not r.insured)
    ]
    c1, c2, _ = st.columns([2, 3, 3])
    c1.button("➕ Nuova iscrizione", on_click=go_to, args=(NEW_PAGE,))
    with c2:
        export_button()
    df = pd.DataFrame([{
        "id": r.id, "Elimina": False, "Cognome": r.last_name, "Nome": r.first_name,
        "Nato il": date.fromisoformat(r.birth_date) if r.birth_date else None,
        "Indirizzo": r.address, "Comune": r.town, "Prov.": r.province, "Telefono": r.phone,
        "Email": r.email, "Pagato": r.paid, "Assicurato": r.insured, "N° polizza": r.insurance_id,
        "Moto": n_bikes[r.id], "N° moto": ", ".join(numbers[r.id]), "Note": r.notes,
    } for r in shown], columns=["id", "Elimina", "Cognome", "Nome", "Nato il", "Indirizzo", "Comune", "Prov.",
                                "Telefono", "Email", "Pagato", "Assicurato", "N° polizza", "Moto", "N° moto", "Note"])
    edited = st.data_editor(
        df, hide_index=True, width="stretch", key=editor_key("riders", df),
        disabled=["id", "Moto", "N° moto"],
        column_config={
            "id": None,
            "Elimina": st.column_config.CheckboxColumn("🗑️", help="Spunta per eliminare l'iscritto e le sue moto"),
            "N° moto": st.column_config.TextColumn(help="Numeri di gara delle sue moto"),
            "Nato il": st.column_config.DateColumn(format="DD/MM/YYYY", min_value=date(1900, 1, 1)),
            "Pagato": st.column_config.CheckboxColumn(help="Iscrizione pagata"),
            "Assicurato": st.column_config.CheckboxColumn(help="Assicurazione valida"),
            "N° polizza": st.column_config.TextColumn(help="Numero della polizza assicurativa (facoltativo)"),
        },
    )
    to_delete = [int(r["id"]) for r in edited.to_dict("records") if r["Elimina"]]
    c1, c2, _ = st.columns([2, 2, 4])
    if c2.button(f"🗑️ Elimina selezionati ({len(to_delete)})", disabled=not to_delete, key="del_riders"):
        confirm_delete(rider_ids=to_delete, bike_ids=[])
    if c1.button("💾 Salva modifiche iscritti", type="primary"):
        changed = 0
        for row in edited.to_dict("records"):
            new = Rider(
                id=int(row["id"]), first_name=as_str(row["Nome"]), last_name=as_str(row["Cognome"]),
                town=as_str(row["Comune"]), province=as_str(row["Prov."]), address=as_str(row["Indirizzo"]),
                birth_date=as_iso(row["Nato il"]), phone=as_str(row["Telefono"]), email=as_str(row["Email"]),
                paid=bool(row["Pagato"]), insured=bool(row["Assicurato"]),
                insurance_id=as_str(row["N° polizza"]), notes=as_str(row["Note"]),
            )
            if new != db.rider(new.id):
                db.update_rider(new)
                changed += 1
        flash(f"{changed} iscritti aggiornati")
        st.rerun()

    st.subheader("Moto")
    page_bikes(riders, bikes, {r.id for r in shown})


def bikes_entry(key: str) -> tuple[list[dict], list[str]]:
    """Bikes typed one per line ('Honda CB 500 1974'); split automatically into brand, model,
    cc and year, shown in an editable table where the organisers also write the race number.
    Returns (bikes as Bike kwargs, blocking errors)."""
    text = st.text_area(
        "Moto: una per riga", key=f"{key}_text", height=120,
        placeholder="Honda CB 500 1974\nMoto Morini Settebello 175 1958",
        help="Scrivi marca, modello, cilindrata e anno: il programma li separa da solo. Sotto puoi correggere.",
    )
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return [], []
    parsed = [parse_bike(line) for line in lines]
    df = pd.DataFrame([{
        "N° gara": None, "Marca": p["brand"], "Modello": p["model"], "cc": p["cc"], "Anno": p["year"],
        "Tipo": KINDS[p["kind"]],
    } for p in parsed], columns=["N° gara", "Marca", "Modello", "cc", "Anno", "Tipo"])
    df["N° gara"] = df["N° gara"].astype("Int64")
    st.caption("Scrivi nella colonna **N° gara** il numero che consegnate al partecipante per ogni moto.")
    edited = st.data_editor(
        df, hide_index=True, width="stretch", key=editor_key(f"{key}_bikes", df),
        column_config={
            "N° gara": st.column_config.NumberColumn(min_value=1, step=1, help="Numero che identifica la moto"),
            "cc": st.column_config.NumberColumn(min_value=0, max_value=3000, step=1),
            "Anno": st.column_config.NumberColumn(min_value=1890, max_value=2100, step=1, format="%d"),
            "Tipo": st.column_config.SelectboxColumn(options=list(KIND_BY_LABEL), required=True),
        },
    )
    bikes, errors, typed = [], [], []
    for row in edited.to_dict("records"):
        bike = {
            "brand": as_str(row["Marca"]).upper(), "model": as_str(row["Modello"]).upper(),
            "cc": as_int(row["cc"]), "year": as_int(row["Anno"]),
            "kind": KIND_BY_LABEL.get(row["Tipo"], "moto"), "race_number": as_int(row["N° gara"]),
        }
        if not bike["brand"]:
            continue
        preview = Bike(None, 0, **bike)
        class_name = db.bike_class(preview)
        number = f"n° **{bike['race_number']}**" if bike["race_number"] else "n° ?"
        line = f"{number} · **{preview.display_name}**" + (f" ({bike['year']})" if bike["year"] else "")
        if class_name:
            st.markdown(f"✅ {line} → classe **{CLASS_TITLES.get(class_name, class_name)}**")
        else:
            st.markdown(f"⚠️ {line} → cilindrata mancante: indicala nella tabella")
        n = bike["race_number"]
        if n is None:
            st.warning(f"{preview.display_name}: manca il numero di gara. Puoi salvare e aggiungerlo dopo, "
                       "ma finché manca la moto non entra nelle batterie.")
        elif (other := db.bike_by_number(n)) is not None:
            errors.append(f"Il numero {n} è già della moto {other.display_name} di {db.rider(other.rider_id).full_name}")
        elif n in typed:
            errors.append(f"Il numero {n} è scritto per due moto")
        if n is not None:
            typed.append(n)
        bikes.append(bike)
    for e in errors:
        st.error(e)
    return bikes, errors


def page_bikes(riders: list[Rider], bikes: list[Bike], visible_riders: set[int]) -> None:
    names = {r.id: f"{r.last_name} {r.first_name}" for r in riders}
    shown = sorted((b for b in bikes if b.rider_id in visible_riders), key=lambda b: (names[b.rider_id], b.id))
    df = pd.DataFrame([{
        "id": b.id, "Elimina": False, "N° gara": b.race_number, "Iscritto": names[b.rider_id], "Marca": b.brand,
        "Modello": b.model, "cc": b.cc, "Anno": b.year, "Tipo": KINDS.get(b.kind, b.kind),
        "Classe": db.bike_class(b) or "?", "Classe forzata": b.class_override or AUTO,
        "Ritirata": b.withdrawn, "Note": b.notes,
    } for b in shown], columns=["id", "Elimina", "N° gara", "Iscritto", "Marca", "Modello", "cc", "Anno", "Tipo",
                                "Classe", "Classe forzata", "Ritirata", "Note"])
    df["N° gara"] = df["N° gara"].astype("Int64")
    edited = st.data_editor(
        df, hide_index=True, width="stretch", key=editor_key("bikes", df),
        disabled=["id", "Iscritto", "Classe"],
        column_config={
            "id": None,
            "cc": st.column_config.NumberColumn(min_value=0, max_value=3000, step=1),
            "Anno": st.column_config.NumberColumn(min_value=1890, max_value=2100, step=1, format="%d"),
            "Elimina": st.column_config.CheckboxColumn("🗑️", help="Spunta per eliminare la moto"),
            "N° gara": st.column_config.NumberColumn(min_value=1, step=1, help="Numero che identifica la moto"),
            "Tipo": st.column_config.SelectboxColumn(options=list(KIND_BY_LABEL), required=True),
            "Classe forzata": st.column_config.SelectboxColumn(
                options=[AUTO, *CLASS_ORDER], required=True,
                help="Per mettere una moto in una classe diversa da quella della sua cilindrata"),
            "Ritirata": st.column_config.CheckboxColumn(help="Esclude la moto dalle batterie"),
        },
    )
    bikes_to_delete = [int(r["id"]) for r in edited.to_dict("records") if r["Elimina"]]
    c1, c2, _ = st.columns([2, 2, 4])
    if c2.button(f"🗑️ Elimina selezionate ({len(bikes_to_delete)})", disabled=not bikes_to_delete, key="del_bikes"):
        confirm_delete(rider_ids=[], bike_ids=bikes_to_delete)
    if c1.button("💾 Salva modifiche moto", type="primary"):
        current = {b.id: b for b in bikes}
        changed = []
        for row in edited.to_dict("records"):
            old = current[int(row["id"])]
            new = Bike(
                id=old.id, rider_id=old.rider_id, brand=as_str(row["Marca"]).upper(),
                model=as_str(row["Modello"]).upper(), cc=as_int(row["cc"]), year=as_int(row["Anno"]),
                kind=KIND_BY_LABEL.get(row["Tipo"], "moto"), race_number=as_int(row["N° gara"]),
                class_override=None if row["Classe forzata"] in (AUTO, None) else row["Classe forzata"],
                withdrawn=bool(row["Ritirata"]), notes=as_str(row["Note"]),
            )
            if new != old:
                changed.append(new)
        try:
            db.update_bikes(changed)
            flash(f"{len(changed)} moto aggiornate")
        except DuplicateNumber as e:
            flash(str(e), "error")
        st.rerun()

    with st.expander("➕ Aggiungi moto a un iscritto esistente"):
        rid = st.selectbox("Iscritto", list(names), format_func=names.get, index=None, key="ab_rider")
        if rid is not None:
            version = st.session_state.setdefault("ab_v", 0)
            new_bikes, errors = bikes_entry(f"ab{version}")
            if st.button("Aggiungi moto", disabled=not new_bikes or bool(errors)):
                for b in new_bikes:
                    db.add_bike(Bike(None, rid, **b))
                st.session_state["ab_v"] = version + 1
                flash(f"{len(new_bikes)} moto aggiunte a {names[rid]}")
                st.rerun()


@st.dialog("Conferma eliminazione")
def confirm_delete(rider_ids: list[int], bike_ids: list[int]) -> None:
    in_grid = {r.bike_id for turns in db.grids().values() for rows in turns for r in rows}
    bikes = {b.id: b for b in db.bikes()}
    # Ignore anything already deleted (e.g. a stale selection) and bikes of riders being deleted.
    existing_riders = {r.id for r in db.riders()}
    rider_ids = [rid for rid in rider_ids if rid in existing_riders]
    bike_ids = [bid for bid in bike_ids if bid in bikes and bikes[bid].rider_id not in rider_ids]
    if not (rider_ids or bike_ids):
        st.info("Niente da eliminare.")
        return
    lines, freed = [], []
    for rid in rider_ids:
        r = db.rider(rid)
        own = db.bikes(rid)
        desc = ", ".join(f"n° {b.race_number or '?'} {b.display_name}" for b in own) or "nessuna moto"
        lines.append(f"- **{r.full_name}** con le sue moto: {desc}")
        freed += [b for b in own]
    for bid in bike_ids:
        b = bikes[bid]
        lines.append(f"- moto **n° {b.race_number or '?'} {b.display_name}** di {db.rider(b.rider_id).full_name}")
        freed.append(b)
    st.markdown("Stai per eliminare:\n" + "\n".join(lines))
    numbers = sorted(b.race_number for b in freed if b.race_number is not None)
    if numbers:
        st.caption(f"I numeri di gara {', '.join(map(str, numbers))} torneranno liberi.")
    if any(b.id in in_grid for b in freed):
        st.warning("Alcune di queste moto sono già nelle batterie: verranno tolte, "
                   "gli altri piloti restano al loro posto.")
    st.error("L'operazione **non si può annullare**. Se hai dubbi, scarica prima un backup da Impostazioni.")
    c1, c2 = st.columns(2)
    if c1.button("🗑️ Elimina definitivamente", type="primary", key="del_confirm"):
        for rid in rider_ids:
            db.delete_rider(rid)
        for bid in bike_ids:
            db.delete_bike(bid)
        what = []
        if rider_ids:
            what.append(f"{len(rider_ids)} {'iscritto' if len(rider_ids) == 1 else 'iscritti'}")
        if bike_ids:
            what.append(f"{len(bike_ids)} moto")
        flash(f"Eliminazione completata: {' e '.join(what)}")
        st.rerun()
    if c2.button("Annulla", key="del_cancel"):
        st.rerun()


def export_button() -> None:
    stamp = date.today().isoformat()
    st.download_button(
        "⬇️ Esporta tutto in Excel", to_bytes(build_export(db, event_date())),
        file_name=f"MotoGP de Bosch - iscritti {stamp}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        help="Tutti gli iscritti e le loro moto, con il numero di gara",
    )


# ==================================== New registration page (Nuova iscrizione)
def page_new() -> None:
    st.header("Nuova iscrizione")
    show_flash()
    # Bumping the version gives every widget a fresh key, which empties the form after saving.
    version = st.session_state.setdefault("new_v", 0)
    k = f"new{version}"

    st.subheader("Partecipante")
    c = st.columns(3)
    first = c[0].text_input("Nome *", key=f"{k}_first")
    last = c[1].text_input("Cognome *", key=f"{k}_last")
    birth = c[2].date_input("Data di nascita", value=None, min_value=date(1900, 1, 1),
                            max_value=date.today(), format="DD/MM/YYYY", key=f"{k}_birth")
    c = st.columns([3, 2, 1])
    address = c[0].text_input("Indirizzo", placeholder="Via Roma 1", key=f"{k}_addr")
    town = c[1].text_input("Comune", key=f"{k}_town")
    prov = c[2].text_input("Prov.", max_chars=2, key=f"{k}_prov")
    c = st.columns(2)
    phone = c[0].text_input("Telefono", key=f"{k}_phone")
    email = c[1].text_input("Email", key=f"{k}_email")
    c = st.columns([1, 1, 2])
    paid = c[0].checkbox("Pagato", key=f"{k}_paid")
    insured = c[1].checkbox("Assicurato", key=f"{k}_ins")
    insurance_id = c[2].text_input("N° polizza assicurativa (facoltativo)", key=f"{k}_insid")
    notes = st.text_input("Note", key=f"{k}_notes")

    name_key = frozenset(f"{first} {last}".lower().split())
    if len(name_key) >= 2:
        same = [r for r in db.riders() if frozenset(f"{r.first_name} {r.last_name}".lower().split()) == name_key]
        if same:
            st.warning(f"Esiste già un iscritto con questo nome: {same[0].full_name}. "
                       "Per aggiungergli moto usa **Iscritti → Aggiungi moto a un iscritto esistente**.")

    st.subheader("Moto")
    bikes, errors = bikes_entry(k)

    if st.button("💾 Salva iscrizione", type="primary", disabled=bool(errors),
                 help="Correggi prima i numeri di gara doppi" if errors else None):
        if not (first.strip() and last.strip()):
            st.error("Nome e cognome sono obbligatori")
            return
        rid = db.add_rider(Rider(
            id=None, first_name=first.strip().title(), last_name=last.strip().title(),
            town=town.strip(), province=prov.strip().upper(), address=address.strip(),
            birth_date=birth.isoformat() if birth else "", phone=phone.strip(), email=email.strip(),
            paid=paid, insured=insured, insurance_id=insurance_id.strip(), notes=notes.strip(),
        ))
        for b in bikes:
            db.add_bike(Bike(None, rid, **b))
        st.session_state["new_v"] = version + 1
        flash(f"Iscritto {first.strip().title()} {last.strip().title()} con {len(bikes)} moto")
        st.rerun()


# ============================================== Starting grids page (Batterie)
def page_grids() -> None:
    st.header("Batterie di partenza")
    show_flash()
    if not db.setting("event_date"):
        st.warning("Imposta la data della manifestazione in **Impostazioni**: viene stampata sulle batterie.")
    grids = db.grids()

    c1, c2, _ = st.columns([2, 2, 3])
    confirm = c2.checkbox("Confermo: rifai il sorteggio", value=not grids,
                          help="Le classi bloccate 🔒 non vengono toccate")
    if c1.button("🎲 Sorteggia tutte le batterie", type="primary", disabled=not confirm):
        drawn = db.draw()
        flash(f"Sorteggiate: {', '.join(drawn) or 'nessuna: nessuna moto in regola o classi tutte bloccate'}",
              "success" if drawn else "warning")
        st.rerun()

    downloads(grids)

    excluded = db.excluded()
    if excluded:
        a, b = st.columns([5, 2])
        a.caption(f"{len(excluded)} moto non possono ancora entrare nelle batterie ufficiali perché mancano dei dati. "
                  "Per vedere comunque come verrebbero le batterie, apri la bozza.")
        b.button("📝 Apri la bozza", on_click=go_to, args=(DRAFT_PAGE,))
        with st.expander(f"🚫 {len(excluded)} moto escluse dalle batterie"):
            st.dataframe(pd.DataFrame([{
                "Iscritto": r.full_name, "Moto": b.display_name, "Motivo": reason,
            } for r, b, reason in excluded]), hide_index=True, width="stretch")

    unplaced = db.unplaced()
    for class_name, missing in unplaced.items():
        bikes = {b.id: b for b in db.bikes()}
        names = ", ".join(f"{db.rider(e.rider_id).full_name} ({bikes[e.bike_id].display_name})" for e in missing)
        with st.container(border=True):
            st.warning(f"**{class_name}**: {len(missing)} moto in regola ma non ancora in batteria: {names}")
            a, b, _ = st.columns([2, 2, 4])
            if a.button("Aggiungi ai turni esistenti", key=f"place_{class_name}",
                        help="Gli altri piloti restano dove sono"):
                failed = db.place_unplaced(class_name)
                flash("Inserite" if not failed else f"{len(failed)} moto non inseribili: aggiungi un turno o risorteggia",
                      "success" if not failed else "warning")
                st.rerun()
            if b.button("Risorteggia la classe", key=f"redraw_u_{class_name}", disabled=db.is_locked(class_name)):
                db.draw([class_name])
                st.rerun()

    if not grids:
        st.info("Nessuna batteria ancora. Segna pagamenti e assicurazioni, poi premi **Sorteggia**.")
        return

    for class_name, turns in grids.items():
        grid_class(class_name, turns)


def grid_class(class_name: str, turns) -> None:
    locked = db.is_locked(class_name)
    total = sum(len(t) for t in turns)
    title = f"{'🔒 ' if locked else ''}{CLASS_TITLES.get(class_name, class_name)} — {total} moto, {len(turns)} turn{'o' if len(turns) == 1 else 'i'}"
    with st.expander(title, expanded=False):
        a, b, c, _ = st.columns([2, 2, 2, 4])
        if a.toggle("Blocca", value=locked, key=f"lock_{class_name}",
                    help="Una classe bloccata non viene risorteggiata") != locked:
            db.set_locked(class_name, not locked)
            st.rerun()
        if b.button("🎲 Risorteggia", key=f"redraw_{class_name}", disabled=locked):
            db.draw([class_name])
            flash(f"{class_name} risorteggiata")
            st.rerun()
        if c.button("➕ Aggiungi turno", key=f"turn_{class_name}", disabled=locked):
            db.add_turn(class_name)
            st.rerun()

        cols = st.columns(max(len(turns), 1))
        for i, rows in enumerate(turns):
            with cols[i]:
                st.markdown(f"**{i + 1}° turno** ({len(rows)}/{db.max_per_grid})")
                st.dataframe(pd.DataFrame([{
                    "n°": r.race_number, "Nome": r.first_name, "Cognome": r.last_name,
                    "Moto": r.bike, "Anno": r.year,
                } for r in rows], columns=["n°", "Nome", "Cognome", "Moto", "Anno"]),
                    hide_index=True, width="stretch")

        if locked:
            return
        st.caption("Modifica a mano: cambia turno o posizione e salva. La posizione decide l'ordine in griglia.")
        df = pd.DataFrame([{
            "bike_id": r.bike_id, "Turno": t + 1, "Posizione": r.position, "n°": r.race_number,
            "Pilota": f"{r.first_name} {r.last_name}", "Moto": r.bike,
        } for t, rows in enumerate(turns) for r in rows])
        edited = st.data_editor(
            df, hide_index=True, width="stretch", key=editor_key(f"edit_{class_name}", df),
            disabled=["bike_id", "n°", "Pilota", "Moto"],
            column_config={
                "bike_id": None,
                "Turno": st.column_config.NumberColumn(min_value=1, max_value=len(turns), step=1),
                "Posizione": st.column_config.NumberColumn(min_value=1, max_value=20, step=1),
            },
        )
        if st.button("💾 Salva ordine", key=f"save_{class_name}"):
            db.save_class_layout(class_name, [
                (int(r["bike_id"]), int(r["Turno"]), int(r["Posizione"])) for r in edited.to_dict("records")
            ])
            problems = [i.message for i in check(db) if i.message.startswith(f"Batteria {class_name},")]
            flash("Salvato" + (": " + "; ".join(problems) if problems else ""), "warning" if problems else "success")
            st.rerun()


@st.cache_data(show_spinner="Creo il PDF…", max_entries=4)
def grids_pdf(xlsx: bytes) -> bytes:
    return xlsx_to_pdf(xlsx)


def downloads(grids) -> None:
    """Always-visible print section: Excel and PDF of the starting grids, same layout as the 2025 file."""
    with st.container(border=True):
        st.subheader("🖨️ Stampa batterie")
        has_grids = any(rows for turns in grids.values() for rows in turns)
        a, b, c = st.columns([2, 2, 4])
        if not has_grids:
            a.button("⬇️ Excel batterie", disabled=True, key="xlsx_off")
            b.button("⬇️ PDF batterie", disabled=True, key="pdf_off")
            c.caption("Disponibili dopo il sorteggio. Entrano nelle batterie solo le moto con numero di gara, "
                      "di iscritti che hanno **pagato** e sono **assicurati**.")
            return
        xlsx = to_bytes(build_workbook(grids, italian_date(event_date()), db.max_per_grid))
        stamp = event_date().isoformat() if event_date() else date.today().isoformat()
        a.download_button("⬇️ Excel batterie", xlsx, file_name=f"Batterie MotoGP de Bosch {stamp}.xlsx",
                          mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                          type="primary", help="Un foglio per classe, come il file del 2025")
        pages = sum(1 for turns in grids.values() for rows in turns if rows)
        if find_soffice() is None:
            b.button("⬇️ PDF batterie", disabled=True, key="pdf_off")
            c.caption(f"{pages} batterie. Per il PDF installa LibreOffice (gratuito); "
                      "intanto puoi stampare direttamente l'Excel.")
            return
        try:
            pdf = grids_pdf(xlsx)
        except Exception as e:  # noqa: BLE001 - shown to the user
            b.button("⬇️ PDF batterie", disabled=True, key="pdf_off")
            c.error(f"Errore nella creazione del PDF: {e}")
            return
        b.download_button("⬇️ PDF batterie", pdf, file_name=f"Batterie MotoGP de Bosch {stamp}.pdf",
                          mime="application/pdf", type="primary", help="Una pagina per ogni batteria, pronta da stampare")
        c.caption(f"{pages} batterie, una per pagina. I file si aggiornano da soli dopo ogni modifica.")


# =========================================== Draft grids page (Bozza batterie)
def page_draft() -> None:
    st.header("Bozza batterie")
    st.info(
        "La bozza serve a **controllare** le batterie prima di quelle ufficiali. Comprende **tutte le moto iscritte** "
        "(tranne le ritirate), anche se mancano pagamento, assicurazione, numero di gara o cilindrata: "
        "accanto a ogni moto è scritto cosa manca. La bozza **non viene salvata** e non cambia le batterie ufficiali."
    )
    seed = st.session_state.setdefault("draft_seed", random.SystemRandom().randrange(2**31))
    draft, issues = db.draft(seed)
    rows = [r for turns in draft.values() for t in turns for r in t]
    if not rows:
        st.warning("Nessuna moto iscritta.")
        return
    flagged = sum(r.bike_id in issues for r in rows)
    c = st.columns([1, 1, 1, 2])
    c[0].metric("Moto nella bozza", len(rows))
    c[1].metric("Da verificare", flagged)
    c[2].metric("Pronte", len(rows) - flagged)
    if c[3].button("🎲 Nuova bozza", help="Rifà il sorteggio della bozza"):
        st.session_state["draft_seed"] = random.SystemRandom().randrange(2**31)
        st.rerun()
    only_flagged = st.toggle("Mostra solo le classi con moto da verificare")

    with st.container(border=True):
        st.subheader("🖨️ Stampa bozza")
        xlsx = to_bytes(build_workbook(draft, italian_date(event_date()), db.max_per_grid, draft_issues=issues))
        stamp = date.today().isoformat()
        a, b, cap = st.columns([2, 2, 4])
        a.download_button("⬇️ Excel bozza", xlsx, file_name=f"BOZZA batterie MotoGP de Bosch {stamp}.xlsx",
                          mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        if find_soffice() is None:
            cap.caption("Per il PDF installa LibreOffice; intanto puoi stampare l'Excel.")
        else:
            try:
                b.download_button("⬇️ PDF bozza", grids_pdf(xlsx), mime="application/pdf",
                                  file_name=f"BOZZA batterie MotoGP de Bosch {stamp}.pdf")
                cap.caption("Ogni pagina è segnata come BOZZA, con la colonna DA VERIFICARE.")
            except Exception as e:  # noqa: BLE001 - shown to the user
                cap.error(f"Errore nella creazione del PDF: {e}")

    for class_name, turns in draft.items():
        n_flag = sum(r.bike_id in issues for t in turns for r in t)
        if only_flagged and not n_flag:
            continue
        total = sum(len(t) for t in turns)
        label = (f"{CLASS_TITLES.get(class_name, class_name)} — {total} moto, {len(turns)} "
                 f"turn{'o' if len(turns) == 1 else 'i'}" + (f" · ⚠️ {n_flag} da verificare" if n_flag else " · ✅"))
        with st.expander(label, expanded=bool(n_flag)):
            cols = st.columns(len(turns))
            for i, t in enumerate(turns):
                with cols[i]:
                    st.markdown(f"**{i + 1}° turno** ({len(t)}/{db.max_per_grid})")
                    df = pd.DataFrame([{
                        "n°": r.race_number, "Pilota": f"{r.first_name} {r.last_name}", "Moto": r.bike,
                        "Anno": r.year, "Da verificare": issues.get(r.bike_id, "✅"),
                    } for r in t])
                    df["n°"] = df["n°"].astype("Int64")
                    df["Anno"] = df["Anno"].astype("Int64")
                    st.dataframe(
                        df.style.apply(lambda row: ["background-color: #fde2e1" if row["Da verificare"] != "✅"
                                                    else "" for _ in row], axis=1),
                        hide_index=True, width="stretch",
                    )


# ===================================================== Checks page (Controlli)
def page_checks() -> None:
    st.header("Controlli")
    issues = check(db)
    if not issues:
        st.success("Nessun problema trovato 👍")
    counts = {lvl: sum(i.level == lvl for i in issues) for lvl in ("errore", "attenzione", "info")}
    c = st.columns(3)
    c[0].metric("Errori", counts["errore"])
    c[1].metric("Avvisi", counts["attenzione"])
    c[2].metric("Info", counts["info"])
    show_info = st.checkbox("Mostra anche le informazioni (pagamenti/assicurazioni mancanti)")
    for issue in issues:
        if issue.level == "errore":
            st.error(issue.message)
        elif issue.level == "attenzione":
            st.warning(issue.message)
        elif show_info:
            st.info(issue.message)


# ================================================ Settings page (Impostazioni)
def page_settings() -> None:
    st.header("Impostazioni")
    show_flash()
    with st.form("settings"):
        day = st.date_input("Data della manifestazione", value=event_date(), format="DD/MM/YYYY")
        if day:
            st.caption(f"Sulle batterie: *{italian_date(day)}*")
        max_grid = st.number_input("Moto massime per batteria", 2, 20, db.max_per_grid)
        st.markdown("**Cilindrata massima di ogni classe** (cc inclusi)")
        bands = db.bands
        cols = st.columns(len(bands) - 1)
        limits = [cols[i].number_input(name, 0, 3000, max_cc, key=f"band_{name}")
                  for i, (max_cc, name) in enumerate(bands[:-1])]
        st.caption(f"Oltre {limits[-1]} cc → {bands[-1][1]}. Sidecar, Vespa/Lambretta e A rullo si scelgono col tipo di moto.")
        if st.form_submit_button("Salva", type="primary"):
            if limits != sorted(limits):
                st.error("I limiti devono essere crescenti")
            else:
                db.set_setting("event_date", day.isoformat() if day else "")
                db.set_setting("max_per_grid", str(max_grid))
                new_bands = [[lim, name] for lim, (_, name) in zip(limits, bands[:-1])] + [[None, bands[-1][1]]]
                db.set_setting("bands", json.dumps(new_bands))
                flash("Impostazioni salvate")
                st.rerun()

    st.subheader("Esporta i dati")
    st.caption("Un file Excel da leggere o stampare: ogni iscritto compare una volta, con il numero di gara "
               "accanto a ciascuna sua moto. La colonna PAGATO è vuota, da compilare a mano.")
    export_button()

    st.subheader("Backup")
    st.caption(f"Tutti i dati sono nel file `{DB_PATH}`. Scaricane una copia ogni tanto.")
    st.download_button("⬇️ Scarica backup", DB_PATH.read_bytes(),
                       file_name=f"motogp-backup-{date.today().isoformat()}.sqlite")

    with st.expander("⚠️ Svuota tutto (nuova edizione)"):
        st.write("Cancella iscritti, moto e batterie. Le impostazioni restano. **Scarica prima il backup!**")
        if st.text_input("Scrivi CANCELLA per confermare") == "CANCELLA" and st.button("Svuota", type="primary"):
            db.clear_all()
            flash("Dati cancellati")
            st.rerun()


NEW_PAGE = "➕ Nuova iscrizione"
DRAFT_PAGE = "📝 Bozza batterie"
PAGES = {
    NEW_PAGE: page_new,
    "🏍️ Iscritti": page_riders,
    "🏁 Batterie": page_grids,
    DRAFT_PAGE: page_draft,
    "✅ Controlli": page_checks,
    "⚙️ Impostazioni": page_settings,
}

with st.sidebar:
    st.title("MotoGP de Bosch")
    if event_date():
        st.caption(italian_date(event_date()))
    page = st.radio("Sezione", list(PAGES), label_visibility="collapsed", key="page")
    riders = db.riders()
    st.divider()
    st.caption(f"{len(riders)} iscritti · {len(db.bikes())} moto · {sum(r.eligible for r in riders)} in regola")

PAGES[page]()
