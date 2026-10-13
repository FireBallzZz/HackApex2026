"""THE DECISION LOGIC - start reading here.

Idea in one paragraph
---------------------
Walk the day hour by hour (10:00 -> 19:00). In every outage hour we choose
WHICH SET of normal shops is powered (mandatory shops are always on). A
"state" after an hour is:
    runs  - for every normal shop, how many outage hours in a row it has been dark
    fuel  - diesel used so far (whole hundredths of a litre)
    value - value served so far
Two states with the same `runs` behave identically in the future, so for the
same `runs` we only keep the ones that are not beaten on BOTH fuel and value
(Pareto pruning). A grid-on hour resets every run to 0. At 20:00 the best
surviving state is the optimal roster; we follow its back-pointers.

That is an exact dynamic programme over the whole day, so diesel is never
"spent at noon" greedily - an hour is only given fuel if that beats saving it.

Two tricks keep it fast:
1. Per hour we only try MAXIMAL sets: sets where no further shop fits without
   pushing the load into the next fuel level. Adding a shop that costs no
   extra fuel can never hurt (values >= 0, and being on only resets its run),
   so non-maximal sets are never needed.
2. Branch-and-bound: a quick "beam" pass finds a good roster first (lower
   bound). In the exact pass a state is dropped if even the most optimistic
   future (best value per hour ignoring the dark-run rule, within the diesel
   left) cannot beat that roster.
If the exact pass ever ran past the time limit we return the beam roster and
say so (solution["optimal"] = False). On every input we have tried it finishes.
"""
import os
import time
from bisect import bisect_right
from collections import defaultdict

SLOTS = 10


class Timeout(Exception):
    pass


# Engine choice: the ILP (scipy/HiGHS) if installed, else the pure-Python DP below.
# Force one with ROSTER_ENGINE=ilp or ROSTER_ENGINE=dp.
try:
    from .ilp import solve_ilp
    HAVE_ILP = True
except ImportError:            # scipy not installed -> DP only
    HAVE_ILP = False


def engine_name():
    want = os.environ.get("ROSTER_ENGINE", "auto")
    if want == "dp" or not HAVE_ILP:
        return "dp"
    return "ilp"


def hour_label(h):
    return f"{10 + h:02d}:00"


def fuel_level(load, levels):
    """(level_kw, hundredths) charged for a combined load. Zero load = zero fuel.
    Rule 4: first level whose load_kw >= load. None if load > capacity."""
    if load == 0:
        return 0, 0
    for kw, cost in levels:
        if load <= kw:
            return kw, cost
    return None


def blocks_of(grid):
    """Maximal runs of consecutive outage slots, e.g. [[2,3,4,5],[7,8,9]]."""
    out, cur = [], []
    for h in range(SLOTS):
        if not grid[h]:
            cur.append(h)
        elif cur:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


