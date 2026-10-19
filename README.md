# Prize Bond Manager

A desktop app (Python + PyQt6 + SQLite) to keep track of your prize bonds, record draw results,
and let a **win-checking agent** find winners for you. No win is recorded until **you approve it**.

- **Import** bonds from `.csv`, `.xlsx` or `.docx` (also `.tsv`, `.txt`) or type them in: one bond,
  a range, a list, or whole **copies** (books / batches).
- **Copies are flexible**: each copy has its own numbers, size and sequence. Every bond keeps its
  **position** in its copy.
- **The same number may sit in several copies. When that number wins, every bond holding it wins.**
- **Win-checking agent**: compares all your bonds with the winning numbers and puts matches in a
  temporary *Pending Wins* list. After you approve them they are recorded in the final *Win List*.
- **A bond can win more than once.** It stays in every later draw; each win is its own row in the
  Win List (other draw, other **location**, other date) and says which win it is ("2 of 3").
- **Win List tracking**: every win has a **location**, a claim **status** (Not claimed yet / Claim
  submitted / Paid / Problem) and a free **feedback** note.
- **Detailed win reports**: for every winning bond - which **copy**, the **1st bond number of that
  copy**, and the **exact position** of the bond inside it.
- **Location (optional)** on every bond, copy, draw and win: where a bond is kept, where a draw was
  held, where a prize is claimed. Leave it empty if it does not matter.
- **Draw results two ways**: type them in (or import a file), **or fetch them automatically** from
  the official National Savings site - API first, then its pages, `.txt` and `.pdf` files, then
  prizebond.net - and let the agent check your bonds.
- **Sales**: record bonds you sold to other people (buyer, contact, place, date, price). Sold bonds
  leave your list automatically - copies, bonds, dashboard and exports update by themselves - and a
  sale can be undone.
- **Check thousands of numbers at once**: a built-in checker answers 10,000 bonds in about ten
  milliseconds, from the window or through a local `POST /check` API.
- **Dashboard**, **history log**, bonds **grouped by price** (100, 200, 750, 1500, ...), sortable and
  filterable tables, and **export** of any list (or everything) to CSV or Excel.

---

## 1. Quick start

```bash
# 1. Python 3.10 or newer
python -m venv .venv
.venv\Scripts\activate            # Windows      (Linux/macOS:  source .venv/bin/activate)
pip install -r requirements.txt          # add requirements-api.txt for the local API

# 2. run
python main.py                    # your own data  ->  prize_bonds.db next to main.py
python main.py --db my.db         # a data file named my.db, kept next to main.py
python main.py --demo             # a throw-away demo.db with sample bonds, copies and a draw
python main.py --db D:\bonds\my.db   # a full path is used as it is (or set PRIZE_BOND_DB)
python main.py --serve            # no window: the local checking API on http://127.0.0.1:8765
```

**Where the data file lives.** Your data is one SQLite file. A name without a folder (`my.db`) is
kept **next to the program** (next to `main.py`, or next to the `.exe` if you package the app) -
not in whatever folder you started it from. So `python main.py --db my.db` finds the same file
wherever you launch it from. To use an existing `my.db`, copy it next to `main.py`. The sidebar
shows the file name; hover over it for the full path. (Data in the older `data/prize_bonds.db` is
still found if no new file exists.) Copy the file to back it up, or use **File -> Back up
database...**.

**The data file is locked while the app is open.** The app keeps a lock on `my.db` (a small
`my.db.lock` file beside it), so a second window - or a second run of the program - cannot open the
same file and mix up your wins; it says so and stops. The lock belongs to the operating system: it
is released when the app closes **or crashes**, so it can never get stuck. (If you wanted a
password on the file instead, that is a different feature - not included.)

