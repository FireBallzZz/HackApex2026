"""One-line reason for every dark cell.

Why these reasons are always the real rule: in an optimal roster, switching a
dark shop ON in an hour only changes that hour's load and fuel (its own dark
run can only get shorter, values are >= 0). So if it fitted the capacity AND
the extra fuel fitted the budget, the optimum would have switched it on.
Therefore every dark shop is dark because of exactly one of:
  - it can never fit (too big for the generator / for what mandatory shops leave),
  - capacity in this hour,
  - the extra diesel would break the day's budget,
  - it is worth 0 in this hour.
"""
from .solver import fuel_level


def L(h):
    return f"{h / 100:.2f} L"


def reason(m, shop, h, load, cost, fuel_total, budget, optimal=True):
    kw, cap, v = shop["kw"], m.cap, shop["values"][h]
    if kw > cap:
        return f"Never fits: needs {kw} kW, the generator carries only {cap} kW."
    if kw > m.free_kw:
        return (f"Never fits: needs {kw} kW, only {m.free_kw} kW is left after "
                f"mandatory shops take {m.mand_kw} kW of {cap} kW.")
    if load + kw > cap:
        over = load + kw - cap
        tail = (" No swap that frees the room scores higher for the day without breaking a rule."
                if optimal else "")
        return (f"Capacity: {load} kW on + {kw} kW = {load + kw} kW > {cap} kW limit; "
                f"{over} kW would have to go. Worth {v} here.{tail}")
    _, new_cost = fuel_level(load + kw, m.levels)
    extra = new_cost - cost
    if fuel_total + extra > budget:
        return (f"Fuel: adding {kw} kW lifts this hour {load}->{load + kw} kW "
                f"({L(cost)}->{L(new_cost)}, +{L(extra)}); the day would need "
                f"{L(fuel_total + extra)} > {L(budget)} budget. Worth only {v} here, "
                f"the diesel buys more value in other hours.")
    if v == 0:
        return "Worth 0 in this hour: powering it adds no value."
    return (f"Not chosen (would fit: {load + kw} kW, +{L(extra)}, worth {v}); "
            f"roster is best-effort / time-limited, not proven optimal.")