class Model:
    def __init__(self, p):
        self.p = p
        self.grid = p["grid"]
        self.cap = p["cap"]
        self.levels = p["levels"]
        self.outage = [h for h in range(SLOTS) if not self.grid[h]]
        self.mand = [s for s in p["shops"] if s["type"] == "mandatory"]
        self.normal = [s for s in p["shops"] if s["type"] == "normal"]
        self.mand_kw = sum(s["kw"] for s in self.mand)
        self.free_kw = self.cap - self.mand_kw
        # Normal shops that can ever be switched on next to the mandatory ones.
        self.elig = [s for s in self.normal if s["kw"] <= self.free_kw]
        # Normal shops that can NEVER be on in an outage (too big).
        self.never = [s for s in self.normal if s["kw"] > self.free_kw]
        self.cands = self._candidate_sets()
        self.hval = {h: self._hour_values(h) for h in self.outage}

    # ---- per-hour choices -------------------------------------------------
    def _candidate_sets(self):
        """All (mask, load, fuel) where mask = which eligible normal shops are on,
        load <= capacity, and the set is maximal within its fuel level."""
        if self.mand_kw > self.cap:
            return []
        kws = [s["kw"] for s in self.elig]
        n = len(kws)
        out = []
        for mask in range(1 << n):
            load = self.mand_kw + sum(kws[i] for i in range(n) if mask >> i & 1)
            if load > self.cap:
                continue
            level_kw, cost = fuel_level(load, self.levels)
            if all((mask >> i & 1) or load + kws[i] > level_kw for i in range(n)):
                out.append((mask, load, cost))
        return out

    def _hour_values(self, h):
        base = sum(s["values"][h] for s in self.mand)
        vals = [s["values"][h] for s in self.elig]
        return {m: base + sum(vals[i] for i in range(len(vals)) if m >> i & 1)
                for m, _, _ in self.cands}

    # ---- optimistic bound for branch-and-bound ---------------------------
    def _future_bounds(self, budget):
        """frontier[k] = Pareto list of (fuel, best value) for outage hours k.. end,
        ignoring the dark-run rule. Used as an upper bound."""
        H = len(self.outage)
        frontier = [None] * (H + 1)
        frontier[H] = ([0], [0])
        for k in range(H - 1, -1, -1):
            h = self.outage[k]
            best_at_cost = {}
            for m, _, c in self.cands:
                v = self.hval[h][m]
                if v > best_at_cost.get(c, -1):
                    best_at_cost[c] = v
            costs, vals = frontier[k + 1]
            pts = [(c + c2, v + v2) for c, v in best_at_cost.items()
                   for c2, v2 in zip(costs, vals) if c + c2 <= budget]
            frontier[k] = _pareto_lists(pts)
        return frontier

    # ---- the search -------------------------------------------------------
    def search(self, budget, max_dark, lower_bound=None, beam=None,
               deadline=None, state_cap=400_000):
        # max_dark=None means "ignore the dark-run rule" (used for best-effort rosters)
        """Returns dict(best=(value, fuel, masks), min_fuel=int) or None if no
        roster satisfies the rules. Raises Timeout if over time / state cap."""
        n = len(self.elig)
        frontier = self._future_bounds(budget)

        def ub(k, fuel_left):
            costs, vals = frontier[k]
            i = bisect_right(costs, fuel_left) - 1
            return vals[i] if i >= 0 else None

        zero = (0,) * n
        layer = {zero: [(0, 0, None)]}        # runs -> [(fuel, value, path)]
        k = 0
        for h in range(SLOTS):
            if self.grid[h]:                  # grid hour: every run resets to 0
                merged = [e for es in layer.values() for e in es]
                layer = {zero: _pareto(merged)}
                continue
            new = defaultdict(list)
            count = 0
            for runs, entries in layer.items():
                if deadline and time.monotonic() > deadline:
                    raise Timeout()
                forced = 0                    # shops that MUST be on (run at the limit)
                if max_dark is not None:
                    for i, r in enumerate(runs):
                        if r >= max_dark:
                            forced |= 1 << i
                for mask, load, cost in self.cands:
                    if mask & forced != forced:
                        continue
                    nruns = (zero if max_dark is None else
                             tuple(0 if mask >> i & 1 else r + 1 for i, r in enumerate(runs)))
                    hv = self.hval[h][mask]
                    bucket = new[nruns]
                    for fuel, val, path in entries:
                        nf = fuel + cost
                        if nf > budget:
                            break             # entries are sorted by fuel
                        nv = val + hv
                        if lower_bound is not None:
                            u = ub(k + 1, budget - nf)
                            if u is None or nv + u <= lower_bound:
                                continue
                        bucket.append((nf, nv, (path, mask)))
                        count += 1
                if beam is None and count > 4 * state_cap:
                    raise Timeout()           # guard memory before Pareto pruning
            layer = {}
            total = 0
            for runs, es in new.items():
                if es:
                    kept = _pareto(es)
                    layer[runs] = kept
                    total += len(kept)
            if beam is not None and total > beam:
                scored = []
                for runs, es in layer.items():
                    for e in es:
                        u = ub(k + 1, budget - e[0])
                        scored.append((e[1] + (u or 0), runs, e))
                scored.sort(key=lambda t: (-t[0], t[2][0]))
                layer = defaultdict(list)
                for _, runs, e in scored[:beam]:
                    layer[runs].append(e)
                layer = {r: sorted(es, key=lambda e: e[0]) for r, es in layer.items()}
            elif total > state_cap:
                raise Timeout()
            k += 1
            if not layer:
                return None

        finals = [e for es in layer.values() for e in es]
        if not finals:
            return None
        best = max(finals, key=lambda e: (e[1], -e[0]))
        masks, path = [], best[2]
        while path is not None:
            path, m = path
            masks.append(m)
        masks.reverse()
        return {"best": (best[1], best[0], masks),
                "min_fuel": min(e[0] for e in finals)}

    def respects_rules(self, masks, budget, max_dark):
        """Re-check an engine's roster: capacity, fuel budget, dark runs."""
        kws = [s["kw"] for s in self.elig]
        fuel, runs = 0, [0] * len(kws)
        for h in range(SLOTS):
            if self.grid[h]:
                runs = [0] * len(kws)
                continue
            mask = masks[self.outage.index(h)]
            load = self.mand_kw + sum(kw for i, kw in enumerate(kws) if mask >> i & 1)
            lv = fuel_level(load, self.levels)
            if lv is None:
                return False
            fuel += lv[1]
            runs = [0 if mask >> i & 1 else r + 1 for i, r in enumerate(runs)]
            if max_dark is not None and any(r > max_dark for r in runs):
                return False
        return fuel <= budget

    def masks_to_sets(self, masks):
        """outage hour -> set of powered shop ids."""
        out = {}
        for h, m in zip(self.outage, masks):
            on = {s["id"] for s in self.mand}
            on |= {s["id"] for i, s in enumerate(self.elig) if m >> i & 1}
            out[h] = on
        return out


