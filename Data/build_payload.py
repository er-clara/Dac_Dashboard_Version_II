"""
build_payload.py — Build payload.json from the legacy source HTMLs

Pipeline:
  1. Read each section_X.html and index.html (the legacy single-page docs)
  2. Extract their embedded <script id="payload"> JSON
  3. Transform to the unified payload schema
  4. Apply per-table MIGRATIONS (schema_by_year, new columns, etc.)
  5. Validate and write payload.json

Supported schema features:
  - data[year]  — body rows keyed by year (string)
  - schema_by_year[year]  — column headers per year (use this when a table's
    columns vary by year, e.g. B2 adding "Micromobility Power Cabinets" in 2025)
  - title_by_year[year]  — table caption per year
  - mapping.{status, notes}  — historical comparability notes

Adding a new year (e.g. 2026):
  - Add it to YEARS at top of file
  - Re-run; tables without data for 2026 will simply not have a 2026 entry
    (the dashboard handles this as "no data")

Adding a table migration:
  - Add an entry to TABLE_MIGRATIONS describing the new shape
  - Re-run; migration is applied AFTER the basic transform

This script is idempotent: re-running with already-migrated payload.json
input will produce the same output.
"""

import json
import re
from pathlib import Path

# ============================================================
# CONFIGURATION
# ============================================================

WORK = Path('/home/claude/work')

# Years to extract (newest first). Add new years here as they come in.
# The dashboard supports any year set; this just controls what build_payload
# pulls from the legacy HTMLs.
YEARS = ['2024', '2023']

# Years that should appear in the dropdown even if no data exists yet.
# These are placeholders that the data team can fill in via the Ingestion page.
PLACEHOLDER_YEARS = ['2025']

SECTION_META = {
    'A': {'name': 'Clean Energy', 'short_name': 'Clean Energy', 'full_name': 'Clean Energy Spending', 'invert_metric': False},
    'B': {'name': 'EV Make-Ready', 'short_name': 'EV Ready', 'full_name': 'EV Make-Ready Program', 'invert_metric': False},
    'C': {'name': 'Demand Response', 'short_name': 'Demand Resp', 'full_name': 'Demand Response', 'invert_metric': False},
    'D': {'name': 'DER', 'short_name': 'DER', 'full_name': 'Distributed Energy Resources', 'invert_metric': False},
    'E': {'name': 'Strategic Cap', 'short_name': 'Strategic', 'full_name': 'Strategic Capital Investments', 'invert_metric': False},
    'F': {'name': 'Outages', 'short_name': 'Outages', 'full_name': 'Customer Outages', 'invert_metric': True},
    'G': {'name': 'Main Replace', 'short_name': 'Mains', 'full_name': 'Main Replacement Program', 'invert_metric': False},
    'H': {'name': 'Leak Repairs', 'short_name': 'Leaks', 'full_name': 'Leak Repairs', 'invert_metric': False},
    'I': {'name': 'Jobs', 'short_name': 'Jobs', 'full_name': 'Clean Energy Jobs', 'invert_metric': False},
    'J': {'name': 'Customer Ops', 'short_name': 'Cust Ops', 'full_name': 'Customer Operations', 'invert_metric': False},
}

