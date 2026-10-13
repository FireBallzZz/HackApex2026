"""input JSON -> (HTTP status, output JSON). Used by the web server AND the CLI.

The output format lives only in this file (_roster_json / run), so it can be
matched to schema.md in one place.
"""
from .validate import validate, InvalidInput
from .solver import solve, fuel_level, hour_label, SLOTS
from .explain import reason


def _litres(h):
    return round(h / 100, 2)


def _roster_json(m, on, budget=None):
    """Build roster entries + totals from 'on' (hour -> set of powered ids).
    Totals are RECOMPUTED here from the roster itself (rule 8)."""
    p = m.p
    shops = p["shops"]
    budget = p["budget"] if budget is None else budget
    ids = [s["id"] for s in shops]

    # pass 1: load / fuel per hour and day total
    per_hour, fuel_total, value_total = {}, 0, 0
    for h in m.outage:
        powered = on.get(h, set())
        load = sum(s["kw"] for s in shops if s["id"] in powered)
        lv = fuel_level(load, m.levels)
        cost = lv[1] if lv else None
        per_hour[h] = (load, cost)
        fuel_total += cost or 0
        value_total += sum(s["values"][h] for s in shops if s["id"] in powered)

    # pass 2: entries with reasons
    roster, running = [], 0
    for h in m.outage:
        powered = on.get(h, set())
        load, cost = per_hour[h]
        running += cost or 0
        roster.append({
            "slot": h,
            "hour": hour_label(h),
            "powered": [i for i in ids if i in powered],
            "dark": [{"id": s["id"],
                      "reason": reason(m, s, h, load, cost or 0, fuel_total,
                                       budget, m_optimal(m))}
                     for s in shops if s["id"] not in powered],
            "load_kw": load,
            "fuel_litres": _litres(cost or 0),
            "fuel_running_litres": _litres(running),
        })

    # dark_hours: all dark outage hours per shop (mandatory -> 0)
    dark_hours = {i: 0 for i in ids}
    for h in m.outage:
        for i in ids:
            if i not in on.get(h, set()):
                dark_hours[i] += 1
    return roster, value_total, fuel_total, dark_hours


def m_optimal(m):
    return getattr(m, "optimal", True)


def run(data, time_limit=9.0):
    try:
        p = validate(data)
    except InvalidInput as e:
        return 400, {"status": "invalid_input", "message": str(e)}

    res = solve(p, time_limit=time_limit)
    m = res["model"]

    if res["status"] == "ok":
        m.optimal = res["optimal"]
        roster, value, fuel, dark = _roster_json(m, res["on"])
        out = {"status": "ok", "roster": roster, "value_total": value,
               "fuel_total_litres": _litres(fuel), "dark_hours": dark}
        if not res["optimal"]:
            out["note"] = "Time limit reached: best roster found, not proven optimal."
        return 200, out

    out = {"status": "infeasible",
           "message": " ".join(res["conflicts"]),
           "conflicts": res["conflicts"]}
    be = res.get("best_effort")
    if be:
        m.optimal = False
        roster, value, fuel, dark = _roster_json(m, be["on"], be["budget"])
        out["best_effort"] = {
            "label": "BEST EFFORT - NOT VALID: " + be["relaxed"],
            "roster": roster, "value_total": value,
            "fuel_total_litres": _litres(fuel), "dark_hours": dark}
    return 200, out
