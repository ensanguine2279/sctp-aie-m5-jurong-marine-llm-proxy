"""Print spend vs budget for the team and each member key.

    python spend_report.py

Needs keys.json (created by setup_keys.py). The web dashboard at
<PROXY_URL>/ui shows the same numbers with charts and per-request logs.
"""
import json
import urllib.parse

from proxy_admin import HERE, PROXY_URL, call


def info_block(res, *names):
    """LiteLLM wraps details under 'info' / 'team_info'; fall back to the top level."""
    for n in names:
        if isinstance(res.get(n), dict):
            return res[n]
    return res


def bar(spent, budget, width=20):
    if not budget:
        return " " * width + "  (no cap)"
    pct = spent / budget
    filled = min(width, int(pct * width))
    flag = "  OVER" if pct >= 1 else ("  !" if pct >= 0.8 else "")
    return "#" * filled + "." * (width - filled) + f" {pct:5.0%}{flag}"


def main():
    saved = json.loads((HERE / "keys.json").read_text())

    team = info_block(
        call("GET", "/team/info?team_id=" + urllib.parse.quote(saved["team_id"])), "team_info"
    )
    t_spent, t_budget = float(team.get("spend") or 0), team.get("max_budget")
    print(f"Proxy: {PROXY_URL}\n")
    print(f"TEAM  {team.get('team_alias', 'team'):<15} ${t_spent:8.4f} / ${t_budget or '-':<6} {bar(t_spent, t_budget)}")
    print("-" * 72)

    for alias, key in saved["keys"].items():
        k = info_block(call("GET", "/key/info?key=" + urllib.parse.quote(key)), "info")
        spent, budget = float(k.get("spend") or 0), k.get("max_budget")
        print(f"      {alias:<15} ${spent:8.4f} / ${budget or '-':<6} {bar(spent, budget)}")

    print("\nCosts are LiteLLM's estimates from OpenAI's list prices, not OpenAI's bill.")


if __name__ == "__main__":
    main()
