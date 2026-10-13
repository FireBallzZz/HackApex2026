# Verification evidence

## 1. The input that broke an earlier version — `bug/`

**Earlier version:** the solver was a pure-Python dynamic programme only (it is still in the code
as the fallback engine, so the failure is reproducible: `ROSTER_ENGINE=dp python app.py`).

**Breaking input:** `bug/input_all_day_outage_12_small_shops.json` — we built it to stress the
search: grid off all ten hours, 12 shops of 1–6 kW (many ways to fill 20 kW), 22 L of diesel.

**That version's output:** `bug/output_before_fix_dp_engine.json` —
`status: infeasible, "Search limit reached before any valid roster was found."`
That is **wrong**: a valid roster exists. The DP's state space (dark-run of every shop × diesel)
grew past the time limit; its quick "beam" pass also found nothing, so it fell back to infeasible.

**Fix:** added the integer-programme engine (`roster/ilp.py`, HiGHS via scipy). Each rule is one
linear constraint family and the solver proves optimality in ~1.5 s.

**Fixed output:** `bug/output_after_fix.json` — `status: ok`, value **312**, 24.80 L.
Checked by `tests/checker.py` (all rules hold, totals match) and by a separately written ILP in
`tests/ilp_crosscheck.py` (also 312).

Re-run through the API:
```
curl -X POST --data-binary @evidence/bug/input_all_day_outage_12_small_shops.json http://localhost:8000/api/roster
```

### Another bug we hit on the way
The first best-effort search for infeasible days ignored the dark-run rule but still *tracked*
dark runs, so on the 8-hour-block update the state space exploded and the process was killed
(out of memory, exit 137). Fix: when the rule is ignored, runs are not tracked; and the search now
stops itself before memory blows up (`count > 4 * state_cap`).

## 2. Boundary checks — `boundary/`, summary in `SUMMARY.md`

All run through `POST /api/roster` by `python evidence/run_evidence.py`; every `ok` output is
re-checked with the independent checker.

| input | what it tests | result |
|---|---|---|
| b01 | no outage at all | ok, empty roster, 0 / 0.00 L |
| b02 | empty shop list | ok, 0 / 0.00 L |
| b03 | budget exactly what the optimum needs (8.00) | ok, 84, 8.00 L — no rounding tolerance |
| b04 | one hundredth less (7.99) | ok, 79, 7.60 L (brute force agrees) |
| b05 | shop bigger than the generator, blocks of 2 h | ok, it is dark "Never fits", rule 6 still holds |
| b06 | same shop, 3 h block | infeasible: names the shop, its kW and the block |
| b07 | max_consecutive_dark = 0 | infeasible: all shops can't fit at once |
| b08 | mandatory shop alone over capacity | infeasible: names the shop and the hours |
| b09 | litres with 3 decimals | 400 invalid_input naming `fuel_budget_litres` |
| b10 | duplicate shop id | 400 invalid_input naming `shops[1].id` |
| b11 | zero diesel, no mandatory shops | ok, everyone dark, 0.00 L |
| b12 | all-day outage, 12 shops | ok, 312 in 1.6 s |

## 3. Optimality tests — `tests/test_solver.py`
* worked example from the brief: 84 / 8.00 L;
* 300 random small markets, compared with a brute force that tries every possible roster:
  same optimum, same infeasible cases, 0 failures (both engines);
* every dark reason on an optimal roster is a real rule (capacity / diesel / never fits / worth 0);
* 10 malformed inputs → HTTP 400 naming the field.
