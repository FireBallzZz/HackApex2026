"""Database tests (stdlib only):  python tests/test_db.py
Uses a throw-away database file, never data/shapla.db."""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
sys.path.insert(0, ROOT)

from roster import db          # noqa: E402
from roster.api import run     # noqa: E402


def main():
    sample = os.path.join(ROOT, "inputs", "sample_input.json")
    db.init(seed_path=sample)
    setups = db.list_setups()
    assert len(setups) == 1 and setups[0]["shop_count"] == 12, setups

    # save, overwrite by name, read back, delete
    inp = json.load(open(os.path.join(ROOT, "inputs", "worked_example.json")))
    sid = db.save_setup("Uttara", inp)
    inp2 = dict(inp, fuel_budget_litres=9.5)
    assert db.save_setup("Uttara", inp2) == sid, "same name must overwrite, not duplicate"
    assert db.get_setup(sid)["input"]["fuel_budget_litres"] == 9.5
    assert len(db.list_setups()) == 2
    assert db.delete_setup(sid) and db.get_setup(sid) is None

    # every run is stored with its totals and the exact input/output
    code, out = run(json.load(open(sample)))
    rid = db.save_run("Thursday", json.load(open(sample)), out)
    r = db.get_run(rid)
    assert r["status"] == "ok" and r["value_total"] == 186 and r["outage_hours"] == 7
    assert r["output"] == out and r["label"] == "Thursday"
    code, bad = run({"grid_available": [True]})
    db.save_run(None, {"grid_available": [True]}, bad)
    runs = db.list_runs()
    assert [x["status"] for x in runs] == ["invalid_input", "ok"], runs
    assert db.delete_run(rid) and db.get_run(rid) is None
    print("database: setups save/overwrite/delete OK, runs save/list/read/delete OK")
    print("ALL PASS")


if __name__ == "__main__":
    main()
