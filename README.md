# Prize Bond Manager

A desktop app (Python + PyQt6 + SQLite) to keep track of your prize bonds, record draw results,
and let a **win-checking agent** find winners for you. Nothing leaves your waiting list until
**you approve it**.

- **Import** bonds from `.csv`, `.xlsx` or `.docx` (also `.tsv`, `.txt`) or type them in: one bond,
  a range, a list, or whole **copies** (books / batches).
- **Copies are flexible**: each copy has its own numbers, size and sequence. Every bond keeps its
  **position** in its copy.
- **The same number may sit in several copies. When that number wins, every bond holding it wins.**
- **Win-checking agent**: compares the waiting list with the winning numbers and puts matches in a
  temporary *Pending Wins* list. After you approve them they move to the final *Win List*.
- **Detailed win reports**: for every winning bond - which **copy**, the **1st bond number of that
  copy**, and the **exact position** of the bond inside it.
- **Dashboard**, **history log**, bonds **grouped by price** (100, 200, 750, 1500, ...), sortable and
  filterable tables, and **export** of any list (or everything) to CSV or Excel.

---

## 1. Quick start

```bash
# 1. Python 3.10 or newer
python -m venv .venv
.venv\Scripts\activate            # Windows      (Linux/macOS:  source .venv/bin/activate)
pip install -r requirements.txt

# 2. run
python main.py                    # your own data  ->  data/prize_bonds.db
python main.py --demo             # a throw-away demo database with sample bonds, copies and a draw
python main.py --db D:\bonds_db\my.db   # use a data file somewhere else (or set PRIZE_BOND_DB)
```

The data lives in one SQLite file (default `data/prize_bonds.db`). Copy it to back it up, or use
**File -> Back up database...**.

**Try it in two minutes** (with the files in `sample_data/`):

1. `python main.py --db data/try.db`
2. **File -> Import from file...** -> `sample_data/bonds_with_copies.csv` -> *Import*
   (Book A and Book B share the numbers 100011-100020 - that is allowed; the dialog points it out).
3. Import `copies_workbook.xlsx` (one copy per sheet) and `copies_list.docx` (choose price Rs 100).
4. **Draw Results** -> draw price **Any denomination** -> *Import from file...* -> `winning_numbers.csv`
   -> **Save draw and check my bonds**.
5. **Pending Wins** now lists 7 bonds for 4 winning numbers (three numbers are held in two copies).
   Select one row and **Approve selected**: the bond with the same number in the other copy is
   approved with it. The report shows both bonds with their copy, 1st bond number and position.

---

## 2. Screens (layout plan)

```
+--------------+---------------------------------------------------------------------+
| Prize Bond   |  Page title                                      [page actions]     |
| Manager      |  short explanation                                                  |
|              |  -------------------------------------------------------------------|
|  Dashboard   |                                                                     |
|  My Bonds    |                      page content                                   |
|  Copies      |            (searchable, sortable tables + Export...)                |
|  Draw Results|                                                                     |
|  Pending (4) |                                                                     |
|  Win List    |                                                                     |
|  History     |                                                                     |
|  data file   |                                                                     |
+--------------+---------------------------------------------------------------------+
| status bar                                                                         |
+------------------------------------------------------------------------------------+
Menus: File (Add bonds, Import, Export everything, Back up, Quit)  Agent  View  Help
```

| Page | What it does |
| --- | --- |
| **Dashboard** | Active bonds, investment value, wins so far, matches waiting for approval; holdings by price; recent draw hits; how many numbers are held more than once; shortcut buttons. A yellow banner appears when the agent has something for you to review. |
| **My Bonds** | One tab per price (plus *All prices*). Filters: status (waiting / drawn / all), number range, purchase-date range, *only numbers held more than once*. Search, sort, **Add**, **Import**, **Edit**, **Delete**. Columns: number, price, purchase date, status, **Same number** (how many bonds hold it), copy, position, 1st bond of the copy. |
| **Copies (Books)** | Every copy with its 1st bond number, size (positions), waiting / won counts. *View bonds* shows the copy position by position. Rename, delete (with or without its bonds). |
| **Draw Results** | 1. choose or create a draw (date, price or *Any denomination*, name); 2. paste / type / import winning numbers with a prize tier and amount; **Save draw and check my bonds**. Recorded draws and their numbers are listed on the right. |
| **Pending Wins** | The agent's temporary list: draw, bond number, prize, **bonds with this number**, copy, 1st bond of the copy, position, check column. **Approve selected / Approve all / Reject selected / Restore selected**. Switch to the *Rejected* view to see dismissed matches. |
| **Win List** | The final list of approved wins with the same copy details. *Show report*, *Save report...*, *Move back to waiting list* (undo an approval). Double-click a row for the report. |
| **History** | Log of everything: bonds added / imported / deleted, draws, agent scans, approvals, rejections. |

