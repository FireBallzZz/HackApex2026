"""Engine 1 (primary): the whole day as one integer linear programme,
solved exactly by HiGHS through scipy.optimize.milp. Runs offline.

Variables (all 0/1)
  x[s,k]  normal shop s is ON in outage hour k
  y[k,l]  hour k is charged at fuel level l   (l = 0 is "zero load, zero fuel")

Each rule is one family of constraints:
  capacity (rule 3) .... load_k <= capacity              (implied by the level choice)
  fuel level (rule 4) .. sum_l y[k,l] = 1
                         load_k <= kw_l            if level l chosen
                         load_k >= kw_(l-1) + 1    if level l chosen   -> level is EXACTLY
                                                                        the first one >= load
  fuel budget (rule 4) . sum_k sum_l litres_l * y[k,l] <= budget
  mandatory (rule 5) ... mandatory shops are constants in load_k (always on)
  dark runs (rule 6) ... in every window of max_dark+1 consecutive outage hours
                         (no grid hour inside) each normal shop is on at least once
Objective (rule 7) ..... maximise sum v[s,h] * x[s,k]   (+ the constant mandatory value)
"""
import numpy as np
from scipy.optimize import milp, LinearConstraint, Bounds

SLOTS = 10


def solve_ilp(m, budget, max_dark, minimise_fuel=False, time_limit=8.0):
    """Returns dict(best=(value, fuel, masks), optimal=bool) or None if infeasible.
    masks: per outage hour, bitmask over m.elig (same format as the DP engine)."""
    outage, elig = m.outage, m.elig
    levels = [(0, 0)] + list(m.levels)
    nS, nH, nL = len(elig), len(outage), len(levels)
    xi = lambda s, k: s * nH + k
    yi = lambda k, l: nS * nH + k * nL + l
    N = nS * nH + nH * nL

    value = np.zeros(N)
    for s, sh in enumerate(elig):
        for k, h in enumerate(outage):
            value[xi(s, k)] = sh["values"][h]
    fuel = np.zeros(N)
    for k in range(nH):
        for l, (_, c) in enumerate(levels):
            fuel[yi(k, l)] = c

    rows, lo, hi = [], [], []

    def add(row, a, b):
        rows.append(row); lo.append(a); hi.append(b)

    for k in range(nH):
        load = np.zeros(N)                     # load_k - mand_kw  (variable part)
        for s, sh in enumerate(elig):
            load[xi(s, k)] = sh["kw"]
        one = np.zeros(N)
        upper, lower = load.copy(), load.copy()
        for l, (kw, _) in enumerate(levels):
            one[yi(k, l)] = 1
            upper[yi(k, l)] = -kw                          # load <= kw_l
            lower[yi(k, l)] = -(levels[l - 1][0] + 1 if l > 0 else 0)   # load >= prev+1
        add(one, 1, 1)
        add(upper, -np.inf, -m.mand_kw)
        add(lower, -m.mand_kw, np.inf)
    add(fuel, -np.inf, budget)

    if max_dark is not None:
        for s in range(nS):
            for start in range(SLOTS - max_dark):
                win = range(start, start + max_dark + 1)
                if all(not m.grid[h] for h in win):
                    row = np.zeros(N)
                    for h in win:
                        row[xi(s, outage.index(h))] = 1
                    add(row, 1, np.inf)

    # tie-break: among equal-value rosters prefer less diesel (tiny weight)
    if minimise_fuel:
        obj = fuel
    else:
        obj = -value + fuel * (0.5 / (fuel.sum() + 1))
    res = milp(obj, constraints=LinearConstraint(np.array(rows), lo, hi),
               integrality=np.ones(N), bounds=Bounds(0, 1),
               options={"time_limit": time_limit, "disp": False, "mip_rel_gap": 0})
    if res.x is None:
        if res.status == 1:            # time limit with nothing found
            raise TimeoutError()
        return None                    # proven infeasible
    x = np.round(res.x).astype(int)
    masks = []
    for k in range(nH):
        mask = 0
        for s in range(nS):
            if x[xi(s, k)]:
                mask |= 1 << s
        masks.append(mask)
    base = sum(sum(sh["values"][h] for sh in m.mand) for h in outage)
    return {"best": (int(value @ x) + base, int(round(fuel @ x)), masks),
            "optimal": res.status == 0}
