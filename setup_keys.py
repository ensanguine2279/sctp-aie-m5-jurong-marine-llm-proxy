"""Keep the proxy's teams/keys in line with members.json.

Usage (run on the VM, in the kit folder):

    python3 setup_keys.py                 # create keys for NEW members only (safe default)
    python3 setup_keys.py --sync          # make the proxy match members.json:
                                          #   - create keys for new members
                                          #   - update budget/models/limits that changed
                                          #   - update the team budget
                                          #   - BLOCK keys of members removed from the file
                                          #   - unblock members who were added back
    python3 setup_keys.py --sync --dry-run    # show what --sync would do, change nothing
    python3 setup_keys.py --sync --yes        # skip the confirmation prompt
    python3 setup_keys.py --rename OLD NEW    # rename a member everywhere, keeping their key

Keys are saved to keys.json (git-ignored). LiteLLM shows each new key only once,
so send each person their own key privately.

Never rename a member by just editing members.json: --sync would see one member
removed (blocked) and a new one added (new key, fresh budget). Use --rename.
"""
import argparse
import json
import sys

from proxy_admin import HERE, call

KEYS_FILE = HERE / "keys.json"
MEMBERS_FILE = HERE / "members.json"
LIMIT_FIELDS = ("rpm_limit", "tpm_limit")


# ---------- file helpers ----------

def load_saved():
    if KEYS_FILE.exists():
        saved = json.loads(KEYS_FILE.read_text())
    else:
        saved = {"team_id": None, "keys": {}}
    saved.setdefault("keys", {})
    saved.setdefault("blocked", {})
    return saved


def save(saved):
    KEYS_FILE.write_text(json.dumps(saved, indent=2))


def load_members():
    cfg = json.loads(MEMBERS_FILE.read_text())
    aliases = [m["alias"] for m in cfg["members"]]
    dupes = {a for a in aliases if aliases.count(a) > 1}
    if dupes:
        sys.exit(f"members.json has duplicate aliases: {', '.join(sorted(dupes))}")
    return cfg


# ---------- proxy helpers ----------

def info_block(res, *names):
    for n in names:
        if isinstance(res.get(n), dict):
            return res[n]
    return res


def desired_key_settings(m):
    return {
        "max_budget": m["max_budget"],
        "budget_duration": m.get("budget_duration", "30d"),
        "models": sorted(m.get("models", [])),
        **{f: m.get(f) for f in LIMIT_FIELDS},
    }


def ensure_team(cfg, saved, apply):
    t = cfg["team"]
    if not saved["team_id"]:
        if apply:
            team = call("POST", "/team/new", {
                "team_alias": t["alias"],
                "max_budget": t["max_budget"],
                "budget_duration": t["budget_duration"],
            })
            saved["team_id"] = team["team_id"]
            save(saved)
        print(f"  create team  {t['alias']}  ${t['max_budget']}/{t['budget_duration']}")
        return []
    return []


def create_key(m, saved):
    body = {
        "key_alias": m["alias"],
        "team_id": saved["team_id"],
        **desired_key_settings(m),
        "metadata": {"member": m["alias"]},
    }
    body = {k: v for k, v in body.items() if v is not None}
    res = call("POST", "/key/generate", body)
    saved["keys"][m["alias"]] = res["key"]
    save(saved)  # save after each key so a crash never loses one


# ---------- modes ----------

def create_only():
    cfg, saved = load_members(), load_saved()
    ensure_team(cfg, saved, apply=True)
    for m in cfg["members"]:
        a = m["alias"]
        if a in saved["keys"]:
            print(f"  skip   {a:<15} (already has a key)")
        elif a in saved["blocked"]:
            print(f"  skip   {a:<15} (blocked; use --sync to unblock)")
        else:
            create_key(m, saved)
            print(f"  made   {a:<15} ${m['max_budget']}/{m.get('budget_duration', '30d')}  models={m.get('models') or 'all'}")
    print_keys(saved)