SHORT_TITLES = {
    'A1': 'Incentive $', 'A2': 'Energy Savings', 'A3': 'Participants', 'A4': 'DAC Participants',
    'A5': 'Commercial Install', 'A6': 'Multifamily Install', 'A7': 'Multisector Install',
    'A8': 'Residential Install', 'A9': 'Comparison Summary', 'A10': 'Install Compare',
    'B1': 'Funding Spent', 'B2': 'Plugs Completed',
    'C1': 'DR Programs', 'C2': 'All Customers', 'C3': 'DAC Customers', 'C4': 'Low-Income', 'C5': 'Total Program',
    'D1': 'Compensation Types', 'D2': 'DER Projects', 'D3': 'CDG & RC', 'D4': 'Net Metering',
    'E1': 'Capital Investments',
    'F1': 'Key Terms', 'F2': 'System Outages', 'F3': 'Interruption Rate', 'F4': 'Non-Network',
    'F5': 'Network', 'F6': 'Mixed Areas', 'F7': 'DAC Outages', 'F8': 'Customers by Type', 'F9': 'Interrupted',
    'G1': 'Pipe Replaced', 'G2': 'Bronx Replaced', 'G3': 'Bronx Abandoned',
    'G4': 'Manhattan Replaced', 'G5': 'Manhattan Abandoned', 'G6': 'Queens Replaced', 'G7': 'Queens Abandoned',
    'G8': 'Westchester Replaced', 'G9': 'Westchester Abandoned', 'G10': 'Emissions',
    'H1': 'Leaks Repaired',
    'I1': 'Year Totals',
    'J1': 'Electric Usage', 'J2': 'Gas Usage', 'J3': '60-90 Days Overdue', 'J4': '90+ Days Overdue',
    'J5': 'Disconnects', 'J6': 'DPAs', 'J7': 'EAP Enrolled', 'J8': 'EAP Spending', 'J9': 'Residential Total',
}

# ============================================================
# TABLE MIGRATIONS
# ============================================================
# Each entry transforms a table's shape after the basic transform.
#
# Migration types:
#   - 'schema_by_year_uniform': the table has the SAME schema across all years,
#     but the schema has changed vs the legacy data. Move the header row out of
#     data[] and into schema_by_year{}, optionally renaming labels/columns.
#   - 'schema_by_year_versioned': the schema VARIES by year. Each year gets its
#     own column list, and data is reshaped to fit (missing values become None).
#
# To add a new migration, append an entry to TABLE_MIGRATIONS. See B2 and G1
# below for examples.
# ============================================================

TABLE_MIGRATIONS = {

    # G1 — uniform schema, columns expanded from 2 to 3
    # 2023 had different row labels; we unify to the 2024 wording.
    'G1': {
        'kind': 'schema_by_year_uniform',
        'unified_schema': ['Category', 'Feet Replaced', 'Percentage'],
        # Row-label mapping: regex pattern → canonical label
        'row_label_map': [
            (r'within\s+(dac|dacs)', 'Feet Replaced within DAC'),
            (r'not\s+in\s+(a\s+dac|dacs)', 'Feet Replaced not in a DAC'),
        ],
        # For columns that existed in the legacy schema, map old col index → new col index
        # Legacy: ['Category', 'Percentage'] (indices 0, 1)
        # New:    ['Category', 'Feet Replaced', 'Percentage'] (indices 0, 1, 2)
        # So old col 1 (Percentage) maps to new col 2.
        'col_map': {0: 0, 1: 2},
        # Add placeholder year(s) with all-null values for any rows
        'placeholder_years': PLACEHOLDER_YEARS,
    },

    # B2 — versioned schema (2025 adds a new column between existing ones)
    'B2': {
        'kind': 'schema_by_year_versioned',
        'schemas': {
            # Years with the legacy 4-column shape
            '2023': ['Category', 'L2 Plugs', 'DCFC Plugs', 'Total Plugs'],
            '2024': ['Category', 'L2 Plugs', 'DCFC Plugs', 'Total Plugs'],
            # 2025 adds Micromobility Power Cabinets between DCFC and Total
            '2025': ['Category', 'L2 Plugs', 'DCFC Plugs', 'Micromobility Power Cabinets', 'Total Plugs'],
        },
        # For years that exist in source data but with a different schema,
        # map each legacy column index → new column index for that year.
        # (If a year's schema matches the source, no mapping needed.)
        'col_maps': {
            # 2025 isn't in legacy source, so no col_map needed for it.
            # The placeholder year gets all-null rows.
        },
        'placeholder_years': PLACEHOLDER_YEARS,
        # Row labels in the legacy data: DAC / Non-DAC / Total. Keep as-is.
    },
}


