# Judging prep — Who Stays On?

Every team member should be able to say all of this alone (criterion 4 picks one at random).

---

## The problem in 30 seconds
7 outage hours. 20 kW generator, 17 L diesel, 12 shops wanting ~40 kW. Each outage hour we pick
which shops are on. Rules: load ≤ 20 kW every hour; diesel is charged **once per hour on the
combined load**, rounded up to the next fuel-table level (≤7 kW 1.20 L, ≤14 kW 2.00 L, ≤20 kW
2.80 L); total ≤ 17.00 L; pharmacy + ATM always on; no normal shop dark 3 hours in a row (grid
hours reset the count). Maximise the sum of values of powered shops.

## Our answer on the sample: value 186, 16.40 L
* Mandatory shops are 5 kW. Running only them (1.20 L) leaves all 10 other shops dark that hour,
  which the 3-hour rule quickly forbids.
* The **minimum** diesel that satisfies the dark-run rule is **15.60 L** (the solver's
  least-diesel roster: 5 hours at the 14 kW level, 2.00 L, + 2 hours at 20 kW, 2.80 L).
* We can afford **3** full-power (20 kW) hours: 4 × 2.00 + 3 × 2.80 = **16.40 L**. A 4th would be
  +0.80 L = 17.20 L > 17.00. That's why 0.60 L is left over — it buys nothing.
* The solver chooses *which* 3 hours get 20 kW and who fills every hour so total value is maximal.
  Proven optimal (integer programme), confirmed by the independent DP engine (also 186).

## Why the greedy idea fails (they WILL ask)
`python evidence/greedy_v0.py inputs/sample_input.json`: fills every hour to 20 kW → 2.80 L × 6 =
16.80 L, the 19:00 hour has no diesel → generator stops, **pharmacy and ATM go dark** (rule 5) and
grocery/jewellery/beauty are dark 12:00–14:00, 3 hours in a row (rule 6). Its "value 189" is invalid.
Last year's pencil plan failed exactly this way.

---

## Criterion by criterion

### 1. Roster correctness
**What judges check:** capacity, diesel, mandatory, 3-hour rule, every outage hour exactly once,
powered + dark = all shops, totals right.
**Our answer:** the solver encodes every rule as a hard constraint; the answer is re-checked before
it is returned (`Model.respects_rules`); totals are recomputed from the final roster (`roster/api.py`);
an independent checker (`tests/checker.py`, does not import the solver) passes on all outputs.
Fuel is computed in whole hundredths of a litre (integers) → no floating-point rounding.
**Show:** `python tests/checker.py inputs/sample_input.json outputs/sample_output.json`.

### 2. Value served
**What judges check:** is your value the best possible?
**Our answer:** optimal, not heuristic. Engine 1 is an integer programme solved by HiGHS with
gap 0 (proven optimum). Engine 2 is an exact dynamic programme. Both give 186 on the sample and 84
on the worked example (= the brief's best). 300 random markets match a brute force that tries every
roster. Ties → least diesel.

### 3. Robustness
| situation | what the app does |
|---|---|
| minute-150 update (one grid hour → outage) | just re-run; nothing is cached. Our pre-run: **infeasible**, needs 17.60 L vs 17.00 L, best-effort roster attached |
| no outages / no shops | ok, empty roster, zeros |
| shop bigger than generator | dark with "Never fits"; infeasible if that leaves it dark > max hours |
| mandatory > capacity, or mandatory diesel > budget | infeasible, names shops and numbers |
| rules can't all hold together | infeasible + which rule pair (dark-run vs diesel / vs capacity) + numbers |
| bad JSON, missing field, wrong lengths, duplicate id, negative, 3 decimals, bad fuel table | HTTP 400, `invalid_input`, message names the field |
| solver bug | HTTP 500 with message, server stays up |
| time | sample 0.5 s; worst case we built (all-day, 12 shops) 1.6 s; hard cap 9 s |

### 4. Personal understanding — likely questions and answers

**Q: Explain your algorithm.**
"We plan the whole day at once. Variables: on/off for each shop in each outage hour, plus which
fuel level each hour is charged at. Each rule is a constraint: load ≤ the chosen level's kW and
> the level below (so the level is exactly the rounded-up one); exactly one level per hour; sum
of litres ≤ budget; in every 3 consecutive outage hours a normal shop is on at least once.
Maximise value. HiGHS solves it exactly. As a fallback without scipy we have a dynamic programme
over the hours that remembers each shop's current dark run and the diesel used."

**Q: How is the dark-run rule a linear constraint?**
"'Never dark 3 in a row' = 'in any window of 3 consecutive outage hours, on at least once':
x[h] + x[h+1] + x[h+2] ≥ 1. A grid hour inside the window breaks the run, so we only add windows
with no grid hour."

**Q: Why is fuel per hour, not per shop?**
"The generator burns by how loaded it is. Pharmacy + tea stall = 4 kW is one lookup (0.80 L in the
worked example), not two." Rounding: 15 kW → the 20 kW level → 2.80 L.

