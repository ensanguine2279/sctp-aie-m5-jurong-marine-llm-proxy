# Capstone LLM budget proxy (LiteLLM)

One server holds the instructor's OpenAI key. Everyone else (Python scripts,
the Java backend) talks to this proxy with their **own virtual key**, and the
proxy enforces spending caps and logs every call.

```
alice.py ─┐
bob.py   ─┼─ member key ─▶  LiteLLM proxy :4000  ── real key ──▶  OpenAI
backend  ─┘                 (checks budget, logs cost)
                                   │
                               Postgres (keys, spend)
```

## Budget layers

| Layer | Where it's set | Default here | What happens when hit |
|---|---|---|---|
| Per-member key | `members.json` | $3 each, $8 for backend / 30 days | Only that key is blocked |
| Team | `members.json` → `team` | $18 / 30 days | All member keys blocked |
| Global proxy | `config.yaml` → `max_budget` | $18 / 30 days | Every request blocked |
| OpenAI project limit | Instructor's dashboard | whatever they set | OpenAI returns `insufficient_quota` |

Set the team and global caps **a little below** the real budget. LiteLLM
calculates cost from list prices, so its numbers are close estimates, not the bill.

## 1. Start the proxy (admin, once)

Needs Docker Desktop (or Docker Engine + Compose).

```bash
cp .env.example .env       # then edit .env: paste the OpenAI key, generate secrets
docker compose up -d
docker compose logs -f litellm     # wait for "Application startup complete", then Ctrl+C
curl http://localhost:4000/health/liveliness
```

Edit `config.yaml` so `model_list` contains only the models your course allows.

## 2. Create everyone's keys (admin)

Edit `members.json` with your real names and budgets, then:

```bash
python setup_keys.py
```

Send each person **only their own key**, privately. `keys.json` holds all of
them and is git-ignored. Keep it that way.

## 3. Use it (everyone)

Point the normal OpenAI SDK at the proxy; nothing else changes.

```python
client = OpenAI(base_url="http://<proxy-host>:4000", api_key="<your member key>")
```

```java
OpenAIOkHttpClient.builder().baseUrl("http://<proxy-host>:4000").apiKey("<backend key>").build();
```

Full examples with budget-error handling: `examples/python_client.py`,
`examples/java/ProxyClientExample.java`.

## 4. Watch spending (admin)

- `python spend_report.py` prints team and per-member spend vs. cap.
- Dashboard: `http://<proxy-host>:4000/ui`, log in as `admin` / `UI_PASSWORD`.
  It shows spend per key and model, and a log of each request.

## Common changes

- **Raise someone's cap:** in the dashboard edit the key, or
  `curl -X POST $PROXY_URL/key/update -H "Authorization: Bearer $LITELLM_MASTER_KEY" -H "Content-Type: application/json" -d '{"key":"sk-...","max_budget":5}'`
- **Block a leaked key:** `POST /key/block` with `{"key":"sk-..."}`, or delete it in the dashboard, then issue a new one.
- **Add a member:** add them to `members.json` and run `python setup_keys.py` again.

## Where to host it so teammates can reach it

- **Testing:** `localhost:4000` only works on your own machine.
- **Same network:** `http://<your-LAN-IP>:4000`. Works on home Wi-Fi; campus Wi-Fi often blocks it.
- **Small cloud VM** (any provider's free or cheapest tier, ~1 GB RAM is enough): install
  Docker, copy this folder, `docker compose up -d`. Put HTTPS in front (e.g. Caddy) or at
  least restrict the firewall so port 4000 isn't open to the whole internet.
- **Temporary tunnel:** `cloudflared tunnel --url http://localhost:4000` gives an HTTPS URL
  while your laptop is on. Fine for a demo, not for daily use.

## Security checklist

- The real OpenAI key lives only in `.env` on the proxy server.
- `.env` and `keys.json` are never committed (see `.gitignore`).
- The master key and `UI_PASSWORD` are for admins only. Members get virtual keys.
- Check with your instructor that running the key on a group server is OK.

## Reset everything

`docker compose down -v` deletes the database: all keys, teams and spend history.
Delete `keys.json` as well before running `setup_keys.py` again.