Dialogs: **Add bonds** (tab *Copies* with a table of copies and a number box per copy, tab *Single
bond / range / list*), **Import**, **Edit bond**, **Edit copy**, **Copy contents**, **Win report**.

Keyboard: `Ctrl+N` add bonds, `Ctrl+I` import, `Ctrl+E` export everything, `Ctrl+R` run the agent,
`Ctrl+1 ... Ctrl+7` pages, `Ctrl+C` copies the selected table rows.

---

## 3. How it works

### Copies, first bond number and position

A **copy** is one physical book or batch. The order you type or import its numbers is its physical
order, so the **position** is simply "which bond in the book":

| Copy | Numbers typed | Position of 100056 |
| --- | --- | --- |
| Copy 1 | `100001-100100` | 56 of 100 (1st bond number: 100001) |
| Copy 5 | `100050-100060` | 7 of 11 (1st bond number: 100050) |
| Copy 3 | `400100-400001` (descending) | `400001` is position 100 |
| Copy 2 | `555001-555020, 777777, 900001-900010:3` | `777777` is position 21 |

Copies do not need the same range, size or sequence. If a bond is removed later, the copy keeps its
size and the other bonds keep their positions. Number patterns accepted everywhere:
`123456`, `100001-100100`, `100001 to 100100`, `100001-100100:2` (every 2nd), and lists separated
by commas, spaces or new lines. Numbers are matched as integers, so `123` equals `000123`.

### The same number in several copies

- **Allowed:** any number of copies may hold the same number (same price). Each of those bonds
  keeps its own copy, 1st bond number and position.
- **Not allowed:** one copy holding a number twice (the app keeps it once and says so).
- **When the number is drawn, all of those bonds win.** The agent queues every one of them, and
  approving any one of them approves the others that are still pending. The report lists each bond
  with its own copy / 1st bond number / position and the total prize for the number.
- A bond you **rejected** is not pulled back in by approving its siblings, and *Move back to
  waiting list* only moves the rows you select.
- **Adding numbers you already hold:** *Add bonds* asks (*Add all* / *Skip numbers I already have* /
  *Cancel*); *Import* shows a notice and a **Skip numbers I already have** tick box. Copies added
  together may share numbers even when you choose to skip: "skip" only looks at what was in your
  list before.
- **My Bonds** shows how many bonds hold each number and can show *only numbers held more than once*.
- Bonds of the same number but a different **price** are different bonds.

### Win-checking agent and approval

```
 winning numbers saved / bonds added / app started / "Run agent now"
                         |
                         v
   waiting list  --(agent compares)-->  PENDING WINS  --(you approve)-->  WIN LIST
   (status active)                      (temporary)      reject -> stays in the waiting list
```

- A bond matches when it is waiting, has a winning number and the draw's price (a draw saved with
  *Any denomination* matches every price). Re-running the agent never creates duplicates, and matches you
  rejected stay rejected (restore them from the *Rejected* view).
- The agent runs **automatically** at start-up, after bonds are added / imported and after a draw
  is saved. Untick *Run automatically* on the Pending Wins page to run it only by hand.
- **Approval re-checks each match.** If the bond was edited or its price changed after the scan, it
  is not approved and you are told why. Rows in amber are flagged (bond bought *after* the draw
  date) - check them before approving.
- Approving writes a permanent **snapshot** (copy name, 1st bond number, position, copy size, prize),
  so the report is still correct if the bond or copy is edited or deleted later.
- *Move back to waiting list* undoes an approval (even if the bond was deleted meanwhile).

### Win report

Each winning number shows draw, prize and, when several bonds hold it, a line such as
*"2 of your bonds hold this number, so all 2 win"* followed by one block per bond:

```
Winning number 100056 (Rs 750)
  Draw  : 2026-10-01 - Draw #98
  Prize : 1st Prize - Rs 1,500,000 per bond
  Held  : 2 bonds - Copy 1, Copy 5
  Total : Rs 3,000,000
  Bond 1 of 2
    Copy (book)                  : Copy 1
    1st bond number of this copy : 100001
    Position in this copy        : 56 of 100 - the 56th bond in the copy
  Bond 2 of 2
    Copy (book)                  : Copy 5
    1st bond number of this copy : 100050
    Position in this copy        : 7 of 11 - the 7th bond in the copy
```

Open it from the Win List (*Show report* or double-click) or right after approving. *Copy as text* and
*Save report...* (HTML, text, Excel or CSV) are in the report window.

### Importing files

| File | How it is read |
| --- | --- |
| `.csv` / `.tsv` | Header row recognised by name (see below); without a header the column that looks like bond numbers is used. Comma, semicolon, tab or pipe separated. |
| `.xlsx` / `.xlsm` | Every sheet is read; with several sheets each sheet becomes one copy. Leading zeros and `123456.0` cells are handled. |
| `.docx` | Paragraphs and tables. A line like `Copy 2:` or `Book 3` names the copy for the numbers that follow it. Each table is read like a sheet. |
| `.txt` | Free text; numbers and ranges anywhere, `Copy N:` lines name copies. |