# ============================================================
# CORE TRANSFORMS (legacy HTML → unified shape)
# ============================================================

def transform_table(t):
    """Transform a table from the legacy embedded shape to the unified shape."""
    new_t = {
        'id': t['id'],
        'section': t['section'],
        'number': t.get('number'),
        'short_title': SHORT_TITLES.get(t['id'], ''),
    }

    # data["2024"], data["2023"] — omit empty years
    data = {}
    for y in YEARS:
        rows = t.get(f'data_{y}', [])
        if rows and len(rows) > 0:
            data[y] = rows
    new_t['data'] = data

    # title_by_year — omit empty
    titles = {}
    for y in YEARS:
        title = t.get(f'title_{y}', '').strip()
        if title:
            titles[y] = title
    new_t['title_by_year'] = titles

    # mapping
    mapping = dict(t.get('mapping', {}))
    if mapping.get('status') == 'NEW IN 2024':
        mapping['status'] = 'NEW'
    if not mapping.get('status'):
        mapping['status'] = 'NEW' if len(data) == 1 else 'SAME'
    mapping.pop('table_2023', None)
    mapping.pop('table_2024', None)
    new_t['mapping'] = mapping

    if 'header_levels' in t:
        new_t['header_levels'] = t['header_levels']

    return new_t


def transform_reported_kpi(k):
    new_k = {
        'id': k['id'],
        'label': k['label'],
        'section': k.get('section'),
        'format': k.get('format'),
        'unit': k.get('unit'),
        'primary_metric': k.get('primary_metric'),
        'narrative': k.get('narrative', ''),
    }
    values = {}
    for y in YEARS:
        v = k.get(f'y{y}')
        if v is not None:
            values[y] = dict(v)
    new_k['values'] = values
    if 'caveat_2023' in k and '2023' in new_k['values']:
        new_k['values']['2023']['caveat'] = k['caveat_2023']
    return new_k


def transform_analytical_kpi(k):
    section = k.get('section')
    new_k = {
        'id': k['id'],
        'label': k['label'],
        'format': k.get('format'),
        'narrative': k.get('narrative', ''),
        'source_calc': k.get('source_calc', ''),
    }
    if section == 'MULTI':
        new_k['composite'] = True
    else:
        new_k['section'] = section
    if k.get('lower_is_better'):
        new_k['lower_is_better'] = True
    values = {}
    for y in YEARS:
        v = k.get(f'y{y}')
        if v is not None and 'value' in v and v['value'] is not None:
            values[y] = {'value': v['value']}
    new_k['values'] = values
    if 'caveat_2023' in k and '2023' in new_k['values']:
        new_k['values']['2023']['caveat'] = k['caveat_2023']
    return new_k


def transform_charts(charts_raw):
    """Transform chart series with _YYYY suffix into values[year] shape."""
    new_charts = {}
    for key, val in charts_raw.items():
        if len(key) >= 5 and key[-5] == '_' and key[-4:].isdigit():
            year = key[-4:]
            base = key[:-5]
            if base not in new_charts:
                new_charts[base] = {'values': {}}
            new_charts[base]['values'][year] = val
        else:
            if isinstance(val, dict):
                normalized = {}
                for k, v in val.items():
                    if str(k).isdigit() and len(str(k)) == 4:
                        normalized[str(k)] = v
                    else:
                        normalized[k] = v
                if all(str(k).isdigit() and len(str(k)) == 4 for k in normalized.keys()):
                    new_charts[key] = {'values': normalized}
                else:
                    new_charts[key] = val
            else:
                new_charts[key] = val
    return new_charts


# ============================================================
# TABLE MIGRATIONS (post-process)
# ============================================================

def apply_row_label_map(label, patterns):
    """Apply regex → canonical mapping. Returns the mapped label or the original."""
    if not isinstance(label, str):
        return label
    for pattern, canonical in patterns:
        if re.search(pattern, label, re.IGNORECASE):
            return canonical
    return label