**Upgrading from an older version.** A data file from an earlier version is upgraded
automatically the first time you open it. Nothing is lost, and a copy of the old file is kept as
`<name>.before-upgrade.bak` first. Bonds that were marked "won" in the old version go back into play
(they take part in every later draw). The newest version (data format 3) adds the Location fields,
the Sales tables and the "typed in / fetched" mark on draws; older files get them empty.

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
6. Open **Win List**, select rows and press **Status / location...** to set the claim status
   (*Claim submitted*, *Paid* ...), the location and a feedback note. Rows are coloured by status.

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
|  Sales       |                                                                     |
|  History     |                                                                     |
|  data file   |                                                                     |
+--------------+---------------------------------------------------------------------+
| status bar                                                                         |
+------------------------------------------------------------------------------------+
Menus: File (Add bonds, Import, Export everything, Back up, Quit)  Agent (run agent, get results
from the web, check a list of numbers)  View  Help
```

| Page | What it does |
| --- | --- |
| **Dashboard** | Your bonds, investment value, wins so far (and how many are **not paid yet**, how many bonds won more than once), matches waiting for approval; holdings by price; recent draw hits with their claim status; how many numbers are held more than once; shortcut buttons. A yellow banner appears when the agent has something for you to review. |
| **My Bonds** | One tab per price (plus *All prices*). Filters: **bonds I hold / bonds I sold / both**, all bonds / bonds that have won / bonds that never won, number range, purchase-date range, *shared numbers only*. Search, sort, **Add**, **Import**, **Sell selected...**, **Edit**, **Delete**. Columns: number, price, purchase date, status (*Active* or *Sold 2026-09-20 to ...*), **Location**, **Times won**, **Same number** (how many bonds hold it), copy, position, 1st bond of the copy. Sold bonds are greyed. |
| **Copies (Books)** | Every copy with its 1st bond number, size (positions), **Held**, **Sold**, **Won**, **Location**. *View bonds* shows the copy position by position (with location and sold state). **Sell copy...**, **Edit** (name, note, location - optionally on every bond), delete (with or without its bonds). |
| **Draw Results** | 1. choose or create a draw (date, price or *Any denomination*, name, **location**); 2. paste / type / import winning numbers with a prize tier and amount; **Save draw and check my bonds**. Or press **Get results from the web...** (see section 3). The list of recorded draws shows whether each was *Typed in* or *Fetched* from a site. An official result file (`.txt` / `.pdf`) or a saved prizebond.net page can be imported whole, with every prize tier and amount. |
| **Pending Wins** | The agent's temporary list: draw, **location**, bond number, prize, **bonds with this number**, copy, 1st bond of the copy, position, **won before** (a repeat winner), check column. **Approve selected / Approve all / Reject selected / Restore selected**. Switch to the *Rejected* view to see dismissed matches. |
| **Win List** | The final list of approved wins: draw date, **location**, bond number, prize, copy, 1st bond of the copy, position, **bond kept at**, **bond sold** (if it was sold later), **same number**, **win no.**, **status**, **feedback**, draw, approved on. *Show report*, *Save report...*, **Status / location...** (edit the selected wins), *Undo approval* (remove a win approved by mistake). Rows are coloured: green = Paid, amber = Claim submitted, red = Problem. Double-click a row for the report. |
| **Sales** | Every sale: date, buyer, contact, location, bonds, face value, amount received, difference to face value, copies, note. **Record a sale...**, **Details** (the bonds of the sale; *Take back selected bonds*), **Edit**, **Undo sale**. |
| **History** | Log of everything: bonds added / imported / deleted, sales, draws, fetches, agent scans, approvals, rejections. |

Dialogs: **Add bonds** (tab *Copies* with a table of copies and a number box per copy, tab *Single
bond / range / list*), **Import**, **Edit bond**, **Edit copy**, **Copy contents**, **Win report**,
**Win details** (status / location / feedback), **Sell bonds**, **Sale details**, **Get draw results from the web**, **Check a list of numbers**. In *Generate copies*, "Numbers skipped between
copies" leaves a gap between one copy's last number and the next copy's first number (with 100
bonds per copy, first number 100001 and a gap of 10: 100001-100100, then 100111-100210, ...).

Keyboard: `Ctrl+N` add bonds, `Ctrl+I` import, `Ctrl+E` export everything, `Ctrl+R` run the agent,
`Ctrl+G` get results from the web, `Ctrl+1 ... Ctrl+8` pages, `Ctrl+C` copies the selected table rows.

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
- A bond you **rejected** is not pulled back in by approving its siblings, and *Undo approval*
  only removes the rows you select.
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
   ALL YOUR BONDS --(agent compares)--> PENDING WINS --(you approve)--> WIN LIST (a record per win)
   (they stay in play)                  (temporary)      reject -> no record, bond unaffected
```

