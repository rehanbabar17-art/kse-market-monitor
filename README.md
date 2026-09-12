# 📈 KSE Market Monitor

Automated monitoring of **KSE 100 Index** and your listed PSX stocks — delivered via **ntfy**.

## What It Does

- **Every 30 minutes** (Mon–Fri, 9 AM – 5 PM PKT): KSE 100 + your portfolio prices
- **End of day** (5:30 PM PKT): Full daily summary with highs, lows, volumes
- **Scheduled by cron-job.org** → triggers GitHub Actions via API (no server hosting needed)

## How It Works

```
cron-job.org ──POST (workflow_dispatch API)──▶ GitHub Actions ──▶ python main.py ──▶ ntfy
```

cron-job.org fires an HTTP request to GitHub's API which launches the repo's workflow.
The workflow runs the monitor script and sends the notification to your ntfy topic.

---

## Quick Setup

### 1. Add your ntfy topic as a GitHub secret

Go to **[https://github.com/rehanbabar17-art/kse-market-monitor/settings/secrets/actions](https://github.com/rehanbabar17-art/kse-market-monitor/settings/secrets/actions)** → **New repository secret**:

| Name | Value |
|---|---|
| `NTFY_TOPIC` | Your ntfy topic name (the part after `ntfy.sh/`) |

### 2. Create a GitHub Personal Access Token (PAT)

cron-job.org needs a token to trigger workflow runs on your repo.

1. Go to GitHub → **Settings → Developer settings → Personal access tokens → Tokens (classic)**
2. **Generate new token (classic)**
3. Give it a name (e.g. `cron-job-org-kse`)
4. Select the **`workflow`** scope (grants access to run workflows)
5. **Generate token** and copy it (shown only once — keep it safe)

> Alternative: use a **fine-grained token** scoped to just this repo with **Actions: Read and write** permission.

### 3. Create One Cron Job on cron-job.org

Go to [cron-job.org](https://cron-job.org) (free account), then click **CREATE CRONJOB**.

The single job uses **`auto` mode**: during market hours it sends interval updates;
once the market closes for the day it sends the EOD summary (only once, tracked via a
state file committed back to the repo).

#### Job — Auto (hourly, Mon–Fri)

| Field | Value |
|---|---|
| **Title** | `KSE Monitor - Auto` |
| **URL** | `https://api.github.com/repos/rehanbabar17-art/kse-market-monitor/actions/workflows/market-monitor.yml/dispatches` |
| **Request method** | `POST` |
| **Schedule** | `Custom` |
| **Cron expression** | `0 * * * 1-5` |
| **Timezone** | `UTC` |
| **Success criteria** | `2xx` (GitHub returns 204 on success) |

**Advanced → Request body:**

```json
{"ref":"main","inputs":{"mode":"auto","force":"true"}}
```

**Advanced → Request headers:**

```
Authorization: Bearer YOUR_PAT
Content-Type: application/json
Accept: application/vnd.github+json
```

> The cron runs hourly on weekdays. The script decides:
> - **9:00 AM – 4:00 PM PKT** → interval update
> - **5:00 PM PKT onward (first check)** → EOD summary (then skips until next day)
> - **Before 9 AM, weekends** → nothing

### 4. Configure Stocks

Stocks are in `kse-monitor/config.yaml`:

```yaml
ntfy:
  server: "https://ntfy.sh"
  topic: "your-unique-topic"

stocks:
  - symbol: "MLCF-SEP"
    name: "Maple Leaf Cement Futures"
  - symbol: "HTL"
    name: "HTL"
```

> Find PSX symbols at [dps.psx.com.pk/market-watch](https://dps.psx.com.pk/market-watch).
> Futures use `SYMBOL-MONTH` format (e.g. `MLCF-SEP`). Commit & push config changes — GitHub Actions picks them up automatically.

---

## Manual Trigger (test it yourself)

```bash
# Auto (same as the cron job)
curl -X POST -H "Authorization: Bearer YOUR_PAT" \
  -H "Content-Type: application/json" \
  -H "Accept: application/vnd.github+json" \
  -d '{"ref":"main","inputs":{"mode":"auto","force":"true"}}' \
  https://api.github.com/repos/rehanbabar17-art/kse-market-monitor/actions/workflows/market-monitor.yml/dispatches
```

Expect an empty `204` response. Then check **Actions** tab on GitHub — the workflow should appear and run.

## Project Structure

```
├── .github/workflows/market-monitor.yml   # Runs via workflow_dispatch
├── kse-monitor/
│   ├── config.yaml                         # Stock list, ntfy settings, market hours
│   ├── main.py                             # CLI entry point (runs the update)
│   ├── fetcher.py                          # PSX scraping + investify.pk fallback
│   ├── notifier.py                         # ntfy notification + formatting
│   └── requirements.txt                    # Python dependencies
├── Dockerfile                              # Optional: self-hosted server (server.py)
├── README.md
└── .gitignore
```

## Customization

- **Add/remove stocks:** Edit `stocks` in `config.yaml`, then commit & push
- **Change schedule:** Update the cron expressions on cron-job.org (NO repo change needed)
- **Self-hosted ntfy:** Change `ntfy.server` in `config.yaml`
- **Auto mode:** interval during hours, EOD once at close (state in `kse-monitor/state/last_eod.txt`)

## Data Sources

- **KSE 100 Index**: [PSX website](https://www.psx.com.pk) (market highlights)
- **PSX Stocks**: [PSX DPS market-watch](https://dps.psx.com.pk/market-watch)
- **Fallback**: [Investify.pk](https://investify.pk) (for delisted/suspended stocks)

## Tech Stack

- **Python 3.11** — requests for PSX scraping
- **ntfy** for push notifications
- **cron-job.org** for scheduling
- **GitHub Actions** for execution
