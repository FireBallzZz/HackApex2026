"""Self-tests (stdlib only):  python tests/test_solver.py

1. Worked example from the brief must score 84 using 8.00 L.
2. 300 random small markets: our solver vs. a brute force that tries EVERY
   possible roster. Same best value, same feasibility, and the independent
   checker accepts our roster.
3. Every dark reason on an optimal roster is a real rule (never the fallback).
4. Invalid inputs return HTTP 400 naming the field.
"""
import itertools
import json
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from roster.api import run          # noqa: E402
from checker import check           # noqa: E402

SLOTS = 10


def brute_force(inp):
    """Try every on/off choice for every normal shop in every outage hour."""
    grid, cap = inp["grid_available"], inp["generator_capacity_kw"]
    budget = round(inp["fuel_budget_litres"] * 100)
    table = [(r["load_kw"], round(r["litres_per_hour"] * 100)) for r in inp["fuel_table"]]
    M = inp["max_consecutive_dark"]
    shops = inp["shops"]
    outage = [h for h in range(SLOTS) if not grid[h]]
    mand = [s for s in shops if s["type"] == "mandatory"]
    normal = [s for s in shops if s["type"] == "normal"]
    best = None
    for bits in itertools.product([0, 1], repeat=len(normal) * len(outage)):
        fuel = value = 0
        ok = True
        on = {}
        for k, h in enumerate(outage):
            pw = mand + [s for j, s in enumerate(normal) if bits[k * len(normal) + j]]
            load = sum(s["kw"] for s in pw)
            if load > cap:
                ok = False
                break
            fuel += 0 if load == 0 else next(c for kw, c in table if load <= kw)
            value += sum(s["values"][h] if "values" in s else s["value_per_slot"][h] for s in pw)
            on[h] = {s["id"] for s in pw}
        if not ok or fuel > budget:
            continue
        for s in normal:
            run_ = 0
            for h in range(SLOTS):
                run_ = 0 if grid[h] or s["id"] in on[h] else run_ + 1
                if run_ > M:
                    ok = False
        if ok and (best is None or value > best):
            best = value
    return best


def random_input(rng):
    n_out = rng.randint(0, 5)
    grid = [True] * SLOTS
    for h in rng.sample(range(SLOTS), n_out):
        grid[h] = False
    cap = rng.randint(4, 10)
    lv = sorted(rng.sample(range(1, cap), rng.randint(0, 2))) + [cap]
    lit, table = 0, []
    for kw in lv:
        lit += rng.randint(10, 80)
        table.append({"load_kw": kw, "litres_per_hour": lit / 100})
    shops = []
    for i in range(rng.randint(0, 4)):
        shops.append({"id": f"s{i}", "kw": rng.randint(1, cap + 1),
                      "type": "mandatory" if rng.random() < 0.2 else "normal",
                      "value_per_slot": [rng.randint(0, 6) for _ in range(SLOTS)]})
    if sum(1 for s in shops if s["type"] == "normal") * n_out > 14:
        shops = shops[:2]
    return {"grid_available": grid, "generator_capacity_kw": cap,
            "fuel_budget_litres": rng.randint(0, 400) / 100, "fuel_table": table,
            "max_consecutive_dark": rng.randint(0, 3), "shops": shops}


def main():
    fails = 0
    # 1. worked example
    inp = json.load(open(os.path.join(ROOT, "inputs", "worked_example.json")))
    code, out = run(inp)
    assert code == 200 and out["value_total"] == 84 and out["fuel_total_litres"] == 8.0, out
    assert not check(inp, out)
    print("worked example: 84 / 8.00 L  OK")

    # 2 + 3. random vs brute force
    rng = random.Random(2026)
    n_ok = n_inf = 0
    for t in range(300):
        inp = random_input(rng)
        code, out = run(inp)
        bf = brute_force(inp)
        if bf is None:
            if out["status"] != "infeasible":
                print("MISMATCH (should be infeasible)", t, json.dumps(inp))
                fails += 1
            n_inf += 1
            continue
        n_ok += 1
        if out["status"] != "ok" or out["value_total"] != bf:
            print("MISMATCH", t, bf, out.get("value_total"), out["status"], json.dumps(inp))
            fails += 1
            continue
        errs = check(inp, out)
        if errs:
            print("CHECKER", t, errs)
            fails += 1
        for e in out["roster"]:
            for d in e["dark"]:
                if d["reason"].startswith("Not chosen"):
                    print("FALLBACK REASON", t, d)
                    fails += 1
    print(f"random vs brute force: {n_ok} feasible + {n_inf} infeasible cases, {fails} failures")

    # 4. invalid inputs
    base = json.load(open(os.path.join(ROOT, "inputs", "worked_example.json")))
    bad_cases = {
        "grid_available": lambda d: d["grid_available"].pop(),
        "generator_capacity_kw": lambda d: d.update(generator_capacity_kw="10"),
        "fuel_budget_litres": lambda d: d.update(fuel_budget_litres=8.001),
        "fuel_table[1].load_kw": lambda d: d["fuel_table"][1].update(load_kw=3),
        "fuel_table: last": lambda d: d["fuel_table"][2].update(load_kw=11),
        "shops[1].id": lambda d: d["shops"][1].update(id="pharmacy"),
        "shops[2].kw": lambda d: d["shops"][2].update(kw=-3),
        "shops[0].type": lambda d: d["shops"][0].update(type="vip"),
        "shops[3].value_per_slot": lambda d: d["shops"][3]["value_per_slot"].append(1),
        "max_consecutive_dark": lambda d: d.pop("max_consecutive_dark"),
    }
    for field, mutate in bad_cases.items():
        d = json.loads(json.dumps(base))
        mutate(d)
        code, out = run(d)
        key = field.split(":")[0]
        if code != 400 or out["status"] != "invalid_input" or key not in out["message"]:
            print("INVALID-INPUT FAIL", field, code, out)
            fails += 1
    print(f"invalid inputs: {len(bad_cases)} cases checked")

    print("ALL PASS" if not fails else f"{fails} FAILURES")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