Recognised columns (names are not case sensitive): **Bond Number** (also *Bond No, Number, Serial*),
**Denomination** (*Price, Value, Rs*), **Date of Purchase** (*Date, Purchased, Bought*),
**Copy** (*Book, Batch, Set*), **Position** (*Pos, Place, Seq*). Day-first dates such as `10/01/2025`
are understood, as are ISO dates. Ranges such as `100001-100050` work inside a cell.

In the import dialog you choose how copies are made: **Automatic** (Copy column / headings / one
copy per sheet or file), **One copy for the whole file**, **Split into copies of N bonds**, or **No
copies (loose bonds)**. If the file has no price, pick one (it is required). A preview shows every
bond with the copy and position it will get; the import is all-or-nothing.

### Export

Every table has an **Export...** button that writes exactly what is shown (current search, filter
and sort order) to `.xlsx` or `.csv`. **File -> Export everything** writes one Excel workbook (all
bonds, waiting bonds per price, copies, pending wins, win list, draws, winning numbers, activity
log) or one CSV file per list. Excel files keep bond numbers as text, so leading zeros stay. CSV files use UTF-8 with a BOM
(Excel reads them with the right encoding) and also contain the zeros, but Excel may hide them
when it opens a CSV - use the Excel export if that matters.

---

## 4. Project layout

```
prize_bond_manager/
|-- main.py                  start here (python main.py [--demo] [--db FILE])
|-- requirements.txt         PyQt6, pandas, openpyxl, python-docx
|-- requirements-dev.txt     + pytest
|-- pytest.ini
|-- README.md
|-- sample_data/             example CSV / Excel / Word files + winning numbers
|-- tools/make_sample_data.py   regenerates sample_data/
|-- app/
|   |-- config.py            constants (price list, 6-digit numbers, limits, data path)
|   |-- models.py            small result objects (AddResult, ScanResult, ApprovalResult)
|   |-- demo.py              demo data used by --demo
|   |-- db/                  DATA LAYER - SQLite only, no UI
|   |   |-- core.py          schema, transactions, settings, activity log, backup
|   |   |-- bonds_repo.py    bonds and copies (add, append, edit, delete, positions)
|   |   |-- draws_repo.py    draws and winning numbers
|   |   `-- wins_repo.py     agent scan, pending list, approve / reject, win list, dashboard stats
|   |-- processing/          LOGIC - no UI, no SQL strings except through app.db
|   |   |-- numbers.py       bond-number parsing (single, ranges, steps, lists)
|   |   |-- parsers.py       read csv / xlsx / docx / txt into plain tables
|   |   |-- importer.py      understand columns, copies, positions; plan and commit an import
|   |   |-- agent.py         the win-checking agent + approval wrapper
|   |   |-- reports.py       win reports (text / HTML / table) grouped by winning number
|   |   `-- exporter.py      CSV / Excel writers and the "everything" workbook
|   `-- ui/                  INTERFACE - PyQt6
|       |-- main_window.py   sidebar, pages, menus
|       |-- context.py       shared state (database, agent, signals)
|       |-- actions.py       add / import / export / backup actions
|       |-- theme.py, widgets.py, table_model.py   look and reusable table widgets
|       |-- pages/           dashboard, bonds, copies, draws, pending, wins, history
|       `-- dialogs/         add bonds, copies editor, import, edit bond / copy, win report
`-- tests/                   pytest: numbers, database, agent, importer, export/reports,
                             sample files, headless GUI smoke tests
```

### Data model (SQLite)

| Table | Holds |
| --- | --- |
| `copies` | name, 1st bond number (kept even if that bond is removed), size (positions), note |
| `bonds` | number (text) + numeric key, price, purchase date, status `active` / `won`, copy, position. One copy never holds the same number twice; different copies may |
| `draws` / `winning_numbers` | draw date, price (or any), label; winning numbers with prize tier and amount |
| `pending_wins` | the agent's temporary list: one row per (bond, winning number), status `pending` / `approved` / `rejected` |
| `wins` | the final win list with a snapshot of the copy details |
| `activity_log`, `settings` | history page; agent on/off and last-run text |

---

## 5. Tests

```bash
pip install -r requirements-dev.txt
python -m pytest            # the GUI tests run headless (Qt "offscreen" platform)
```

## 6. Troubleshooting

- **Linux:** if Qt says it cannot load the platform plugin `xcb`, install the missing library
  (Debian / Ubuntu: `sudo apt install libxcb-cursor0`).
- **"This database was created by a newer version"**: the data file comes from a newer release;
  start with a different `--db` file or update the app.
- **A file will not import**: open it in the import dialog to see what was understood; the notes box
  lists unreadable cells. Password-protected Excel files cannot be read.
- **Export fails**: the target file is probably open in Excel - close it and try again.