def _pareto(entries):
    """Keep entries not beaten on both fuel (lower) and value (higher). Sorted by fuel."""
    entries.sort(key=lambda e: (e[0], -e[1]))
    kept, best = [], -1
    for e in entries:
        if e[1] > best:
            kept.append(e)
            best = e[1]
    return kept


def _pareto_lists(points):
    points.sort(key=lambda t: (t[0], -t[1]))
    costs, vals, best = [], [], -1
    for c, v in points:
        if v > best:
            costs.append(c)
            vals.append(v)
            best = v
    return costs, vals


# ---------------------------------------------------------------------------
def optimise(m, budget, max_dark, deadline, minimise_fuel=False):
    """One call = "best roster under these rules".
    Returns dict(best=(value, fuel, masks), optimal=bool) or None if no roster
    satisfies the rules. max_dark=None ignores the dark-run rule.
    With minimise_fuel=True the roster uses the least diesel (value ignored)."""
    left = lambda: max(0.5, deadline - time.monotonic())
    if engine_name() == "ilp":
        try:
            r = solve_ilp(m, budget, max_dark, minimise_fuel, time_limit=left())
        except TimeoutError:
            raise Timeout()
        if r is None or m.respects_rules(r["best"][2], budget, max_dark):
            return r
        # numerical surprise (never seen): fall through to the DP engine

    if minimise_fuel:
        r = m.search(10 ** 12, max_dark, deadline=deadline)
        if r is None:
            return None
        return {"best": (None, r["min_fuel"], None), "optimal": True}

    quick = m.search(budget, max_dark, beam=300, deadline=deadline)
    lb = quick["best"][0] if quick else None
    try:
        exact = m.search(budget, max_dark, lower_bound=lb, deadline=deadline)
        optimal = True
    except Timeout:
        exact, optimal = None, False
    if exact:
        return {"best": exact["best"], "optimal": True}
    if quick:                 # beam already optimal (exact found nothing better) or timed out
        return {"best": quick["best"], "optimal": optimal}
    if optimal:
        return None
    raise Timeout()


def solve(p, time_limit=9.0):
    """Main entry. Returns one of
       {"status": "ok", "on": {hour: set(ids)}, "value", "fuel", "optimal", "engine", "model"}
       {"status": "infeasible", "conflicts": [str], "best_effort": {...} or None, "model"}
    """
    m = Model(p)
    if not m.outage:                                   # rule 1: nothing to decide
        return {"status": "ok", "on": {}, "value": 0, "fuel": 0, "optimal": True,
                "engine": engine_name(), "model": m}

    conflicts = obvious_conflicts(m)
    if conflicts:
        return _infeasible(m, conflicts, time.monotonic() + time_limit)

    # Time plan (API must answer < 10 s): 60% optimise, then diagnosis, then best effort.
    start = time.monotonic()
    try:
        r = optimise(m, p["budget"], p["max_dark"], start + 0.6 * time_limit)
    except Timeout:
        return _infeasible(m, ["Search limit reached before any valid roster was found."],
                           start + time_limit)
    if r is None:
        msgs, min_fuel = deeper_conflicts(m, start + 0.85 * time_limit)
        return _infeasible(m, msgs, start + time_limit, min_fuel)
    value, fuel, masks = r["best"]
    return {"status": "ok", "on": m.masks_to_sets(masks), "value": value, "fuel": fuel,
            "optimal": r["optimal"], "engine": engine_name(), "model": m}