def migrate_uniform_schema(table, migration):
    """
    Reshape a table with the same NEW schema across all years.
    The legacy data has different columns; we map them to the new schema.
    """
    new_schema = migration['unified_schema']
    col_map = migration.get('col_map', {})
    row_label_map = migration.get('row_label_map', [])

    schema_by_year = {}
    new_data = {}

    for year, rows in table['data'].items():
        if not rows:
            continue
        # First row is the legacy header; the rest is the body
        body = rows[1:] if len(rows) > 1 else []

        new_body = []
        for row in body:
            new_row = [None] * len(new_schema)
            # Label column — apply row-label remapping
            if len(row) > 0:
                new_row[0] = apply_row_label_map(row[0], row_label_map)
            # Other columns: map legacy index → new index
            for old_idx, new_idx in col_map.items():
                if old_idx > 0 and old_idx < len(row) and new_idx < len(new_schema):
                    new_row[new_idx] = row[old_idx]
            new_body.append(new_row)

        schema_by_year[year] = list(new_schema)
        new_data[year] = new_body

    # Add placeholder years if requested
    placeholder_years = migration.get('placeholder_years', [])
    for py in placeholder_years:
        if py in new_data:
            continue
        # Use the row labels from the most recent existing year as a template
        if new_data:
            template_year = sorted(new_data.keys(), reverse=True)[0]
            labels = [row[0] for row in new_data[template_year]]
            schema_by_year[py] = list(new_schema)
            new_data[py] = [[label] + [None] * (len(new_schema) - 1) for label in labels]

    table['schema_by_year'] = schema_by_year
    table['data'] = new_data


def migrate_versioned_schema(table, migration):
    """
    Apply a per-year schema. Each year may have a different column list.
    Existing data is reshaped via col_maps[year] if provided; missing years get
    null-filled placeholders.
    """
    schemas = migration['schemas']
    col_maps = migration.get('col_maps', {})

    schema_by_year = {}
    new_data = {}

    for year, rows in table['data'].items():
        if not rows or year not in schemas:
            continue
        new_schema = schemas[year]
        body = rows[1:] if len(rows) > 1 else []  # strip legacy header
        col_map = col_maps.get(year)

        new_body = []
        for row in body:
            if col_map:
                new_row = [None] * len(new_schema)
                for old_idx, new_idx in col_map.items():
                    if old_idx < len(row) and new_idx < len(new_schema):
                        new_row[new_idx] = row[old_idx]
                new_body.append(new_row)
            else:
                # No column remap needed — assume schema matches the legacy header
                new_body.append(row[:len(new_schema)])

        schema_by_year[year] = list(new_schema)
        new_data[year] = new_body

    # Placeholder years
    placeholder_years = migration.get('placeholder_years', [])
    for py in placeholder_years:
        if py in new_data:
            continue
        if py not in schemas:
            continue
        new_schema = schemas[py]
        # Template from existing year
        if new_data:
            template_year = sorted(new_data.keys(), reverse=True)[0]
            labels = [row[0] for row in new_data[template_year]]
            new_data[py] = [[label] + [None] * (len(new_schema) - 1) for label in labels]
        else:
            new_data[py] = []
        schema_by_year[py] = list(new_schema)

    table['schema_by_year'] = schema_by_year
    table['data'] = new_data


def apply_table_migrations(payload):
    """Apply all migrations defined in TABLE_MIGRATIONS."""
    for table_id, migration in TABLE_MIGRATIONS.items():
        if table_id not in payload['tables']:
            print(f'   ⚠️ Migration for {table_id}: table not found, skipping')
            continue
        table = payload['tables'][table_id]
        kind = migration['kind']
        if kind == 'schema_by_year_uniform':
            migrate_uniform_schema(table, migration)
            print(f'   ✅ {table_id} migrated (uniform schema, {len(table["schema_by_year"])} years)')
        elif kind == 'schema_by_year_versioned':
            migrate_versioned_schema(table, migration)
            print(f'   ✅ {table_id} migrated (versioned schema, {len(table["schema_by_year"])} years)')
        else:
            print(f'   ⚠️ Unknown migration kind for {table_id}: {kind}')


