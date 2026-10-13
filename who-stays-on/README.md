# Who Stays On? — generator roster for Shapla Shopping Complex

Reads today's load-shedding situation and decides, for every outage hour, which shops the
20 kW generator powers — never over capacity, never over the diesel budget, mandatory shops
always on, no normal shop dark more than `max_consecutive_dark` hours in a row — and serves
the **maximum possible value**. Every dark cell gets a one-line reason with numbers.

## Start it

```
pip install -r requirements.txt     # once, before the event (numpy + scipy). Optional, see "Engines".
python app.py                       # or: ./run.sh
```

Open **http://localhost:8000/** (port 8000; change with `PORT=9000 python app.py`).
No internet needed at runtime.

API: `POST http://localhost:8000/api/roster` — body = input JSON, response = output JSON.
HTTP 200 for `ok` and `infeasible`, HTTP 400 for `invalid_input`. The screen uses this same endpoint.

```
curl -X POST --data-binary @inputs/sample_input.json http://localhost:8000/api/roster
```

Command line (same code path): `python solve_cli.py input.json [output.json]` — exit code 2 on invalid input.

## Where the decision logic lives (read in this order)

| file | what it does |
|---|---|
| `roster/solver.py` | **the decision logic.** `solve()` → `optimise()` picks the engine; infeasibility diagnosis; the pure-Python DP engine (`Model.search`) |
| `roster/ilp.py` | primary engine: the day as one integer programme (each rule = one constraint family), solved exactly by HiGHS via scipy |
| `roster/explain.py` | the one-line reason for every dark cell |
| `roster/validate.py` | input checks → `invalid_input` naming the field; litres converted to whole hundredths |
| `roster/api.py` | input JSON → output JSON; totals recomputed from the roster. **Output format lives only here** |
| `app.py` | web server: serves `static/index.html`, `POST /api/roster`, and the database endpoints below |
| `roster/db.py` | SQLite database (`data/shapla.db`): saved markets and the history of every roster |
| `static/index.html` | the screen — calls `/api/roster`. HTML + CSS + JS in one file, no internet. **Plan-the-day form** (power-cut hour chips, generator & diesel fields, shop cards with drag-to-set hourly bars and "must stay on" switches) that builds the input JSON; a JSON tab for raw input; diesel speedometer + KPI cards with click-to-open trend charts; roster board; shop badges; reasons; history; A4 print view |

## Database (SQLite, built into Python — nothing to install, offline)

File: `data/shapla.db`, created on first start (override with `DB_PATH=...`). Two tables:

* `setups` — a market's saved configuration (shops, generator, fuel table) so nobody retypes it daily.
  The sample market is added on first start.
* `runs` — every roster the API produced: time, label, status, value, diesel, plus the full input and
  output JSON, so any past day can be reopened or audited.

| endpoint | does |
|---|---|
| `GET /api/runs?limit=50` | past rosters, newest first (summary) |
| `GET /api/runs/<id>` · `DELETE /api/runs/<id>` | one past roster with full input/output · remove it |
| `GET /api/setups` · `GET /api/setups/<id>` | saved markets · one market's input JSON |
| `POST /api/setups` `{"name": .., "input": {..}}` | save or overwrite by name (input is validated first) |
| `DELETE /api/setups/<id>` | remove a saved market |

`POST /api/roster` is unchanged: same body, same response. It also stores the run and returns its id in
the `X-Run-Id` header (optional `X-Run-Label` request header names it). If the database fails, the
roster is still returned.

## How it decides

The day is planned as **one problem**, not hour by hour (hour-by-hour greedy burns the diesel at
noon and breaks the 3-hour rule — see `evidence/greedy_v0.py`).

* **Engine 1 — integer programme (default).** 0/1 variable per (normal shop, outage hour) and per
  (outage hour, fuel level). Capacity, "first fuel level ≥ combined load", diesel budget, and
  "on at least once in every `max_dark+1` consecutive outage hours" are linear constraints;
  objective = total value. HiGHS proves the optimum. Equal-value ties → least diesel.
* **Engine 2 — dynamic programme (fallback, standard library only).** Walks the hours keeping
  states (dark-run of every shop, diesel used, value); keeps only states not beaten on both diesel
  and value; per hour tries only "maximal" shop sets. Exact on the sample and the worked example;
  can hit the time limit on all-day outages with 12 small shops (it says so in the output).
  Used automatically if scipy is missing; force with `ROSTER_ENGINE=dp python app.py`.

Every answer is re-checked against the rules before it is returned.

**Infeasible inputs** are explained by the rule pair in conflict, with numbers
(e.g. *"keeping every normal shop dark at most 2 h in a row needs at least 17.60 L of diesel;
budget is 17.00 L"*), plus a clearly labelled best-effort roster.

## Results on the public inputs

| input | status | value | diesel |
|---|---|---|---|
| `inputs/worked_example.json` (brief p.3) | ok | 84 | 8.00 L (matches the brief) |
| `inputs/sample_input.json` | ok | 186 | 16.40 L of 17.00 |
| minute-150 update | *run on arrival — see below* | | |

Outputs: `outputs/sample_output.json`, `outputs/worked_example_output.json`.

### Minute-150 update
```
cp <update file> inputs/update_input.json
curl -X POST --data-binary @inputs/update_input.json http://localhost:8000/api/roster > outputs/update_output.json
python tests/checker.py inputs/update_input.json outputs/update_output.json   # if status ok
```
We pre-ran both likely updates (16:00 or 11:00 becomes an outage) in `outputs/predicted_update/`:
both are **infeasible** — 8 outage hours need at least 17.60 L to keep every shop within the
2-hour rule, and there are 17.00 L. The app reports that and attaches a best-effort roster at 17.60 L.

## Testing

```
python tests/test_solver.py          # worked example, 300 random markets vs brute force, invalid inputs
python tests/test_db.py              # database: save / overwrite / read / delete setups and runs
python evidence/run_evidence.py      # (app running) boundary inputs through the API -> evidence/SUMMARY.md
python tests/ilp_crosscheck.py inputs/sample_input.json   # dev: independent ILP formulation
python tests/checker.py input.json output.json            # independent rule checker
```

`evidence/` — `bug/` (input that broke an earlier version, that version's output, fixed output),
`boundary/` (12 boundary inputs + outputs), `SUMMARY.md`, `NOTES.md`.

## Output format

```
{ "status": "ok",
  "roster": [ { "slot": 2, "hour": "12:00", "powered": [ids], "dark": [{"id": .., "reason": ..}],
                "load_kw": 14, "fuel_litres": 2.0, "fuel_running_litres": 2.0 }, ... ],
  "value_total": 186, "fuel_total_litres": 16.4, "dark_hours": {"pharmacy": 0, ...} }
{ "status": "infeasible", "message": .., "conflicts": [..], "best_effort": { "label": .., "roster": .., ... } }
{ "status": "invalid_input", "message": "shops[1].id: duplicate id 'pharmacy'" }
```
If `schema.md` differs, only `roster/api.py` needs changing.