def plan_sync(cfg, saved):
    """Work out every change needed. Returns a list of (description, action) pairs."""
    plan = []
    wanted = {m["alias"]: m for m in cfg["members"]}

    # Team
    t = cfg["team"]
    if not saved["team_id"]:
        plan.append((f"create team   {t['alias']}  ${t['max_budget']}/{t['budget_duration']}",
                     lambda: ensure_team(cfg, saved, apply=True)))
    else:
        cur = info_block(call("GET", f"/team/info?team_id={saved['team_id']}"), "team_info")
        diffs = {}
        if cur.get("max_budget") != t["max_budget"]:
            diffs["max_budget"] = (cur.get("max_budget"), t["max_budget"])
        if cur.get("budget_duration") != t["budget_duration"]:
            diffs["budget_duration"] = (cur.get("budget_duration"), t["budget_duration"])
        if diffs:
            body = {"team_id": saved["team_id"], **{k: new for k, (_, new) in diffs.items()}}
            plan.append((f"update team   {t['alias']}  " + fmt_diffs(diffs),
                         lambda body=body: call("POST", "/team/update", body)))

    # Members in the file
    for a, m in wanted.items():
        if a in saved["keys"]:
            cur = info_block(call("GET", f"/key/info?key={saved['keys'][a]}"), "info")
            want = desired_key_settings(m)
            diffs = {}
            for f, new in want.items():
                old = cur.get(f)
                if f == "models":
                    old = sorted(old or [])
                if old != new:
                    diffs[f] = (old, new)
            if diffs:
                body = {"key": saved["keys"][a], **{k: new for k, (_, new) in diffs.items()}}
                plan.append((f"update        {a:<15} " + fmt_diffs(diffs),
                             lambda body=body: call("POST", "/key/update", body)))
        elif a in saved["blocked"]:
            def unblock(a=a, m=m):
                key = saved["blocked"].pop(a)
                call("POST", "/key/unblock", {"key": key})
                call("POST", "/key/update", {"key": key, **desired_key_settings(m)})
                saved["keys"][a] = key
                save(saved)
            plan.append((f"UNBLOCK       {a:<15} (was removed, now back in members.json)", unblock))
        else:
            def create(m=m):
                create_key(m, saved)
            plan.append((f"create key    {a:<15} ${m['max_budget']}/{m.get('budget_duration', '30d')}  "
                         f"models={m.get('models') or 'all'}", create))

    # Keys no longer in the file -> block (not delete, so spend history is kept)
    removed = [a for a in saved["keys"] if a not in wanted]
    for a in removed:
        def block(a=a):
            key = saved["keys"].pop(a)
            call("POST", "/key/block", {"key": key})
            saved["blocked"][a] = key
            save(saved)
        plan.append((f"BLOCK         {a:<15} (not in members.json)", block))

    new_aliases = [a for a in wanted if a not in saved["keys"] and a not in saved["blocked"]]
    return plan, removed, new_aliases


def fmt_diffs(diffs):
    return ", ".join(f"{k}: {old!r} -> {new!r}" for k, (old, new) in diffs.items())


def sync(dry_run, yes):
    cfg, saved = load_members(), load_saved()
    plan, removed, new_aliases = plan_sync(cfg, saved)

    if not plan:
        print("Proxy already matches members.json. Nothing to do.")
        return

    print("Planned changes:")
    for desc, _ in plan:
        print("  " + desc)

    if removed and new_aliases:
        print("\n  ⚠  Some members are being removed AND others added in the same run.")
        print(f"     Removed: {', '.join(removed)}   Added: {', '.join(new_aliases)}")
        print("     If this is a RENAME, stop and use:  python3 setup_keys.py --rename OLD NEW")
        print("     (otherwise the person gets a second key with a fresh budget).")

    if dry_run:
        print("\nDry run: nothing changed.")
        return
    if not yes:
        if input("\nApply these changes? [y/N] ").strip().lower() != "y":
            print("Cancelled. Nothing changed.")
            return

    for desc, action in plan:
        action()
        print("  done  " + desc)
    print_keys(saved)


def rename(old, new):
    saved = load_saved()
    cfg = json.loads(MEMBERS_FILE.read_text())
    if old not in saved["keys"]:
        sys.exit(f"'{old}' has no active key in keys.json. Active: {', '.join(saved['keys']) or '(none)'}")
    if new in saved["keys"] or new in saved["blocked"]:
        sys.exit(f"'{new}' already exists in keys.json. Pick another name.")
    if any(m["alias"] == new for m in cfg["members"]):
        sys.exit(f"'{new}' already exists in members.json. Pick another name.")

    key = saved["keys"][old]
    call("POST", "/key/update", {"key": key, "key_alias": new, "metadata": {"member": new}})

    saved["keys"] = {(new if a == old else a): k for a, k in saved["keys"].items()}
    save(saved)

    found = False
    for m in cfg["members"]:
        if m["alias"] == old:
            m["alias"] = new
            found = True
    if found:
        MEMBERS_FILE.write_text(json.dumps(cfg, indent=2) + "\n")
    print(f"Renamed '{old}' -> '{new}' in the proxy and keys.json"
          + (" and members.json." if found else f". ('{old}' wasn't in members.json; add '{new}' there yourself.)"))
    print("Their key, budget and spend history are unchanged. Nothing to restart.")


def print_keys(saved):
    print(f"\nActive keys (saved in {KEYS_FILE.name}). Send each member ONLY their own:\n")
    for a, k in saved["keys"].items():
        print(f"  {a:<15} {k}")
    if saved["blocked"]:
        print(f"\nBlocked: {', '.join(saved['blocked'])}")


def main():
    p = argparse.ArgumentParser(description="Create/sync LiteLLM keys from members.json")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--sync", action="store_true", help="make the proxy match members.json")
    g.add_argument("--rename", nargs=2, metavar=("OLD", "NEW"), help="rename a member, keeping their key")
    p.add_argument("--dry-run", action="store_true", help="with --sync: show the plan only")
    p.add_argument("--yes", "-y", action="store_true", help="with --sync: don't ask for confirmation")
    args = p.parse_args()

    if args.rename:
        rename(*args.rename)
    elif args.sync:
        sync(args.dry_run, args.yes)
    else:
        create_only()


if __name__ == "__main__":
    main()