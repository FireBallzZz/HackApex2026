"""The "obvious" first idea, kept to show WHY it fails (brief, 'What makes a strong entry?').

Each outage hour, in time order: switch on the most valuable shops that fit
the capacity, as long as diesel is left. No look-ahead.

python evidence/greedy_v0.py inputs/sample_input.json
"""
import json
import sys

SLOTS = 10


def greedy(inp):
    cap = inp["generator_capacity_kw"]
    budget = round(inp["fuel_budget_litres"] * 100)
    table = [(r["load_kw"], round(r["litres_per_hour"] * 100)) for r in inp["fuel_table"]]
    cost = lambda load: 0 if load == 0 else next(c for kw, c in table if load <= kw)
    shops = inp["shops"]
    fuel = value = 0
    rows = []
    for h in range(SLOTS):
        if inp["grid_available"][h]:
            continue
        on = [s for s in shops if s["type"] == "mandatory"]
        load = sum(s["kw"] for s in on)
        for s in sorted((s for s in shops if s["type"] == "normal"),
                        key=lambda s: -s["value_per_slot"][h]):
            if load + s["kw"] <= cap:
                on.append(s)
                load += s["kw"]
        c = cost(load)
        if fuel + c > budget:                 # diesel has run out: generator stops
            on, load, c = [], 0, 0
        fuel += c
        value += sum(s["value_per_slot"][h] for s in on)
        rows.append((h, [s["id"] for s in on], load, c, fuel))
    return rows, value, fuel


if __name__ == "__main__":
    inp = json.load(open(sys.argv[1]))
    rows, value, fuel = greedy(inp)
    for h, on, load, c, run in rows:
        print(f"{10 + h}:00  load {load:2d} kW  fuel {c / 100:.2f} L  so far {run / 100:5.2f} L  on={on}")
    print(f"value {value}, fuel {fuel / 100:.2f} L")
