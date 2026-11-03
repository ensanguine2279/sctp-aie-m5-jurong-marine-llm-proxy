"""Daily token usage and cost from the LiteLLM proxy database.

Run on the VM, in the kit folder (it queries Postgres through docker compose):

    python3 daily_report.py                    # last 7 days, per member
    python3 daily_report.py --days 30          # last 30 days
    python3 daily_report.py --by model         # per model instead of per member
    python3 daily_report.py --by member,model  # per member AND model
    python3 daily_report.py --by day           # one total per day
    python3 daily_report.py --csv usage.csv    # also save the rows as CSV

Dates are Singapore dates by default (--tz to change). Costs are LiteLLM's
estimates (see README, "How accurate is the cost tracking?").
Needs per-request logging, i.e. NOT `disable_spend_logs: true` in config.yaml.
Standard library only, no installs needed.
"""
import argparse
import csv
import io
import os
import re
import shlex
import subprocess
import sys

from proxy_admin import HERE

GROUPINGS = {
    "day": [],
    "member": ["member"],
    "model": ["model"],
    "member,model": ["member", "model"],
}
COLUMN_SQL = {
    "member": "COALESCE(v.key_alias, '(unknown/deleted)')",
    "model": "s.model",
}
NUMERIC = ("calls", "input_tokens", "output_tokens", "total_tokens", "cost_usd")


def build_query(days, tz, dims):
    day = f"""date(s."startTime" AT TIME ZONE 'UTC' AT TIME ZONE '{tz}')"""
    select = [f"{day} AS day"] + [f"{COLUMN_SQL[d]} AS {d}" for d in dims]
    return f"""
COPY (
  SELECT {", ".join(select)},
         COUNT(*)                                    AS calls,
         COALESCE(SUM(s.prompt_tokens), 0)           AS input_tokens,
         COALESCE(SUM(s.completion_tokens), 0)       AS output_tokens,
         COALESCE(SUM(s.total_tokens), 0)            AS total_tokens,
         ROUND(COALESCE(SUM(s.spend), 0)::numeric, 6) AS cost_usd
  FROM "LiteLLM_SpendLogs" s
  LEFT JOIN "LiteLLM_VerificationToken" v ON v.token = s.api_key
  WHERE s."startTime" >= (now() AT TIME ZONE 'UTC') - interval '{days} days'
  GROUP BY {", ".join(str(i + 1) for i in range(len(select)))}
  ORDER BY 1 DESC{"".join(f", {i + 2}" for i in range(len(dims)))}
) TO STDOUT WITH CSV HEADER
"""


def psql_command():
    # Default: the Postgres container from docker-compose.yml.
    # PSQL_CMD overrides it, e.g. PSQL_CMD="psql -h localhost -U litellm -d litellm".
    if os.environ.get("PSQL_CMD"):
        return shlex.split(os.environ["PSQL_CMD"])
    return ["docker", "compose", "exec", "-T", "db", "psql", "-U", "litellm", "-d", "litellm"]


def run_query(sql):
    cmd = psql_command() + ["-v", "ON_ERROR_STOP=1", "-q"]
    try:
        res = subprocess.run(cmd, input=sql, capture_output=True, text=True, cwd=HERE, timeout=60)
    except FileNotFoundError:
        sys.exit(f"Could not run '{cmd[0]}'. Run this on the proxy VM, in the kit folder.")
    if res.returncode != 0:
        err = res.stderr.strip()
        hint = ""
        if "does not exist" in err and ("relation" in err or "column" in err):
            hint = ("\nHint: LiteLLM's table/column names may differ in your version. Check with:\n"
                    "  docker compose exec db psql -U litellm -d litellm -c '\\d \"LiteLLM_SpendLogs\"'")
        elif "no such service" in err or "not running" in err:
            hint = "\nHint: is the proxy running? Try `docker compose ps`."
        sys.exit(f"Query failed:\n{err}{hint}")
    return list(csv.DictReader(io.StringIO(res.stdout)))


def to_number(v):
    return float(v) if "." in v else int(v)


def print_table(rows, dims):
    cols = ["day", *dims, *NUMERIC]
    headers = {"day": "Day", "member": "Member", "model": "Model", "calls": "Calls",
               "input_tokens": "In tokens", "output_tokens": "Out tokens",
               "total_tokens": "Total tokens", "cost_usd": "Cost (USD)"}

    def fmt(col, v):
        if col == "cost_usd":
            c = float(v)
            return "<$0.0001" if 0 < c < 0.0001 else f"${c:,.4f}"
        if col in NUMERIC:
            return f"{int(v):,}"
        return v

    body = [[fmt(c, r[c]) for c in cols] for r in rows]
    totals = {c: sum(to_number(r[c]) for r in rows) for c in NUMERIC}
    total_row = ["TOTAL"] + [""] * len(dims) + [fmt(c, totals[c]) for c in NUMERIC]

    widths = [max(len(headers[c]), *(len(b[i]) for b in body + [total_row])) for i, c in enumerate(cols)]
    right = {i for i, c in enumerate(cols) if c in NUMERIC}

    def line(cells):
        return "  ".join(cell.rjust(w) if i in right else cell.ljust(w)
                         for i, (cell, w) in enumerate(zip(cells, widths)))

    print(line([headers[c] for c in cols]))
    print("  ".join("-" * w for w in widths))
    prev_day = None
    for r, b in zip(rows, body):
        if dims and prev_day is not None and r["day"] != prev_day:
            print()
        print(line(b))
        prev_day = r["day"]
    print("  ".join("-" * w for w in widths))
    print(line(total_row))


def main():
    p = argparse.ArgumentParser(description="Daily token usage and cost from LiteLLM")
    p.add_argument("--days", type=int, default=7, help="how many days back (default 7)")
    p.add_argument("--by", choices=GROUPINGS, default="member",
                   help="break each day down by: day (totals only), member, model, member,model")
    p.add_argument("--tz", default="Asia/Singapore", help="time zone for dates (default Asia/Singapore)")
    p.add_argument("--csv", metavar="FILE", help="also write the rows to this CSV file")
    args = p.parse_args()

    if not 1 <= args.days <= 3650:
        sys.exit("--days must be between 1 and 3650")
    if not re.fullmatch(r"[A-Za-z0-9_/+\-]{1,64}", args.tz):
        sys.exit(f"Invalid time zone: {args.tz!r}")

    dims = GROUPINGS[args.by]
    rows = run_query(build_query(args.days, args.tz, dims))

    print(f"LiteLLM usage, last {args.days} day(s), dates in {args.tz}, by {args.by}\n")
    if not rows:
        print("No requests in this period. (If calls were made, check that "
              "`disable_spend_logs` is not set in config.yaml.)")
    else:
        print_table(rows, dims)
        print("\nCosts are LiteLLM's estimates from list prices, not OpenAI's bill.")

    if args.csv:
        with open(args.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["day", *dims, *NUMERIC])
            w.writeheader()
            w.writerows(rows)
        print(f"Saved {len(rows)} row(s) to {args.csv}")


if __name__ == "__main__":
    main()