# ============================================================
# BUILD
# ============================================================

print('🔨 Building payload.json...')

payload = {
    'meta': {
        'title': 'Con Edison DAC Annual Report',
        'years': YEARS,
        'current_year': YEARS[0],
        'baseline_options': [35, 40],
        'default_baseline': 35,
    },
    'sections': {},
    'tables': {},
    'kpis': {'reported': [], 'analytical': []},
    'charts': {},
}

# Sections
print('\n📂 Sections...')
for letter in 'ABCDEFGHIJ':
    p = json.load(open(WORK / f'section_{letter}_payload.json'))
    payload['sections'][letter] = {
        **SECTION_META[letter],
        'blurb': p.get('blurb', ''),
    }

# Tables
print('\n📊 Tables...')
for letter in 'ABCDEFGHIJ':
    p = json.load(open(WORK / f'section_{letter}_payload.json'))
    for t in p.get('tables', []):
        new_t = transform_table(t)
        payload['tables'][new_t['id']] = new_t
print(f'   Total: {len(payload["tables"])} tables')

# KPIs
print('\n📈 KPIs...')
idx = json.load(open(WORK / 'index_payload.json'))
for k in idx.get('kpis', []):
    payload['kpis']['reported'].append(transform_reported_kpi(k))
for k in idx.get('analytical', []):
    payload['kpis']['analytical'].append(transform_analytical_kpi(k))
print(f'   Reported: {len(payload["kpis"]["reported"])}')
print(f'   Analytical: {len(payload["kpis"]["analytical"])}')

# Charts
print('\n📉 Charts...')
all_charts_raw = {}
all_charts_raw.update(idx.get('charts', {}))
for letter in 'ABCDEFGHIJ':
    p = json.load(open(WORK / f'section_{letter}_payload.json'))
    for k, v in p.get('charts', {}).items():
        if k not in all_charts_raw:
            all_charts_raw[k] = v
payload['charts'] = transform_charts(all_charts_raw)
print(f'   Unique series: {len(payload["charts"])}')

# Apply migrations
print('\n🔧 Applying table migrations...')
apply_table_migrations(payload)

# ============================================================
# WRITE
# ============================================================

out_path = WORK / 'payload.json'
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)

size_kb = out_path.stat().st_size / 1024
print(f'\n✅ Written: {out_path} ({size_kb:.1f} KB)')

# ============================================================
# VALIDATIONS
# ============================================================
print('\n🔍 Validations:')

assert set(payload.keys()) == {'meta', 'sections', 'tables', 'kpis', 'charts'}
print('   ✅ Top-level keys OK')

assert len(payload['sections']) == 10
print('   ✅ 10 sections')

empty_tables = [tid for tid, t in payload['tables'].items() if not t['data']]
if empty_tables:
    print(f'   ⚠️ Tables with no data: {empty_tables}')
else:
    print('   ✅ All tables have data in at least one year')

# Tables with schema_by_year
migrated = [tid for tid, t in payload['tables'].items() if 'schema_by_year' in t]
print(f'   ℹ️ Tables with schema_by_year: {migrated}')

# No leftover old keys
def has_old_keys(obj):
    if isinstance(obj, dict):
        for k in obj.keys():
            if k in ('y2024', 'y2023', 'y2022', 'data_2024', 'data_2023', 'title_2024', 'title_2023', 'caveat_2023'):
                return k
        for v in obj.values():
            found = has_old_keys(v)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = has_old_keys(item)
            if found:
                return found
    return None

stale = has_old_keys(payload)
if stale:
    print(f'   ⚠️ Stale old key found: {stale}')
else:
    print('   ✅ No legacy keys left')

print('\n🎉 Done')