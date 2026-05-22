# Con Edison DAC Annual Report Dashboard

Interactive web dashboard for Con Edison's Disadvantaged Communities (DAC) Annual Report.
Single-page application that visualizes 10 reporting areas (Clean Energy, EV Make-Ready,
Demand Response, DER, Strategic Capital, Outages, Mains, Leaks, Jobs, Customer Ops) with
year-over-year comparisons, equity benchmarks, and inline data ingestion.

---

## 🚀 Quick start

```bash
# Local development
git clone <repo>
cd dac-dashboard
python3 -m http.server 8000
# Open http://localhost:8000
```

The dashboard works with any static file server. No build step required — just open
`index.html` through a web server (not `file://`, because `fetch('payload.json')`
needs HTTPS or HTTP).

---

## 📁 Project structure

```
dac-dashboard/
├── index.html          # Single-page shell (96 lines)
├── app.js              # Application: router, charts, ingestion (~5,250 lines)
├── styles.css          # All styles (~5,700 lines)
├── payload.json        # Data source — all KPIs, charts, tables (~200 KB)
├── build_payload.py    # Script to regenerate payload.json from source HTMLs
├── logo/
│   ├── ConEd_Logo_completo.svg
│   └── ConEd_Logo_fondo_blanco.jpeg
└── README.md           # This file
```

**Only 4 files are required for deployment**: `index.html`, `app.js`, `styles.css`,
`payload.json`. The logos and the build script are dev-time only.


---

## 📊 The `payload.json` schema

All data the dashboard renders comes from `payload.json`. Top-level structure:

```json
{
  "meta": {
    "title": "Con Edison DAC Annual Report",
    "years": ["2025", "2024", "2023"],     // dropdown order (newest first)
    "current_year": "2024",                 // default selected year
    "baseline_options": [35, 40],           // toggle: 35% Climate Act vs 40% Justice40
    "default_baseline": 35
  },
  "sections": {
    "A": { "name": "Clean Energy", "short_name": "...", "full_name": "...", "blurb": "..." },
    "B": { ... },
    ...
  },
  "tables": {
    "A1": { "id", "section", "data", "title_by_year", "mapping", ... },
    "B2": { ... "schema_by_year": { "2024": [...], "2025": [...] } },  // year-versioned
    ...
  },
  "kpis": {
    "reported":   [{ "id", "label", "section", "format", "values": { "2024": {...}, "2023": {...} } }, ...],
    "analytical": [{ "id", "label", "composite": true, "values": {...} }, ...]
  },
  "charts": {
    "A1_programs":   { "values": { "2024": [...], "2023": [...] } },
    "B2_plugs":      { "values": { "2024": {...}, "2025": {...} } },
    ...
  }
}
```

### Table shapes — two flavors

**Legacy shape** (most tables, e.g. A1): the first row of each `data[year]` is the
header.

```json
"A1": {
  "data": {
    "2024": [
      ["Program Name", "Total Funding", "DAC Funding"],   // ← header row
      ["HEAT Pump Rebate", 1250000, 650000],
      ["Income-eligible", 875000, 875000]
    ]
  }
}
```

**Schema-by-year shape** (B2, G1): headers live in `schema_by_year`; `data` is
body-only. Use this when columns differ between years.

```json
"B2": {
  "schema_by_year": {
    "2024": ["Category", "L2 Plugs", "DCFC Plugs", "Total Plugs"],
    "2025": ["Category", "L2 Plugs", "DCFC Plugs", "Micromobility Power Cabinets", "Total Plugs"]
  },
  "data": {
    "2024": [["DAC", 1732, 118, 1850], ...],
    "2025": [["DAC", null, null, null, null], ...]   // null = placeholder
  }
}
```

The dashboard detects both shapes automatically.

---

## 🔄 Updating data

Two ways to update what the dashboard shows.

### Option 1 — Via the in-app Ingestion page

Best for: ad-hoc edits, adding values for new years, fixing typos.

1. Open the dashboard → click **Data Ingestion** in the sidebar
2. Pick a section + table + year
3. Edit cells; rows labeled "Total" auto-calculate from the rows above (shown in grey)
4. Click **Save** → modal asks for your name + email → confirms
5. Changes are stored in `localStorage` and applied on top of `payload.json` at every
   page load (the merged result is what charts render)

#### Adding a new year
1. Ingestion page → **+ Add year** → enter (e.g.) `2026`
2. The year appears in the main dropdown ("year selector") immediately
3. All tables show empty placeholders for the new year, ready to be filled
4. **Remove year** is available for user-added years only (not for years baked into
   `payload.json`)

#### Storage backend
Changes are persisted via the `Storage` module, which writes to `localStorage`:

- `dac:overrides` — `{ "TableID:Year": [[...rows...]] }`
- `dac:history` — array of save events `{ ts, user, email, tableId, year, changes }`
- `dac:years` — user-added years like `["2026"]`

To migrate to a real backend (e.g. Dataverse), swap the `Storage` module's
implementation in `app.js`. The rest of the app calls `Storage.saveTable()`,
`Storage.applyOverrides()`, etc. — no other code needs to change.

#### Resetting local changes
- Per-save: **Reset** button in the editor reverts the current draft to the last save
- All overrides: in the browser console:
  ```javascript
  Dash.Storage.clearAll();
  location.reload();
  ```

### Option 2 — Rebuild `payload.json` from source