- A bond matches when it carries a winning number and has the draw's price (a draw saved with
  *Any denomination* matches every price). **A bond that has already won still matches** - it stays
  in every later draw. Re-running the agent never creates duplicates, and matches you
  rejected stay rejected (restore them from the *Rejected* view).
- The agent runs **automatically** at start-up, after bonds are added / imported and after a draw
  is saved. Untick *Run automatically* on the Pending Wins page to run it only by hand.
- **Approval re-checks each match.** If the bond was edited or its price changed after the scan, it
  is not approved and you are told why. Rows in amber are flagged (bond bought *after* the draw
  date) - check them before approving.
- Approving writes a permanent **snapshot** (copy name, 1st bond number, position, copy size, prize),
  so the report is still correct if the bond or copy is edited or deleted later.
- *Undo approval* removes a win that was approved by mistake. The bond itself is untouched; the
  match goes to the *Rejected* view of Pending Wins (restore it from there to review it again).

### A bond that wins more than once (different place or time)

Winning does not take a bond out of play, because the same bond can win again in a later draw.
Every win is its own row in the Win List - one per (bond, draw):

| Draw date | Location | Bond | Copy / 1st bond / position | Win no. | Status | Feedback |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-10-01 | Lahore | 100056 | Copy 1 / 100001 / 56 of 100 | 1 of 2 | Paid | cash received, slip 77 |
| 2026-11-01 | Karachi | 100056 | Copy 1 / 100001 / 56 of 100 | 2 of 2 | Claim submitted | at HBL Mall Road, ref 4411 |

- **Location** starts as the *location of the draw* (set in Draw Results) and can be changed per
  win, for example to the branch where you claim the prize. Suggestions come from places you used.
- **Status**: *Not claimed yet* (every new win starts here), *Claim submitted*, *Paid*, *Problem*.
  Only *Paid* counts as finished; the dashboard shows how many wins are not paid yet.
- **Feedback** is free text: what the bank said, a reference number, the date you handed the bond in.
- A bond can win only once per draw. Each of the bonds holding a shared number has its own row,
  status and feedback (they are claimed separately).
- **Status / location...** works on one win or on several at once: a field that differs between the
  selected wins starts empty, and only what you change is written.
- Pending Wins shows **Won before** so you can see a repeat winner before approving it, and
  *My Bonds* has a **Times won** column and a filter for bonds that have won.

### Location (optional)

Every bond and every copy can have a **location** - where it is kept ("Home safe", "Bank locker",
"Office drawer"). It is never required.

- **Add bonds**: one *Location (optional)* box for everything you add, plus a *Location* column in
  the copies table so each copy can have its own (it wins over the common one). *Generate copies...*
  can give all generated copies a place.
- **Import**: a *Location* column in the file is read; *Location for bonds without one* in the
  dialog fills the empty cells. (`sample_data/bonds_with_location.csv` shows it.)
- **Edit bond** and **Edit copy** change it. *Edit copy* can also set the place on every bond of the
  copy that you still hold. A copy shows a location when it was set on the copy or when all of its
  bonds share one.
- **Where it shows**: My Bonds, Copies, copy contents, the Win List and Pending Wins (*Bond kept
  at*), reports, and every export. A win keeps a snapshot of where its bond was kept.
