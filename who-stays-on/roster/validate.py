"""Input validation (rule 2, rule 9).

Anything that does not match the input format raises InvalidInput with a
message that names the offending field. Litres are converted to whole
hundredths (ints) so every fuel sum later is exact - no float rounding.
"""
from decimal import Decimal, InvalidOperation
import math

SLOTS = 10
MAX_SHOPS = 12


class InvalidInput(Exception):
    pass


def _whole(x, field, minimum):
    """Whole number >= minimum. 3 and 3.0 are accepted, 3.5 / "3" / true are not."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise InvalidInput(f"{field}: must be a whole number, got {x!r}")
    if isinstance(x, float):
        if not math.isfinite(x) or x != int(x):
            raise InvalidInput(f"{field}: must be a whole number, got {x!r}")
        x = int(x)
    if x < minimum:
        raise InvalidInput(f"{field}: must be >= {minimum}, got {x}")
    return x


def _hundredths(x, field):
    """Litres -> whole hundredths of a litre. Rejects negatives and >2 decimals."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise InvalidInput(f"{field}: must be a number of litres, got {x!r}")
    if isinstance(x, float) and not math.isfinite(x):
        raise InvalidInput(f"{field}: must be a finite number")
    if x < 0:
        raise InvalidInput(f"{field}: must not be negative, got {x}")
    try:
        d = Decimal(repr(x)) * 100
    except InvalidOperation:
        raise InvalidInput(f"{field}: not a valid number")
    if d != d.to_integral_value():
        raise InvalidInput(f"{field}: more than two decimal places ({x})")
    return int(d)


def _need(obj, key, where):
    if key not in obj:
        raise InvalidInput(f"{where}{key}: missing")
    return obj[key]


def validate(data):
    """Return a normalised problem dict, or raise InvalidInput."""
    if not isinstance(data, dict):
        raise InvalidInput("input: must be a JSON object")

    grid = _need(data, "grid_available", "")
    if not isinstance(grid, list) or len(grid) != SLOTS:
        raise InvalidInput(f"grid_available: must be a list of exactly {SLOTS} booleans")
    for i, g in enumerate(grid):
        if not isinstance(g, bool):
            raise InvalidInput(f"grid_available[{i}]: must be true or false, got {g!r}")

    cap = _whole(_need(data, "generator_capacity_kw", ""), "generator_capacity_kw", 1)
    budget = _hundredths(_need(data, "fuel_budget_litres", ""), "fuel_budget_litres")
    max_dark = _whole(_need(data, "max_consecutive_dark", ""), "max_consecutive_dark", 0)

    table = _need(data, "fuel_table", "")
    if not isinstance(table, list) or not table:
        raise InvalidInput("fuel_table: must be a non-empty list")
    levels = []
    prev = 0
    for i, row in enumerate(table):
        where = f"fuel_table[{i}]."
        if not isinstance(row, dict):
            raise InvalidInput(f"fuel_table[{i}]: must be an object")
        kw = _whole(_need(row, "load_kw", where), where + "load_kw", 1)
        lit = _hundredths(_need(row, "litres_per_hour", where), where + "litres_per_hour")
        if kw <= prev:
            raise InvalidInput(f"{where}load_kw: levels must be strictly increasing ({kw} after {prev})")
        prev = kw
        levels.append((kw, lit))
    if levels[-1][0] != cap:
        raise InvalidInput(
            f"fuel_table: last load_kw ({levels[-1][0]}) must equal generator_capacity_kw ({cap})")

    shops = _need(data, "shops", "")
    if not isinstance(shops, list):
        raise InvalidInput("shops: must be a list")
    if len(shops) > MAX_SHOPS:
        raise InvalidInput(f"shops: at most {MAX_SHOPS} shops, got {len(shops)}")
    out_shops, seen = [], set()
    for i, s in enumerate(shops):
        where = f"shops[{i}]."
        if not isinstance(s, dict):
            raise InvalidInput(f"shops[{i}]: must be an object")
        sid = _need(s, "id", where)
        if not isinstance(sid, str) or not sid.strip():
            raise InvalidInput(f"{where}id: must be a non-blank string")
        if sid in seen:
            raise InvalidInput(f"{where}id: duplicate id {sid!r}")
        seen.add(sid)
        kw = _whole(_need(s, "kw", where), where + "kw", 1)
        typ = _need(s, "type", where)
        if typ not in ("mandatory", "normal"):
            raise InvalidInput(f"{where}type: must be 'mandatory' or 'normal', got {typ!r}")
        vals = _need(s, "value_per_slot", where)
        if not isinstance(vals, list) or len(vals) != SLOTS:
            raise InvalidInput(f"{where}value_per_slot: must be a list of exactly {SLOTS} numbers")
        vals = [_whole(v, f"{where}value_per_slot[{j}]", 0) for j, v in enumerate(vals)]
        out_shops.append({"id": sid, "kw": kw, "type": typ, "values": vals})

    return {
        "grid": grid,
        "cap": cap,
        "budget": budget,          # hundredths of a litre
        "levels": levels,          # [(load_kw, hundredths per hour)], increasing
        "max_dark": max_dark,
        "shops": out_shops,
    }
