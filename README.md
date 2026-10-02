# MotoGP de Bosch – Gestionale iscrizioni e batterie

Programma locale (funziona senza internet) per:

- registrare gli iscritti e le loro moto (senza limite di numero), con **pagato** e **assicurato**;
- comporre in automatico le **batterie di partenza** per classe (max 8 moto, sorteggio casuale);
- stampare le batterie in **Excel** e **PDF**, nello stesso formato del file 2025.

## Avvio

- **Linux / Mac**: doppio clic su `start.sh` (oppure `./start.sh` da terminale).
- **Windows**: doppio clic su `start.bat`. Serve Python 3 installato da python.org.

Al primo avvio il programma si installa da solo (serve internet solo quella volta).
Poi si apre il browser su `http://localhost:8501`.
Per il PDF serve **LibreOffice** installato; l'Excel funziona comunque.

## Come si usa

1. **Impostazioni**: data della manifestazione (viene stampata sulle batterie) e limiti di cilindrata.
2. **Nuova iscrizione**: in un'unica schermata inserisci il partecipante e le sue moto.
   - Dati del partecipante: nome, cognome, data di nascita, indirizzo, contatti, *Pagato*, *Assicurato* e n° di polizza (facoltativo).
   - Moto: una per riga, ad es. `Honda CB 500 1974`. Il programma separa da solo marca, modello, cilindrata e anno, e mostra la classe.
     Sotto puoi correggere e scrivere il **numero di gara** di ogni moto.
3. **Iscritti**: modifica piloti e moto. Spunta *Pagato* e *Assicurato*.
   - Nelle batterie entra **solo** chi ha entrambe le spunte.
   - *Classe forzata* sposta una moto in un'altra classe (es. una 175 che vuole correre nei 250).
   - *Ritirata* toglie una moto dalle batterie (la moto resta registrata e tiene il suo numero).
   - **Eliminare**: spunta la colonna 🗑️ degli iscritti (o delle moto) e premi *Elimina selezionati*.
     Una finestra mostra cosa verrà cancellato e chiede conferma. Eliminando un iscritto si eliminano anche le sue moto,
     i loro numeri tornano liberi e vengono tolte dalle batterie senza rimescolare gli altri. Non si può annullare.
4. **Controlli**: segnala numeri di gara doppi, dati mancanti e iscritti forse duplicati.
5. **Batterie**: premi **Sorteggia**, poi scarica Excel o PDF.
6. **Bozza batterie**: per ricontrollare prima delle batterie ufficiali. Comprende tutte le moto iscritte
   (tranne le ritirate), anche se mancano pagamento, assicurazione, numero di gara o cilindrata.
   Accanto a ogni moto è scritto cosa manca (colonna *DA VERIFICARE*). Le moto senza cilindrata finiscono
   in un gruppo *DA CLASSIFICARE*. Si stampa in Excel o PDF, con ogni pagina segnata come **BOZZA**.
   La bozza non viene salvata e non cambia le batterie ufficiali; *Nuova bozza* rifà il sorteggio.

## Numero di gara

Ogni moto ha il suo numero, che **date voi** al partecipante; il programma non lo assegna mai da solo.
- Il numero identifica la moto ed è stampato nella colonna *n°* delle batterie.
- Due moto non possono avere lo stesso numero: il programma rifiuta di salvare. Le moto ritirate tengono il loro numero.
- Una moto si può salvare anche senza numero, ma resta fuori dalle batterie finché non lo ricevete
  (la pagina *Controlli* la segnala).
- In *Iscritti* puoi cercare un partecipante scrivendo il numero di una sua moto.

## Regole delle batterie

| Classe | Moto |
|---|---|
| 50 | fino a 100 cc |
| 125 | 101–175 cc |
| 250 | 176–250 cc |
| 350 | 251–399 cc |
| 500 | 400–500 cc |
| OPEN | oltre 500 cc |
| SIDECAR, VESPA E LAMBRETTA, A RULLO | scelte con il *Tipo* della moto |

- Con più di 8 moto la classe si divide in più turni il più possibile uguali (9 → 5+4, 17 → 6+6+5).
- Le moto e l'ordine di partenza vengono sorteggiati.
- Uno stesso pilota non ha mai due moto nello stesso turno.
- **Blocca** una classe per non farla più risorteggiare.
- Se qualcuno si ritira o non risulta più pagato, viene tolto senza rimescolare gli altri.
- Chi si mette in regola dopo il sorteggio si aggiunge con **Aggiungi ai turni esistenti**.
- L'ordine si può sempre correggere a mano.

## Esportare tutti i dati

Il pulsante **⬇️ Esporta tutto in Excel** (in *Iscritti* e in *Impostazioni*) scarica un file pensato per essere
letto e stampato:
- **Iscritti**: ogni partecipante compare **una sola volta** (in ordine di cognome), con i suoi dati
  (nascita, indirizzo, contatti, assicurazione, n° polizza). Accanto a **ogni sua moto** c'è il **numero di gara**
  in grassetto: così si vede subito quale numero va a quale moto. Le caselle gialle sono moto ancora senza numero.
  La colonna **PAGATO è vuota**, da compilare a mano. Ci sono anche classe, turno di batteria e note.
- **Moto per numero**: elenco delle moto in ordine di numero di gara, per trovare subito di chi è una moto.

Si stampa in orizzontale su A4, con l'intestazione ripetuta su ogni pagina.

## Dati e backup

Tutto è salvato nel file `data/motogp.sqlite`. Da **Impostazioni → Scarica backup** se ne scarica una copia.
Per una nuova edizione: scarica il backup, poi usa **Svuota tutto**.

## For developers

Code, comments and scripts are in English; the UI and this user guide are in Italian for the volunteers.

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest                                                            # run the test suite
MOTOGP_DB=/tmp/test.sqlite .venv/bin/streamlit run src/motogp_bosch/app.py  # run against a scratch database
```

| Module | Responsibility |
|---|---|
| `models.py` | `Rider`, `Bike`, `GridRow` dataclasses |
| `db.py` | SQLite schema and migrations, CRUD, race-number uniqueness, draw / draft / grid maintenance |
| `classes.py` | cc bands and bike types → race class |
| `grids.py` | pure, seedable draw algorithm (even split, max per grid, one bike per rider per turn) |
| `validate.py` | consistency checks shown on the *Controlli* page |
| `parsing.py` | splits free-text bike descriptions into brand, model, cc and year |
| `export_xlsx.py` | starting grids (official and draft) in the 2025 template layout |
| `export_pdf.py` | PDF conversion through LibreOffice headless |
| `export_data.py` | human-readable full data export |
| `app.py` | Streamlit UI |
