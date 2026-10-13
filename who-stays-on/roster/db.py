"""SQLite storage (Python standard library - no server, no install, works offline).

Two tables:
  setups  - a market's saved configuration (shops, generator, fuel table, ...) so the
            committee does not retype twelve shops every day. One row per name.
  runs    - every roster the API has produced: when, status, totals, and the full
            input and output JSON, so any past day can be reopened or audited.

The file lives at data/shapla.db (override with the DB_PATH environment variable).
Saving is best-effort: if the database fails, the roster API still answers.
"""
import json
import os
import sqlite3
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("DB_PATH", os.path.join(ROOT, "data", "shapla.db"))
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS setups (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    input_json  TEXT    NOT NULL,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at         TEXT    NOT NULL,
    label              TEXT,
    status             TEXT    NOT NULL,
    value_total        INTEGER,
    fuel_total_litres  REAL,
    outage_hours       INTEGER,
    shop_count         INTEGER,
    input_json         TEXT    NOT NULL,
    output_json        TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS runs_created ON runs(created_at);
"""


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _connect():
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def init(seed_path=None):
    """Create the file and tables if missing; seed the sample market once."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with _lock, _connect() as c:
        c.executescript(SCHEMA)
        empty = c.execute("SELECT COUNT(*) FROM setups").fetchone()[0] == 0
    if empty and seed_path and os.path.exists(seed_path):
        with open(seed_path, encoding="utf-8") as f:
            data = json.load(f)
        data.pop("_story", None)
        save_setup("Shapla Shopping Complex (sample)", data)


# ---- runs ------------------------------------------------------------------
def save_run(label, inp, out):
    grid = inp.get("grid_available") if isinstance(inp, dict) else None
    shops = inp.get("shops") if isinstance(inp, dict) else None
    row = (_now(), (label or "")[:120] or None, out.get("status", "?"),
           out.get("value_total"), out.get("fuel_total_litres"),
           sum(1 for g in grid if g is False) if isinstance(grid, list) else None,
           len(shops) if isinstance(shops, list) else None,
           json.dumps(inp), json.dumps(out))
    with _lock, _connect() as c:
        cur = c.execute("""INSERT INTO runs (created_at, label, status, value_total, fuel_total_litres,
                           outage_hours, shop_count, input_json, output_json)
                           VALUES (?,?,?,?,?,?,?,?,?)""", row)
        return cur.lastrowid


def list_runs(limit=50):
    with _lock, _connect() as c:
        rows = c.execute("""SELECT id, created_at, label, status, value_total, fuel_total_litres,
                            outage_hours, shop_count FROM runs ORDER BY id DESC LIMIT ?""",
                         (int(limit),)).fetchall()
    return [dict(r) for r in rows]


def get_run(run_id):
    with _lock, _connect() as c:
        r = c.execute("SELECT * FROM runs WHERE id = ?", (int(run_id),)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["input"] = json.loads(d.pop("input_json"))
    d["output"] = json.loads(d.pop("output_json"))
    return d


def delete_run(run_id):
    with _lock, _connect() as c:
        return c.execute("DELETE FROM runs WHERE id = ?", (int(run_id),)).rowcount > 0


# ---- setups ----------------------------------------------------------------
def save_setup(name, inp):
    """Insert, or overwrite the setup with the same name. Returns its id."""
    now = _now()
    with _lock, _connect() as c:
        c.execute("""INSERT INTO setups (name, input_json, created_at, updated_at) VALUES (?,?,?,?)
                     ON CONFLICT(name) DO UPDATE SET input_json = excluded.input_json,
                                                     updated_at = excluded.updated_at""",
                  (name, json.dumps(inp), now, now))
        return c.execute("SELECT id FROM setups WHERE name = ?", (name,)).fetchone()[0]


def list_setups():
    with _lock, _connect() as c:
        rows = c.execute("SELECT id, name, input_json, updated_at FROM setups ORDER BY updated_at DESC, id DESC").fetchall()
    out = []
    for r in rows:
        inp = json.loads(r["input_json"])
        out.append({"id": r["id"], "name": r["name"], "updated_at": r["updated_at"],
                    "shop_count": len(inp.get("shops", []))})
    return out


def get_setup(setup_id):
    with _lock, _connect() as c:
        r = c.execute("SELECT id, name, input_json, updated_at FROM setups WHERE id = ?", (int(setup_id),)).fetchone()
    if not r:
        return None
    return {"id": r["id"], "name": r["name"], "updated_at": r["updated_at"], "input": json.loads(r["input_json"])}


def delete_setup(setup_id):
    with _lock, _connect() as c:
        return c.execute("DELETE FROM setups WHERE id = ?", (int(setup_id),)).rowcount > 0
