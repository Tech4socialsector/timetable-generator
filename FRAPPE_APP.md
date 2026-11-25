# Timetable Generator – Frappe app

This repository holds two things that share one scheduling engine:

| Part | Where | What it does |
|---|---|---|
| **Command-line generator** (original) | `main.py`, `src/` | Reads a planning workbook and writes a timetable workbook |
| **Frappe app** (web UI) | `timetable_app/`, `frontend/` | Data management, readiness checks, background generation, review, manual moves, approval and Excel reports at `/timetable` |

The app does **not** copy the engine: it loads `src/domain.py` and `src/solver.py` from this
repository (`timetable_app/engine/_upstream.py`). Any change to `src/` reaches both the command line
and the web app.

## Repository layout

```
timetable-generator/
├── main.py, requirements.txt, src/      original command-line generator (unchanged)
├── pyproject.toml                       Frappe app package (installs only timetable_app)
├── package.json                         lets `bench build` build the frontend
├── frontend/                            Vue 3 + frappe-ui single-page app
└── timetable_app/
    ├── hooks.py, setup.py, www/         Frappe app wiring, roles, SPA entry
    ├── timetable_generator/doctype/     DocTypes (TT Plan, TT Section, TT Faculty, TT Room, ...)
    ├── api/                             whitelisted methods used by the UI
    ├── engine/                          adapters around src/ (no solver copy)
    │   ├── _upstream.py, domain.py, solver.py   load src/ (plus Faculty.program_ids)
    │   ├── scenario_builder.py          plan data / workbook rows -> src.domain objects
    │   ├── plan_solver.py               per-section room requirements
    │   ├── runner.py                    rule weights, cross-term fix, progress, stop
    │   ├── preflight.py, checks.py      readiness checks and timetable verification
    │   └── workbook.py                  .xlsx read/write
    └── tests/                           engine, migration and integration tests
```

## Requirements

Frappe v16, Python 3.14 (bench env), Node 24+ with Yarn 1.22, MariaDB 10.6+ (11.8 recommended), Redis.
The app must be installed in editable mode (bench always does this) because it loads `src/` from the
repository. Python packages `ortools` and `pydantic` are declared in `pyproject.toml`; `main.py` additionally uses
the packages in `requirements.txt`.

## Install on a bench

`bench get-app` reads the package name (`timetable_app`) from `pyproject.toml` and renames the cloned
folder to `apps/timetable_app` itself:

```bash
cd ~/frappe-bench
bench get-app https://github.com/Tech4socialsector/timetable-generator --branch <branch>
bench --site <site> install-app timetable_app
bench build --app timetable_app
```

Already have the repository cloned somewhere else (e.g. GitHub Desktop)? Link it in:

```bash
ln -s /path/to/timetable-generator ~/frappe-bench/apps/timetable_app
cd ~/frappe-bench && uv pip install -e apps/timetable_app --python env/bin/python   # or: bench setup requirements
echo timetable_app >> sites/apps.txt   # only if not already listed
bench --site <site> install-app timetable_app   # or migrate if already installed
bench build --app timetable_app
```

Roles: **Timetable Manager** (programme office), **Timetable Approver**, **Timetable Viewer**.
Generation runs on the `long` queue, so a worker must be running (`bench start` runs one).

## Development

```bash
cd apps/timetable_app/frontend && yarn install
yarn dev      # Vite dev server, proxies to the bench
yarn build    # -> timetable_app/public/frontend and timetable_app/www/timetable.html (both git-ignored)
```

## Tests

```bash
cd ~/frappe-bench/apps/timetable_app
../../env/bin/python -m unittest timetable_app.tests.test_engine       # engine (no Frappe)
../../env/bin/python -m unittest timetable_app.tests.test_week         # configurable week (no Frappe)
../../env/bin/python -m unittest timetable_app.tests.test_migration    # repo / engine contract (no Frappe)

cd ~/frappe-bench/sites
TT_TEST_SITE=<site> ../env/bin/python -m unittest timetable_app.tests.test_integration   # app on a site
```

`test_migration` fails if the original files change unexpectedly, if the app stops using `src/`,
or if a method / argument the app calls on `src/solver.py` is renamed. The integration tests create
throw-away plans named `_TT Test …` and delete them afterwards.

## Week structure (per plan)

Each plan defines its own week on **Term setup**: teaching days (any of Mon–Sun), 1–12 time slots per
day with labels and times, and which days / slots are *regular* (used when a section or category lists no
allowed slots). New plans start with the original 6 × 6 week (regular Mon–Fri, slots 1–4), and plans on that
week run the original `src/solver.py` logic unchanged. For other weeks `engine/plan_solver.py` applies the
same rules with the plan's week (upstream hard-codes six slots per day).

Slot numbers stored in the data (allowed slots, meeting slots) are `day × slots_per_day + slot`. When the week
changes, the app rewrites them, and room / faculty availability, so they keep pointing at the same day and slot;
values on removed days or slots are dropped (the user is told how many). A plan that already has timetable
versions cannot change its week — copy the plan instead.

## Faculty from the course list

Saving a section (or importing the Sections sheet) with a faculty ID that is not in the plan's Faculty list
creates that faculty member automatically, free in every slot of every teaching day, with the name taken from
the email (`juhi.tyagi@…` → "Juhi Tyagi"). Admins then adjust their availability on *Faculty availability*.

## Engine changes kept outside `src/`

The app improves on the original engine without editing `src/`:

1. **No double booking across overlapping terms** (`runner.py`, on by default per plan). `src/solver.py`
   only prevents a room / faculty member being double booked within the *same* term ID.
2. **Per-section room requirements** (`plan_solver.py`). `src/data_loader.py` builds one course per course
   code from the first row, so every section inherited section 1's room capacity and lab type.
3. **`Faculty.program_ids`** (`engine/domain.py`). `src/solver.py` reads it for the faculty free-day rule,
   but `src/domain.py` does not declare it.
4. **Rule weights, progress and stop** (`runner.py`): penalties scale with the plan's weights (100 =
   original values); the search runs in a helper thread so the job can report progress and stop.

Known issue in the original command line (left unchanged): `src/data_loader.py` does not read the current
workbook format (`required_cohorts`, `meeting_slots` on Programs, two `str[...]` typos). The app uses its own
`scenario_builder.py` and is not affected.
