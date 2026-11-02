"""Shared helpers for the admin scripts. Standard library only, no installs needed."""
import json
import os
import pathlib
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).parent


def load_env(path=HERE / ".env"):
    """Read KEY=VALUE lines from .env into os.environ (existing env vars win)."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()
PROXY_URL = os.environ.get("PROXY_URL", "http://localhost:4000").rstrip("/")
MASTER_KEY = os.environ.get("LITELLM_MASTER_KEY")


def call(method, path, body=None):
    """Call the LiteLLM admin API with the master key and return parsed JSON."""
    if not MASTER_KEY:
        raise SystemExit("LITELLM_MASTER_KEY is not set (check your .env).")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        PROXY_URL + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {MASTER_KEY}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{method} {path} failed ({e.code}): {e.read().decode()[:500]}")
    except urllib.error.URLError as e:
        raise SystemExit(f"Cannot reach the proxy at {PROXY_URL}: {e.reason}. Is it running?")