- Do not confuse it with the **draw / claim location** (where the draw was held, or where the prize
  is claimed): that is the separate *Location* of a draw and of a win.

### Sales - bonds you sold

Use **Sell selected...** on My Bonds, **Sell copy...** on Copies, **Record a sale...** on Sales or
the Dashboard. In the dialog you give the **date**, **who bought them**, their **contact**, the
**location** of the sale and a note, then choose the bonds: take the ones you selected, type
numbers (`100090-100099, 555001`), or pick a whole copy. If a number is held in several copies the
program never guesses - it tells you and you choose the copy (or the price). The price is either the
**face value**, **the same amount for each bond**, or **one total for all of them** (shared out by
face value in whole rupees, adding up exactly to the total you typed).

What a sale changes - all in one step, and shown immediately everywhere:

- The bonds are marked **sold**. They stay in their copy at their position (so the book still looks
  like the book), but they are **not yours any more**: *My Bonds* shows them only under *Bonds I
  sold*, the copy table counts them as **Sold** instead of **Held**, the dashboard counts only what
  you hold (and shows **Sold so far**), and the exports mark them *Held / Sold*.
- **Who owns a bond on a given day.** A sold bond takes part in the draws held **before the sale
  date** - a win you earned while you owned it stays yours and is still approved, reported and
  listed (the Win List shows *Bond sold ... to ...*). From the **sale date on** (the day of the sale
  included) it belongs to the buyer: the win-checking agent ignores it, a possible win from such a
  draw is taken off Pending Wins when you record the sale, and *Approve* refuses it.
- A sale keeps a **snapshot** of every bond (number, price, copy, 1st bond of the copy, position, the
  place it was kept), so it stays readable even if the bond or copy is edited or deleted later.
  A sold bond cannot be edited until the sale is undone.
- **Take bonds back** (*Sale details*) or **Undo sale**: the bonds are yours again, take part in
  every draw (including those held while they were sold), and the agent runs again. A sale left with
  no bonds is removed. Changing the date of a sale moves the date from which the bonds belong to
  the buyer.

### Getting draw results from the web

*Draw Results -> Get results from the web...* (or *Agent -> Get draw results from the web*). The
program tries, **in this order**, until one works - and a log tab (*What was tried*) shows every
attempt and why it failed:

1. the **official National Savings site** (savings.gov.pk): its JSON API first. At the time of
   writing the site answers "401 - only authenticated users" to that API, so this step is tried,
   noted in the log and skipped;
2. the official **list page** of that price, then the draw's **`.txt`** file, then its **`.pdf`**;
3. **prizebond.net**: its list of draws and the draw's result page (it has no API).

Pick the **source** (official first then prizebond.net / official only / prizebond.net only) and the
**prices** to look for, press **Look for draws**, tick the draws you want and press **Read selected
draws**. Each draw shows what was read (prize tiers, amounts, number counts, warnings). Nothing is
saved until you press **Save selected draws and check my bonds**; then the win-checking agent lists
possible wins on *Pending Wins* for your approval, exactly as for numbers you typed in.

- **Check against a second site**: reads each draw from two sites and compares the numbers; they
  either agree ("confirmed by prizebond.net") or the differences are listed as a warning.
- **Warnings** (an incomplete list, a date the sites disagree about, a prize-count mismatch) are
  shown, and you are asked before such a draw is saved.
- **Paste a link** to a result (an official `.txt` / `.pdf`, or a prizebond.net result page) when
  the automatic search cannot find it. If the file carries no date, the date box next to the link
  is used.
- **Both ways stay available**: every draw is marked **Typed in** or **Fetched: <site>**, and you can
  keep typing results in by hand or importing files. A draw that is already recorded is topped up,
  never duplicated.
- **Automatic**: tick *Look for new draws by myself when the program starts*. Then, at most once a
  day, in the background (the window never waits), the program fetches the newest draws it does not
  have yet **for the prices you hold**, ignoring draws from before you owned any bond. Only results
  that look complete (a date, exactly one first prize, no warnings) are saved on their own; anything
  odd is left for you to review in the dialog. **Agent -> Look for new draws online now** does the
  same check immediately. Nothing is ever approved automatically.