**Q: Why is X dark at Y?** Click the ✗. Every reason is one of four, always with numbers:
1. *Capacity* — adding it exceeds 20 kW. 2. *Fuel* — adding it lifts the hour to a higher fuel
level and the day would exceed 17.00 L. 3. *Never fits* — bigger than the free capacity.
4. *Worth 0*. Why only these: switching a dark shop on changes only that hour's load/fuel (and
only shortens its own dark run), so if it fitted both capacity and budget the optimum would have
turned it on.

**Q: Why not spend the last 0.60 L?** Every useful upgrade (14 → 20 kW level) costs 0.80 L.

**Q: Predict: budget changes?** (sample, from our runs)
| budget | result |
|---|---|
| ≤ 15.59 L | infeasible — rule 6 needs ≥ 15.60 L |
| 16.00 L | 171 (uses 15.60) |
| 16.39 L | 171 — one hundredth short of the 3rd full hour |
| 16.40–17.19 L | 186 |
| 18.00 L | 212 |
| ≥ 19.60 L | 225 — every hour at 20 kW; more diesel doesn't help |

**Q: Predict: other changes?**
| change | result |
|---|---|
| capacity 22 kW | 206, same 16.40 L |
| capacity 18 kW | infeasible (needs 17.20 L) |
| max dark 3 | 203; max dark 4 → 207 |
| max dark 0 or 1 | infeasible — not enough capacity to keep everyone that often |
| 16:00 or 11:00 becomes outage | infeasible: needs 17.60 L; with 17.60 L → 185 |
| 12:00 grid returns | 196 |
| restaurant mandatory | infeasible, needs 19.60 L |
Rule of thumb: more diesel, more capacity or a looser dark-run rule can only keep or raise value;
more outage hours or more mandatory shops can only lower it or make it infeasible.

**Q: What if the generator / diesel can't satisfy everything?** "We return `infeasible` (HTTP 200),
say which rules clash with numbers, and attach a best-effort roster clearly labelled NOT VALID —
for a diesel shortfall it obeys every other rule and shows the least extra diesel needed."

**Q: Why ILP and not just the DP?** "The DP is exact but its state (dark run of every shop ×
diesel) explodes on all-day outages with many small shops — evidence/bug shows it timing out on one
we built. The ILP solves that in 1.6 s. We kept the DP as a no-dependency fallback and cross-check."

**Q: Why a form instead of JSON?** "The people who use this are a market secretary and a generator
operator, not programmers. They tap the hours DESCO cuts, type today's diesel, and drag bars for how busy
each shop is. The form builds exactly the same JSON the API reads, and the JSON tab still exists for
other systems."

**Q: What does the database do?** "SQLite, built into Python, so it works offline with nothing to
install. It stores saved markets (shops rarely change, so you load them instead of retyping) and every
roster ever made, with its full input and output, so a dispute about last Thursday can be checked. If
the database fails, the roster API still answers - saving is best-effort."

**Q: How fast? Offline?** Under 2 s on everything we tried; 9 s cap; no network calls; scipy is
installed beforehand.

### 5. Working application
Run `python app.py`, open `http://localhost:8000/`. Show: Load sample → Make roster → board with
✓/✗/grid, ★ mandatory; per-hour load vs 20 kW and fuel with running total vs 17 L; click a ✗ for
its reason; list of all reasons; dark hours column; Download output JSON; Print (one A4 landscape
page). Show the API with curl. Upload a bad file → red invalid_input message.

### 6. Verification evidence
`evidence/NOTES.md` tells the story: the all-day 12-shop input broke the DP-only version (said
"infeasible" wrongly) → added the ILP engine → now ok 312, checked by the independent checker and a
separate ILP. 12 boundary inputs run through the API (`evidence/SUMMARY.md`). Plus brute-force tests.

---

## Before judging
1. Get `schema.md`, `example_output.json` and the validator from the pack; run the validator on
   `outputs/sample_output.json`. If field names differ, change only `roster/api.py`.
2. At minute 150: save the update as `inputs/update_input.json`, POST it, save
   `outputs/update_output.json`, commit.
3. Each member: run the app once yourself and click through.
