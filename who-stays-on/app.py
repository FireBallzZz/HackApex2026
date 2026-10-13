"""Start the app:  python app.py        (PORT env var overrides 8000)

Serves the screen at  http://localhost:8000/
The roster API        POST /api/roster      body = input JSON -> output JSON
                      200 for ok / infeasible, 400 for invalid_input.
Database (SQLite, data/shapla.db):
  GET    /api/runs              past rosters (newest first, summary only)
  GET    /api/runs/<id>         one past roster with its full input and output
  DELETE /api/runs/<id>
  GET    /api/setups            saved market setups
  GET    /api/setups/<id>       one setup's input JSON
  POST   /api/setups            {"name": "...", "input": {...}}  save / overwrite by name
  DELETE /api/setups/<id>
Standard library only (plus scipy if installed, used by the solver). No internet.
"""
import json
import os
import sys
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import unquote, urlparse, parse_qs

from roster import db
from roster.api import run
from roster.solver import engine_name
from roster.validate import validate, InvalidInput

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(ROOT, "static")
SAMPLE = os.path.join(ROOT, "inputs", "sample_input.json")
FILES = {"/": ("index.html", "text/html; charset=utf-8"),
         "/index.html": ("index.html", "text/html; charset=utf-8"),
         "/sample_input.json": ("../inputs/sample_input.json", "application/json")}
MAX_BODY = 1_000_000


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json", extra=None):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")   # other markets may call it
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Run-Label")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Expose-Headers", "X-Run-Id")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, obj, extra=None):
        self._send(code, json.dumps(obj, indent=2), extra=extra)

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n > MAX_BODY:
            raise ValueError("body too large")
        return self.rfile.read(n)

    def _route(self):
        """('runs', '12') for /api/runs/12 ; ('runs', None) for /api/runs."""
        parts = [unquote(p) for p in urlparse(self.path).path.split("/") if p]
        if len(parts) >= 2 and parts[0] == "api":
            return parts[1], (parts[2] if len(parts) > 2 else None)
        return None, None

    def do_OPTIONS(self):
        self._send(204, b"")

    def do_GET(self):
        path = urlparse(self.path).path
        if path in FILES:
            name, ctype = FILES[path]
            with open(os.path.join(STATIC, name), "rb") as f:
                return self._send(200, f.read(), ctype)
        what, ident = self._route()
        try:
            if what == "health":
                return self._json(200, {"ok": True, "engine": engine_name(), "database": db.DB_PATH})
            if what == "runs" and ident is None:
                limit = parse_qs(urlparse(self.path).query).get("limit", ["50"])[0]
                return self._json(200, db.list_runs(min(int(limit), 500)))
            if what == "runs":
                r = db.get_run(ident)
                return self._json(200, r) if r else self._json(404, {"error": "run not found"})
            if what == "setups" and ident is None:
                return self._json(200, db.list_setups())
            if what == "setups":
                s = db.get_setup(ident)
                return self._json(200, s) if s else self._json(404, {"error": "setup not found"})
        except ValueError:
            return self._json(400, {"error": "bad id"})
        self._json(404, {"error": "not found"})

    def do_DELETE(self):
        what, ident = self._route()
        try:
            if what == "runs" and ident:
                return self._json(200 if db.delete_run(ident) else 404, {"deleted": ident})
            if what == "setups" and ident:
                return self._json(200 if db.delete_setup(ident) else 404, {"deleted": ident})
        except ValueError:
            return self._json(400, {"error": "bad id"})
        self._json(404, {"error": "not found"})

    def do_POST(self):
        what, _ = self._route()
        try:
            raw = self._body()
        except ValueError:
            return self._json(400, {"status": "invalid_input", "message": "input: body too large"})

        if what == "setups":
            try:
                body = json.loads(raw.decode("utf-8"))
                name = str(body.get("name", "")).strip()
                if not name:
                    return self._json(400, {"error": "name: required"})
                validate(body.get("input"))          # only valid inputs are saved
                return self._json(200, {"id": db.save_setup(name[:80], body["input"]), "name": name[:80]})
            except InvalidInput as e:
                return self._json(400, {"error": f"input: {e}"})
            except (UnicodeDecodeError, ValueError, AttributeError) as e:
                return self._json(400, {"error": f"not valid JSON ({e})"})

        if what != "roster":
            return self._json(404, {"error": "not found"})
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as e:
            return self._json(400, {"status": "invalid_input", "message": f"input: not valid JSON ({e})"})
        try:
            code, out = run(data)
        except Exception as e:   # a bug, not the caller's fault: keep the server up, say so
            code, out = 500, {"status": "error", "message": f"internal error: {e}"}
        extra = {}
        try:                     # record the run; the response is the same with or without it
            extra["X-Run-Id"] = str(db.save_run(unquote(self.headers.get("X-Run-Label") or ""), data, out))
        except Exception as e:
            sys.stderr.write(f"database: could not save run ({e})\n")
        self._json(code, out, extra)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.command, fmt % args))


def main():
    db.init(seed_path=SAMPLE)
    port = int(os.environ.get("PORT", "8000"))
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Who Stays On? running on http://localhost:{port}/  (engine: {engine_name()}, database: {db.DB_PATH})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
