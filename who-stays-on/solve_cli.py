"""Command line: python solve_cli.py input.json [output.json]
Exit code 0 for ok / infeasible, 2 for invalid_input (rule 8)."""
import json
import sys
from roster.api import run


def main():
    if len(sys.argv) < 2:
        print("usage: python solve_cli.py input.json [output.json]", file=sys.stderr)
        return 2
    try:
        with open(sys.argv[1], encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        code, out = 400, {"status": "invalid_input", "message": f"input: not readable JSON ({e})"}
    else:
        code, out = run(data)
    text = json.dumps(out, indent=2)
    if len(sys.argv) > 2:
        with open(sys.argv[2], "w", encoding="utf-8") as f:
            f.write(text + "\n")
    print(text)
    return 2 if code == 400 else 0


if __name__ == "__main__":
    sys.exit(main())
