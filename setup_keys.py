"""Create the team and one virtual key per member, using members.json.

Run once after the proxy is up:
    python setup_keys.py

The new keys are printed AND saved to keys.json (git-ignored). LiteLLM only
shows each key once, so send each person their own key privately.

Running it again skips members that already have a key in keys.json.
To add someone later, add them to members.json and run it again.
"""
import json

from proxy_admin import HERE, call

KEYS_FILE = HERE / "keys.json"


def main():
    cfg = json.loads((HERE / "members.json").read_text())
    saved = json.loads(KEYS_FILE.read_text()) if KEYS_FILE.exists() else {"team_id": None, "keys": {}}

    # 1. One team = the shared budget for the whole group.
    if not saved["team_id"]:
        t = cfg["team"]
        team = call("POST", "/team/new", {
            "team_alias": t["alias"],
            "max_budget": t["max_budget"],
            "budget_duration": t["budget_duration"],
        })
        saved["team_id"] = team["team_id"]
        print(f"Created team '{t['alias']}' (budget ${t['max_budget']}/{t['budget_duration']})")
    else:
        print(f"Using existing team {saved['team_id']}")

    # 2. One key per member, each with a personal cap that also counts toward the team budget.
    for m in cfg["members"]:
        alias = m["alias"]
        if alias in saved["keys"]:
            print(f"  skip  {alias:<15} (already has a key)")
            continue
        body = {
            "key_alias": alias,
            "team_id": saved["team_id"],
            "max_budget": m["max_budget"],
            "budget_duration": m.get("budget_duration", "30d"),
            "models": m.get("models", []),
            "metadata": {"member": alias},
        }
        for opt in ("rpm_limit", "tpm_limit"):
            if opt in m:
                body[opt] = m[opt]
        res = call("POST", "/key/generate", body)
        saved["keys"][alias] = res["key"]
        print(f"  made  {alias:<15} ${m['max_budget']}/{body['budget_duration']}  models={body['models'] or 'all'}")
        KEYS_FILE.write_text(json.dumps(saved, indent=2))  # save after each key

    KEYS_FILE.write_text(json.dumps(saved, indent=2))
    print(f"\nKeys saved to {KEYS_FILE.name}. Send each member ONLY their own key:\n")
    for alias, key in saved["keys"].items():
        print(f"  {alias:<15} {key}")


if __name__ == "__main__":
    main()
