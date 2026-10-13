"""Independent rule checker - does NOT import the solver.

python tests/checker.py input.json output.json
Recomputes everything from the input and the roster and reports any broken rule.
"""
import json
import sys

SLOTS = 10


def check(inp, out):
    errs = []
    if out.get("status") != "ok":
        return [f"status is {out.get('status')}, not ok"]
    grid, cap = inp["grid_available"], inp["generator_capacity_kw"]
    budget = round(inp["fuel_budget_litres"] * 100)
    table = [(r["load_kw"], round(r["litres_per_hour"] * 100)) for r in inp["fuel_table"]]
    shops = {s["id"]: s for s in inp["shops"]}
    ids = set(shops)
    outage = [h for h in range(SLOTS) if not grid[h]]

    by_slot = {}
    for e in out["roster"]:
        if e["slot"] in by_slot:
            errs.append(f"slot {e['slot']} appears twice")
        by_slot[e["slot"]] = e
    if sorted(by_slot) != outage:
        errs.append(f"roster slots {sorted(by_slot)} != outage slots {outage}")

    fuel = value = 0
    on = {}
    for h in outage:
        e = by_slot.get(h)
        if not e:
            continue
        p = e["powered"]
        d = [x["id"] for x in e["dark"]]
        if len(set(p)) != len(p) or len(set(d)) != len(d) or set(p) & set(d) or set(p) | set(d) != ids:
            errs.append(f"slot {h}: powered/dark not an exact split of the shop ids")
        for x in e["dark"]:
            if not x.get("reason", "").strip():
                errs.append(f"slot {h}: {x['id']} dark without a reason")
        load = sum(shops[i]["kw"] for i in p)
        if load > cap:
            errs.append(f"slot {h}: load {load} > capacity {cap}")
        cost = 0 if load == 0 else next((c for kw, c in table if load <= kw), None)
        fuel += cost or 0
        value += sum(shops[i]["value_per_slot"][h] for i in p)
        for i, s in shops.items():
            if s["type"] == "mandatory" and i not in p:
                errs.append(f"slot {h}: mandatory {i} is dark")
        on[h] = set(p)

    if fuel > budget:
        errs.append(f"fuel {fuel/100:.2f} L > budget {budget/100:.2f} L")
    for i, s in shops.items():
        run = longest = dark = 0
        for h in range(SLOTS):
            if grid[h] or i in on.get(h, set()):
                run = 0
            else:
                run += 1
                dark += 1
                longest = max(longest, run)
        if s["type"] == "normal" and longest > inp["max_consecutive_dark"]:
            errs.append(f"{i}: dark {longest} h in a row > {inp['max_consecutive_dark']}")
        if out["dark_hours"].get(i) != dark:
            errs.append(f"{i}: dark_hours {out['dark_hours'].get(i)} != recomputed {dark}")
    if out["value_total"] != value:
        errs.append(f"value_total {out['value_total']} != recomputed {value}")
    if round(out["fuel_total_litres"] * 100) != fuel:
        errs.append(f"fuel_total_litres {out['fuel_total_litres']} != recomputed {fuel/100:.2f}")
    return errs


if __name__ == "__main__":
    inp = json.load(open(sys.argv[1]))
    out = json.load(open(sys.argv[2]))
    errs = check(inp, out)
    print("\n".join(errs) if errs else "OK - all rules hold, totals match")
    sys.exit(1 if errs else 0)