- The program reads public pages politely (it names itself, waits between retries, never retries a
  refusal). If a site changes its layout or needs a login, that step fails and the next one is
  used; it never guesses numbers.

### Checking thousands of numbers (local API)

The checker behind the agent is also available on its own:

- **In the window**: *Agent -> Check a list of numbers...* - paste any amount of numbers or ranges
  (`200000-209999` is 10,000 numbers), optionally a price, and see which won; or check every bond
  you hold without queueing anything.
- **As an API** (needs `pip install -r requirements-api.txt`):

```bash
python main.py --serve                      # http://127.0.0.1:8765  (docs at /docs)
python main.py --serve --db my.db --port 9000
python main.py --serve --host 0.0.0.0 --token SECRET    # other computers: a token is required
```

`POST /check` takes the numbers in the **body** (so there is no URL length limit):

```bash
curl -X POST http://127.0.0.1:8765/check -H "Content-Type: application/json" -d \
  '{"denomination": 750, "bonds": ["100056", 777777, {"number": "123456", "ref": "Copy 2 #4"}]}'
```

```json
{"checked": 3, "winners": 2, "hits": 2, "draws_searched": 1, "winning_numbers_searched": 4,
 "elapsed_ms": 0.04,
 "wins": [{"number": "100056", "denomination": 750, "ref": null, "draw_id": 1,
           "draw_date": "2026-10-01", "draw_label": "Draw #98 (demo)", "location": "Lahore",
           "prize_label": "1st Prize", "prize_amount": 1500000}, "..."],
 "invalid": []}
```

The body is a Pydantic model: `bonds` is a list of 1 to **100,000** items, each a bare number
(`"100056"` or `100056`) or an object (`number`, optional `denomination` and `ref`); `denomination`
is the default price; `draw_ids` / `since` limit the draws. Unreadable numbers come back in
`invalid` and the rest is still checked. `POST /check/my-bonds` checks every bond in the data file
(sold bonds only for draws before their sale date), `GET /draws` lists the draws, `GET /health`
says it is running. The server **only reads** the data file (opened read-only), notices new draws
without a restart, and listens on `127.0.0.1` only unless you pass `--host` **and** `--token`
(`Authorization: Bearer <token>`). Measured here: 10,000 bonds matched in about 10 ms; a complete
`POST` of 10,000 bonds over real HTTP took about 60 ms (see `tests/test_api.py`).

### Which draws count for a bond, colours and the PIN

* **Bought after the draw.** A bond whose date of purchase is later than the draw date is not
  checked for that draw (a bond with no purchase date is always checked).
* **Last prize taken on.** Edit a bond and fill in the day you last took a prize for it. Draws held
  on or before that day are skipped for it; newer draws are checked. Leave it empty to check all.
  The bond list has a column for it. Changing either date removes waiting matches that no longer
  apply, and the local API follows the same two rules.
* **Colours.** Rows of bonds and copies that have already won are green. *Highlight* gives the
  selected rows a colour of your choice (ready colours, any colour, or remove). A colour on a copy
  also shows on its bonds. Order: sold (grey), your colour, win waiting (amber), already won (green).
* **PIN / password** (File menu). With a PIN set, the program asks for it before anything is edited
  or deleted, and before bonds are added or imported, wins are approved / rejected / restored and rows are
  highlighted: bonds, copies, draws and winning numbers, sales, win details. Only a salted hash is
  stored. Three wrong PINs in a row lock the question for 30 seconds. It protects the screens, it
  does not encrypt the data file. Forgot it: `python main.py --reset-pin` removes it.

### Win report

