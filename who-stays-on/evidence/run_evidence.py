"""Re-run every evidence input THROUGH THE API and save the outputs.

Start the app first (python app.py), then:
    python evidence/run_evidence.py                      # uses http://localhost:8000
    python evidence/run_evidence.py http://localhost:8001

Writes  evidence/boundary/<name>.output.json  and  evidence/SUMMARY.md, and
checks every 'ok' output with the independent checker (tests/checker.py).
"""
import glob
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tests"))
from checker import check  # noqa: E402


def post(url, body):
    req = urllib.request.Request(url + "/api/roster", data=body,
                                 headers={"Content-Type": "application/json"})
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read()), time.time() - t
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read()), time.time() - t


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    lines = ["# Boundary checks (run through POST /api/roster)", "",
             "| input | HTTP | status | value | diesel | checker | time | note |",
             "|---|---|---|---|---|---|---|---|"]
    for path in sorted(glob.glob(os.path.join(HERE, "boundary", "b*.json"))):
        if path.endswith(".output.json"):
            continue
        body = open(path, "rb").read()
        code, out, dt = post(url, body)
        with open(path.replace(".json", ".output.json"), "w") as f:
            json.dump(out, f, indent=2)
        chk = "-"
        if out.get("status") == "ok":
            errs = check(json.loads(body), out)
            chk = "OK" if not errs else "FAIL: " + "; ".join(errs)
        note = (out.get("message") or out.get("note") or "")[:110]
        lines.append(f"| {os.path.basename(path)} | {code} | {out.get('status')} | "
                     f"{out.get('value_total', '-')} | {out.get('fuel_total_litres', '-')} | "
                     f"{chk} | {dt:.2f}s | {note} |")
        print(lines[-1])
    with open(os.path.join(HERE, "SUMMARY.md"), "w") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