# ---- infeasibility (rule 5) -----------------------------------------------
def _l(h):
    return f"{h / 100:.2f} L"


def obvious_conflicts(m):
    """Conflicts visible without searching."""
    p, out = m.p, []
    hours = ", ".join(hour_label(h) for h in m.outage)
    if m.mand_kw > m.cap:
        parts = " + ".join(f"{s['id']} {s['kw']} kW" for s in m.mand)
        out.append(f"Capacity vs mandatory (rules 3, 5): {parts} = {m.mand_kw} kW > "
                   f"{m.cap} kW generator, in every outage hour ({hours}).")
        return out
    cheapest = min(c for _, _, c in m.cands)
    need = cheapest * len(m.outage)
    if need > p["budget"]:
        parts = " + ".join(f"{s['id']} {s['kw']} kW" for s in m.mand) or "no shops"
        out.append(f"Fuel vs mandatory (rules 4, 5): mandatory load ({parts}) costs at least "
                   f"{_l(cheapest)}/h x {len(m.outage)} outage hours = {_l(need)} > "
                   f"budget {_l(p['budget'])}.")
        return out
    for blk in blocks_of(m.grid):
        if len(blk) > p["max_dark"]:
            for s in m.never:
                why = (f"more than the {m.cap} kW generator" if s["kw"] > m.cap else
                       f"but only {m.free_kw} kW is free after mandatory shops ({m.mand_kw} kW)")
                out.append(f"Dark-run vs capacity (rules 3, 6): {s['id']} needs {s['kw']} kW, "
                           f"{why}, so it is dark all of {hour_label(blk[0])}-{hour_label(blk[-1]+1)} "
                           f"({len(blk)} h > max {p['max_dark']} in a row).")
    return out


def deeper_conflicts(m, deadline):
    """Simple checks passed but no roster exists: the dark-run rule clashes with
    capacity or with diesel. Returns (messages, min_fuel or None)."""
    p = m.p
    try:
        need = optimise(m, 10 ** 12, p["max_dark"], deadline, minimise_fuel=True)
    except Timeout:
        need = None
    if need is None:
        bad = []
        for blk in blocks_of(m.grid):
            sub = Model(dict(p, grid=[h not in blk for h in range(SLOTS)]))
            try:
                if optimise(sub, 10 ** 12, p["max_dark"], deadline, minimise_fuel=True) is None:
                    bad.append(f"{hour_label(blk[0])}-{hour_label(blk[-1]+1)}")
            except Timeout:
                pass
        where = ", ".join(bad) or "the outage hours"
        return [f"Dark-run vs capacity (rules 3, 6): in {where} no choice of shops keeps every "
                f"normal shop dark at most {p['max_dark']} h in a row within {m.cap} kW "
                f"({m.free_kw} kW free after mandatory shops)."], None
    need = need["best"][1]
    return [f"Dark-run vs fuel (rules 4, 6): keeping every normal shop dark at most "
            f"{p['max_dark']} h in a row needs at least {_l(need)} of diesel; "
            f"budget is {_l(p['budget'])} ({_l(need - p['budget'])} short)."], need


def _infeasible(m, conflicts, deadline, min_fuel=None):
    """Attach a labelled best-effort roster (rule 5 allows it):
    - diesel short  -> obey every rule except the budget, using the least diesel that works;
    - otherwise     -> obey capacity, diesel and mandatory, ignore the dark-run rule."""
    p = m.p
    best_effort = None
    if m.cands and m.outage:
        deadline = max(deadline, time.monotonic() + 0.5)
        if min_fuel is not None:
            budget, max_dark = min_fuel, p["max_dark"]
            label = (f"fuel budget exceeded: needs {_l(min_fuel)}, "
                     f"{_l(min_fuel - p['budget'])} more than the {_l(p['budget'])} available")
        else:
            budget, max_dark = p["budget"], None
            label = "dark-run rule (rule 6) ignored"
        try:
            r = optimise(m, budget, max_dark, deadline)
        except Timeout:
            r = None
        if r:
            v, f, masks = r["best"]
            best_effort = {"on": m.masks_to_sets(masks), "value": v, "fuel": f,
                           "relaxed": label, "budget": budget}
    return {"status": "infeasible", "conflicts": conflicts,
            "best_effort": best_effort, "model": m}