Each winning number shows draw, prize and, when several bonds hold it, a line such as
*"2 of your bonds hold this number, so all 2 win"* followed by one block per bond. A bond block
also states the location, the claim status, your feedback note and - for a repeat winner - which
of its wins this is:

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
    Location                     : Lahore
    Status                       : Claim submitted
    Feedback                     : handed in at the bank counter
    This bond has won            : 2nd of 2 wins
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
**Copy** (*Book, Batch, Set*), **Position** (*Pos, Place, Seq*), **Location** (*Kept at, Storage,
Site*). Day-first dates such as `10/01/2025`
are understood, as are ISO dates. Ranges such as `100001-100050` work inside a cell.

In the import dialog you choose how copies are made: **Automatic** (Copy column / headings / one
copy per sheet or file), **One copy for the whole file**, **Split into copies of N bonds**, or **No
copies (loose bonds)**. If the file has no price, pick one (it is required). A preview shows every
bond with the copy and position it will get; the import is all-or-nothing.

### Export

Every table has an **Export...** button that writes exactly what is shown (current search, filter
and sort order) to `.xlsx` or `.csv`. **File -> Export everything** writes one Excel workbook (all
bonds, bonds per price, copies, **sales**, **sold bonds**, pending wins, win list, draws, winning
numbers, activity log) or one CSV file per list. Bonds and copies carry their **Location**,
*Held / Sold*, *Sold on* and *Sold to*; draws say whether they were typed in or fetched. The Win List export has the location, status, feedback, win no.
and how often the bond won. Excel files keep bond numbers as text, so leading zeros stay. CSV
files use UTF-8 with a BOM (Excel reads them with the right encoding) and also contain the zeros, but Excel may hide them
when it opens a CSV - use the Excel export if that matters.

---

## 4. Project layout

```
prize_bond_manager/
|-- main.py                  start here (python main.py [--demo] [--db FILE] [--serve])
|-- requirements.txt         PyQt6, pandas, openpyxl, python-docx, pypdf
|-- requirements-api.txt     + fastapi, uvicorn, pydantic (only for --serve)
|-- requirements-dev.txt     + pytest, httpx, reportlab
|-- pytest.ini
|-- README.md
|-- sample_data/             example CSV / Excel / Word files + winning numbers
|-- tools/make_sample_data.py   regenerates sample_data/
|-- app/
|   |-- config.py            constants (price list, 6-digit numbers, limits, data path)
|   |-- models.py            small result objects (AddResult, ScanResult, ApprovalResult)
|   |-- demo.py              demo data used by --demo
|   |-- db/                  DATA LAYER - SQLite only, no UI
|   |   |-- core.py          schema (v3) + automatic upgrade, transactions, settings, log, backup
|   |   |-- lock.py          the lock that keeps two windows off one data file
|   |   |-- bonds_repo.py    bonds and copies (add, append, edit, delete, positions)
|   |   |-- draws_repo.py    draws and winning numbers
|   |   |-- sales_repo.py    sales: record, edit, take bonds back, undo
|   |   `-- wins_repo.py     agent scan, pending list, approve / reject, win list, dashboard stats
|   |-- online/              FETCHER - no UI: sources, parsers, fallback chain, saving, auto check
|   |   |-- http.py          small polite HTTP client (replaceable transport for tests)
|   |   |-- parse.py         readers for the official .txt / .pdf, prizebond.net pages, list pages
|   |   |-- sources.py       OfficialSource (API, page, txt, pdf), PrizeBondNetSource
|   |   |-- fetcher.py       ResultFetcher: list, read, cross-check, read a pasted link
|   |   `-- store.py         save a fetched draw; plan / fetch / apply of the automatic check
|   |-- api/                 BULK CHECKER - checker.py (index + matching), schemas.py (Pydantic),
|   |                        server.py (FastAPI: /check, /check/my-bonds, /draws, /health)
|   |-- processing/          LOGIC - no UI, no SQL strings except through app.db
|   |   |-- numbers.py       bond-number parsing (single, ranges, steps, lists)
|   |   |-- parsers.py       read csv / xlsx / docx / txt into plain tables
|   |   |-- importer.py      understand columns, copies, positions; plan and commit an import
|   |   |-- agent.py         the win-checking agent + approval wrapper
|   |   |-- reports.py       win reports (text / HTML / table) grouped by winning number
|   |   |-- sales.py         pricing a sale (face / each / total, exact whole-rupee split)
|   |   `-- exporter.py      CSV / Excel writers and the "everything" workbook
|   `-- ui/                  INTERFACE - PyQt6
|       |-- main_window.py   sidebar, pages, menus
|       |-- context.py       shared state (database, agent, signals)
|       |-- actions.py       add / import / sell / export / backup actions
|       |-- background.py    run a slow job (web request) in a worker thread
|       |-- online_auto.py   the quiet start-up check and "look for new draws now"
|       |-- theme.py, widgets.py, table_model.py   look and reusable table widgets
|       |-- pages/           dashboard, bonds, copies, draws, pending, wins, sales, history
|       `-- dialogs/         add bonds, copies editor, import, edit bond / copy, win report,
|                            win details, sell / sale details, web results, check numbers
`-- tests/                   pytest: numbers, database, agent, importer, export/reports, sales,
                             location, upgrades, online fetcher (saved real pages), API, sample
                             files, headless GUI tests
```