Best for: bulk updates from Excel sources, structural changes (new columns, schema
migrations).

1. Place the legacy source files in `/home/claude/work/` (see `build_payload.py`)
2. Run `python3 build_payload.py`
3. The script:
   - Extracts data from each `section_X.html` and `index.html`
   - Transforms to the unified schema
   - Applies the migrations defined in `TABLE_MIGRATIONS`
   - Validates the result
   - Writes `payload.json`
4. Replace the deployed `payload.json` with the new file

#### Adding a new year to `build_payload.py`
Edit the `YEARS` constant at the top:

```python
YEARS = ['2025', '2024', '2023']   # newest first
```

The script will pull `data_2025` / `y2025` / `*_2025` keys from the legacy HTMLs.
Years with no data are skipped automatically.

#### Adding a table migration
Edit `TABLE_MIGRATIONS`:

```python
TABLE_MIGRATIONS = {
    'G1': {
        'kind': 'schema_by_year_uniform',
        'unified_schema': ['Category', 'Feet Replaced', 'Percentage'],
        'row_label_map': [(r'within\s+dacs?', 'Feet Replaced within DAC'), ...],
        'col_map': {0: 0, 1: 2},
        'placeholder_years': ['2025'],
    },
    'B2': {
        'kind': 'schema_by_year_versioned',
        'schemas': {
            '2024': ['Category', 'L2 Plugs', 'DCFC Plugs', 'Total Plugs'],
            '2025': ['Category', 'L2 Plugs', 'DCFC Plugs', 'Micromobility Power Cabinets', 'Total Plugs'],
        },
        'placeholder_years': ['2025'],
    },
}
```

Two migration kinds are supported:

| Kind                          | Use when                                  |
|-------------------------------|-------------------------------------------|
| `schema_by_year_uniform`      | All years share the same NEW schema       |
| `schema_by_year_versioned`    | Each year has its own column list         |

---

## 🏗️ Architecture

### Single-bundle SPA
- One HTML, one JS bundle, one CSS bundle
- No build step (no webpack, no bundler, no transpiler)
- Plain ES2017+ — works in all modern browsers
- Hash routing: `#/`, `#/section/A`, `#/section/B`, ..., `#/ingest`

### `window.Dash` public API
For debugging from the browser console:

```javascript
Dash.payload                       // current merged payload
Dash.year                          // selected year
Dash.Storage.getAddedYears()       // ['2026']
Dash.Storage.getAllHistory()       // all saves, newest first
Dash.Storage.listOverrides()       // table:year keys
Dash.Storage.clearAll()            // nuke everything
```

### Data flow

```
   payload.json (baseline)
            │
            ▼
   Storage.applyAddedYears()    ← adds user-added years to meta.years
            │
            ▼
   Storage.applyOverrides()     ← merges edited tables on top
            │
            ▼
   state.payload (in memory)
            │
            ▼
   Renderers (sections, exec summary, ingestion)
```

### File-level layout of `app.js`

```
Lines 1-200      Header, state declaration, Storage module
Lines 200-800    Formatters, year helpers, chart primitives
Lines 800-1500   Executive Summary (KPIs, equity charts, header cards)
Lines 1500-3100  Sections A-J renderers
Lines 3100-4300  Section interactions (tooltips, toggles, modals)
Lines 4300-5250  Ingestion page (editor, storage, history)
```

---

## 🧪 Manual test plan

A non-exhaustive list of checks before deploying:

1. **Year switching**: Change the year dropdown across 2025/2024/2023 — all sections
   should update; sections with no data for the selected year show "no data" panes.
2. **Section A**: rank toggle ($/MMBtu), quadrant metric toggle, "How to read this
   chart" modal, tooltips on bars and quadrant dots
3. **Section B**: funding bars, tornado chart, hover tooltips
4. **Section J**: dumbbell, unpaid blocks, DPA growth (only renders with prior year)
5. **Source tables**: tab switching, "Compare with previous" toggle
6. **Ingestion**:
   - Edit a cell, watch the auto-calc total update
   - Save with name + email → check history strip
   - Reload page → edits persist
   - Click Reset → reverts to last save
   - Add year 2026 → appears in main dropdown
   - Remove year → confirms, then disappears everywhere
7. **B2 / G1**: year-versioned columns render correctly per year

---

## ⚙️ Browser support

Tested on:
- Chrome / Edge (Chromium-based) 120+
- Firefox 120+
- Safari 17+

The dashboard uses:
- ES2017+ (`async/await`, destructuring, template literals)
- CSS Grid + Flexbox
- `<canvas>` for the Section E arc chart
- `localStorage` for persistence

No polyfills required for these browsers.

---

## 🛣️ Future work

- **Dataverse integration**: replace the `Storage` module with one that POSTs to
  Dataverse. All app code calls remain identical.
- **Authentication**: today, "who edited" is captured per-save via a name+email
  prompt. Plug this into Azure AD / Entra ID when available.
- **Export PDF**: the print button uses `window.print()` — consider a richer
  export (e.g. server-rendered PDF) if reports need to be archived.
- **Excel ingestion**: drag-and-drop an Excel sheet → auto-map columns → load into
  `payload.json` without going through `build_payload.py`.

---

## 📝 License

Internal Con Edison project. Not for redistribution.

---

## 🙋 Contact

Issues, questions, or feature requests: open an issue in this repo or contact the
maintainer.
