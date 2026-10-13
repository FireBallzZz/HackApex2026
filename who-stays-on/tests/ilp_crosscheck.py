"""Dev-only cross-check with a completely different method: an integer linear
programme solved by scipy's MILP solver (HiGHS). NOT used by the app (the app
needs only the Python standard library).

python tests/ilp_crosscheck.py inputs/sample_input.json [more inputs...]
Prints the ILP optimum next to ours. For infeasible inputs it prints the
minimum diesel the dark-run rule needs.
"""
import json
import os
import sys

import numpy as np
from scipy.optimize import milp, LinearConstraint, Bounds

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from roster.api import run  # noqa: E402

SLOTS = 10


def ilp(inp, minimise_fuel=False, budget_override=None):
    grid, cap, M = inp["grid_available"], inp["generator_capacity_kw"], inp["max_consecutive_dark"]
    budget = round(inp["fuel_budget_litres"] * 100) if budget_override is None else budget_override
    levels = [(0, 0)] + [(r["load_kw"], round(r["litres_per_hour"] * 100)) for r in inp["fuel_table"]]
    shops = inp["shops"]
    outage = [h for h in range(SLOTS) if not grid[h]]
    if not outage:
        return 0, 0
    nS, nH, nL = len(shops), len(outage), len(levels)
    xi = lambda s, k: s * nH + k
    yi = lambda k, l: nS * nH + k * nL + l
    N = nS * nH + nH * nL
    c = np.zeros(N)
    lo, hi = np.zeros(N), np.ones(N)
    A, lb, ub = [], [], []
    for s, sh in enumerate(shops):
        for k, h in enumerate(outage):
            c[xi(s, k)] = -sh["value_per_slot"][h]
            if sh["type"] == "mandatory":
                lo[xi(s, k)] = 1
    for k in range(nH):
        row = np.zeros(N)
        for s, sh in enumerate(shops):
            row[xi(s, k)] = sh["kw"]
        for l, (kw, _) in enumerate(levels):
            row[yi(k, l)] = -kw
        A.append(row); lb.append(-np.inf); ub.append(0)          # load <= chosen level
        row = np.zeros(N)
        for l in range(nL):
            row[yi(k, l)] = 1
        A.append(row); lb.append(1); ub.append(1)                 # exactly one level
    fuel_row = np.zeros(N)
    for k in range(nH):
        for l, (_, cost) in enumerate(levels):
            fuel_row[yi(k, l)] = cost
    A.append(fuel_row); lb.append(-np.inf); ub.append(budget)
    # dark-run rule: in every M+1 consecutive slots with no grid hour, on at least once
    for s, sh in enumerate(shops):
        if sh["type"] != "normal":
            continue
        for start in range(SLOTS - M):
            win = list(range(start, start + M + 1))
            if all(not grid[h] for h in win):
                row = np.zeros(N)
                for h in win:
                    row[xi(s, outage.index(h))] = 1
                A.append(row); lb.append(1); ub.append(np.inf)
    obj = fuel_row if minimise_fuel else c
    res = milp(obj, constraints=LinearConstraint(np.array(A), lb, ub),
               integrality=np.ones(N), bounds=Bounds(lo, hi))
    if res.status != 0:
        return None
    x = res.x
    return round(-float(c @ x)), round(float(fuel_row @ x))


if __name__ == "__main__":
    for path in sys.argv[1:]:
        inp = json.load(open(path))
        _, ours = run(inp)
        r = ilp(inp)
        if r is None:
            mf = ilp(inp, minimise_fuel=True, budget_override=10 ** 9)
            print(f"{os.path.basename(path)}: ILP infeasible; min diesel for dark-run rule = "
                  f"{mf[1] / 100 if mf else 'n/a'} | ours: {ours['status']} - {ours.get('message', '')[:90]}")
        else:
            print(f"{os.path.basename(path)}: ILP best value {r[0]} | ours {ours.get('value_total')} "
                  f"({ours['status']}, {ours.get('fuel_total_litres')} L)")