### Data model (SQLite)

| Table | Holds |
| --- | --- |
| `copies` | name, 1st bond number (kept even if that bond is removed), size (positions), note, **location** |
| `bonds` | number (text) + numeric key, price, purchase date, copy, position, **location**, **sale_id / sold_date** (sold iff `sale_id` is set). One copy never holds the same number twice; different copies may. Bonds are never "used up" by a win |
| `draws` / `winning_numbers` | draw date, price (or any), label, **location**, **source** (Manual or the site), source url, draw number; winning numbers with prize tier and amount |
| `sales` / `sale_items` | a sale (date, buyer, contact, location, total, note) and a snapshot of each bond sold (number, price, copy, 1st bond number, position, place) |
| `pending_wins` | the agent's temporary list: one row per (bond, winning number), status `pending` / `approved` / `rejected` |
| `wins` | the final win list, one row per (bond, draw): snapshot of the copy details, **location**, **bond_location**, **claim_status**, **feedback** |
| `activity_log`, `settings` | history page; agent on/off and last-run text |

---

## 5. Tests

```bash
pip install -r requirements-dev.txt
python -m pytest            # the GUI tests run headless (Qt "offscreen" platform)
python -m pytest -s tests/test_api.py     # also prints the 10,000-bond timings
```

## 6. Troubleshooting

- **Linux:** if Qt says it cannot load the platform plugin `xcb`, install the missing library
  (Debian / Ubuntu: `sudo apt install libxcb-cursor0`).
- **"... is already open in another Prize Bond Manager window"**: close the other window (or the
  other program using the file). If the app crashed earlier, just start it again - the lock is
  released by the system, nothing needs to be deleted.
- **My data seems to be missing after I used `--db my.db`**: a bare name is now looked for next to
  `main.py`. If your file was created somewhere else (the folder you started the app from), copy it
  next to `main.py` or give the full path.
- **"This database was created by a newer version"**: the data file comes from a newer release;
  start with a different `--db` file or update the app.
- **A file will not import**: open it in the import dialog to see what was understood; the notes box
  lists unreadable cells. Password-protected Excel files cannot be read.
- **"No draws were found" when fetching**: open the *What was tried* tab - it lists every step and
  the reason (no connection, the site refused, the page layout changed). Try the other source, paste
  a link to the result file, or type the numbers in on the Draw Results page. The fetcher could not be
  tried against the live sites while it was written (they were not reachable from the build
  machine); it is tested against saved copies of the real pages, so a site that changes its layout
  is the most likely cause of a failure.
- **`--serve` says it needs extra packages**: `pip install -r requirements-api.txt`.
- **A sold bond cannot be edited**: undo the sale (Sales page) or take the bond back first.
- **Export fails**: the target file is probably open in Excel - close it and try again.
