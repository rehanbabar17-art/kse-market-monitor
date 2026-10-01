# 📈 PSX / KSE Market Monitor & Alert System

An automated, serverless monitor for the **Pakistan Stock Exchange (PSX)** and **KSE 100 Index**. It tracks your custom stock watchlist and futures contracts during market hours and delivers real-time price alerts and end-of-day (EOD) summaries straight to your phone, desktop, or smartwatch via **ntfy**.

---

## 📑 Table of Contents
1. [Architecture & Workflow](#-architecture--workflow)
2. [Project Structure](#-project-structure)
3. [How to Manage Your Stock Watchlist](#-how-to-manage-your-stock-watchlist)
4. [How the Data Fetcher Works](#-how-the-data-fetcher-works)
5. [How Push Notifications Work (ntfy)](#-how-push-notifications-work-ntfy)
6. [Trading Windows & Market Schedule (PKT)](#-trading-windows--market-schedule-pkt)
7. [Automated Setup (GitHub Actions + cron-job.org)](#-automated-setup-github-actions--cron-joborg)
8. [Local Development & Testing](#-local-development--testing)
9. [Developer Guide: Modifying the Python Scripts](#-developer-guide-modifying-the-python-scripts)
10. [Troubleshooting & FAQs](#-troubleshooting--faqs)

---

## 🏗 Architecture & Workflow

No always-on virtual machine or paid server is required. The architecture operates entirely serverless:

```text
┌────────────────┐     HTTP POST (workflow_dispatch)     ┌───────────────────────┐
│  cron-job.org  ├───────────────────────────────────────▶│     GitHub Actions    │
└────────────────┘                                       └───────────┬───────────┘
                                                                     │
                                                                     ▼
                                                         ┌───────────────────────┐
                                                         │ python main.py (auto) │
                                                         └───────────┬───────────┘
                                                                     │
                         ┌───────────────────────────────────────────┴───────────────────────────────────────────┐
                         ▼                                                                                       ▼
                         ┌───────────────────────┐                                                               ┌───────────────────────┐
                         │   fetcher.py Scraper  │                                                               │  notifier.py Alert    │
                         │  • PSX indices       │                                                               │  • Formats Message    │
                         │  • PSX Futures AJAX   │                                                               │  • Posts to ntfy.sh   │
                         │  • Investify fallback│                                                               └───────────┬───────────┘
             └───────────────────────┘                                                                           │
                                                                                                                 ▼
                                                                                                     ┌───────────────────────┐
                                                                                                     │   Mobile / Desktop    │
                                                                                                     │    Push Alert 🔔      │
                                                                                                     └───────────────────────┘
```

1. **GitHub Actions** starts the workflow every hour on weekdays using its built-in schedule. A manual `workflow_dispatch` is also available for testing.
2. **GitHub Actions** launches an ephemeral Ubuntu runner, restores the complete monitor configuration and state from B2, and executes `kse-monitor/main.py --mode auto`.
3. **`fetcher.py`** queries live PSX data with multi-source fallback redundancy.
4. **`notifier.py`** formats the market report and pushes it instantly to your **ntfy** topic.
5. The workflow uploads the configuration and updated EOD state to the private `kse-market-monitor/` B2 prefix; GitHub is used only for code and workflow files.

---

## 📁 Project Structure

```text
kse-market-monitor/
├── .github/
│   └── workflows/
│       └── market-monitor.yml       # GitHub Actions workflow triggered by cron
├── kse-monitor/
│   ├── main.py                      # Main entrypoint & schedule evaluation logic
│   ├── fetcher.py                   # Multi-source scraper (PSX Portal, Futures, Investify)
│   ├── notifier.py                  # Message builder & ntfy push dispatcher
│   ├── requirements.txt             # Python libraries (requests, pyyaml, etc.)
│   ├── server.py                    # Optional lightweight FastAPI/Flask local server
│   ├── b2_sync.py                   # B2 state restore/upload helper
│   └── state/                       # Not tracked; created only in temporary runners
├── Dockerfile                       # Container definition for self-hosting
└── README.md                        # Documentation & operator manual
```

---

## 🎯 How to Manage Your Stock Watchlist

The authoritative watchlist is stored in the private B2 object **`kse-market-monitor/config.yaml`**.
The repository does not retain a configuration or state cache. Download the B2 configuration
for an approved edit, then upload it again:

### 1. Download the B2 configuration
With the B2 secrets exported, run:

```bash
cd kse-market-monitor/kse-monitor
export B2_CONFIG_FILE=/tmp/kse-monitor-config.yaml
export B2_STATE_FILE=/tmp/kse-monitor-last_eod.json
export KSE_STATE_FILE=/tmp/kse-monitor-last_eod.json
B2_COMMAND=download python b2_sync.py
```

Edit `/tmp/kse-monitor-config.yaml`. It contains only the symbols to track:

```yaml
stocks:
  - HTL
  - YOUW
  - BIPL
  - MLCF-OCT
  - HASCOL
```

### 2. Adding a Regular Stock
Add a new item with the stock's standard PSX ticker symbol:
```yaml
  - OGDC
```

### 3. Adding a Future Contract
PSX 30-day and 90-day futures follow the `SYMBOL-MONTH` format (e.g. `MLCF-OCT`, `OGDC-NOV`, `TRG-DEC`):
```yaml
  - MLCF-OCT
```
The scraper automatically detects the hyphenated month pattern, queries the PSX Futures AJAX table for that specific contract month, and parses its open, high, low, current price, and volume. Display names are taken from fetched market data when supplied; otherwise the symbol is used.

### 4. Removing a Stock
Delete or comment out (`#`) the symbol lines in `/tmp/kse-monitor-config.yaml`, then upload the updated B2 configuration:
```bash
B2_COMMAND=upload python b2_sync.py
```
The next scheduled run will immediately use the updated B2 watchlist. Do not commit the temporary configuration.

---

## 🌐 How the Data Fetcher Works

`kse-monitor/fetcher.py` uses a resilient, per-symbol pipeline. A temporary failure in one source should not prevent notifications for the other symbols.

### Quote-source order

1. **KSE-100 index — PSX Data Portal and homepage**
   - Reads the current index, point change, percentage change, and available high/low values from the current PSX indices table.
   - Uses the PSX homepage markup as a compatibility fallback.
2. **Regular equities — DPS, official PSX market summary, then Investify**
   - Attempts the DPS market-watch snapshot first.
   - If DPS changes its route or returns `403`/`404`, the fetcher reads the official PSX market-summary include at `www.psx.com.pk/psx/include71650/new-PSX-market-summary.php` and its full-page fallback.
   - If both official sources are unavailable or omit a symbol, each equity is fetched independently from `https://www.investify.pk/company/{SYMBOL}/quote`.
   - Investify values are read from the current page quote metadata/FAQ payload, including current price, change, percentage change, volume, and day range.
3. **Futures — PSX Futures AJAX**
   - Queries `https://www.psx.com.pk/psx/market-summary/future-contract-ajax` for each configured contract month.
   - Symbols must use `SYMBOL-MONTH`, for example `MLCF-OCT` or `OGDC-NOV`.

### Expired futures

Futures are month-specific contracts. Once a contract month expires, its quote may no longer be returned. For example, `MLCF-SEP` should be replaced with the active contract such as `MLCF-OCT`. An expired symbol is reported as unavailable while the other watch-list symbols continue normally.

### Partial-failure behavior

If one symbol cannot be found in either source, the notification still proceeds and marks only that symbol with an error. This is preferable to failing the entire GitHub Actions run.

---

## 🔔 How Push Notifications Work (ntfy)

Notifications are published via [ntfy.sh](https://ntfy.sh) — a free, open-source, privacy-respecting notification service that requires no account creation.

### Setting Up ntfy on Your Devices:
1. **Mobile (Android / iOS)**: Install the **ntfy** app from Google Play Store or Apple App Store.
2. **Subscribe**: Tap **+** (Subscribe to topic) and enter your unique secret topic name (e.g. `my-private-kse-alerts-9823`).
3. **Web / Desktop**: You can also receive alerts in your browser by visiting `https://ntfy.sh/YOUR_TOPIC_NAME`.

### Message Types:
* **Interval Alert (During Trading Hours)**:
  - Summarizes current KSE-100 status.
  - Lists each watchlist stock with current price, change in PKR, percentage change (🟢 / 🔴), and traded volume.
  - Is sent only when the displayed market snapshot differs from the last interval alert sent that day; a changed notification timestamp alone does not trigger another alert.
* **End of Day (EOD) Summary (Market Close)**:
  - Sent once per trading day after market close (from 5:00 PM PKT onwards).
  - Includes Day High, Day Low, Close Price, Total Volume, and Net Day Change.

---

## ⏰ Trading Windows & Market Schedule (PKT)

Pakistan Stock Exchange trading sessions run in the **`Asia/Karachi`** timezone (PKT / UTC+5).

The schedule is maintained in the monitor code, not in the B2 watchlist file. The monitor
uses `Asia/Karachi`, Monday–Thursday 09:00–17:00 PKT, and Friday sessions 09:00–13:00
and 14:00–17:00 PKT. The B2 file contains symbols only.

### Auto Mode Behavior:
- **During a Trading Window**: Sends regular interval price alerts.
- **Duplicate interval snapshots**: If the KSE-100 and watchlist values shown in the interval message are unchanged from the last alert sent that day, the monitor skips the duplicate notification. The notification timestamp is not part of the comparison.
- **At Market Close (5:00 PM PKT)**: Sends the full EOD summary and records the date in the private B2 object `kse-market-monitor/last_eod.json` to prevent duplicate alerts.
- **Friday Jumma Break (1:00 PM - 2:00 PM PKT)**: Skips notifications during prayer break.
- **Weekends & Off-Hours**: Does not send notifications unless explicitly invoked with `--force`.

---

## ⚙️ Automated Setup (GitHub Actions)

### Step 1: Add your ntfy Topic as a GitHub Secret
1. Go to your repository on GitHub: **Settings → Secrets and variables → Actions**.
2. Click **New repository secret**.
3. Name: `NTFY_TOPIC`
4. Value: `your-ntfy-topic-name` (e.g., `kse-alerts-rehan-786`)
5. Click **Add secret**.

### Step 2: Add the shared Backblaze B2 secrets
The workflow stores the complete monitor setup in the namespaced objects
`kse-market-monitor/config.yaml` and `kse-market-monitor/last_eod.json` inside the shared
`GithubRepoSecretRB17` bucket.
Add these repository secrets using **Settings → Secrets and variables → Actions**:

| Secret | Value |
|---|---|
| `B2_KEY_ID` | The Backblaze application key ID |
| `B2_APPLICATION_KEY` | The Backblaze application key |
| `B2_BUCKET` | `GithubRepoSecretRB17` |
| `B2_ENDPOINT` | `https://s3.us-east-005.backblazeb2.com` |

The application key should be restricted to the shared bucket and should not be committed to the repository.

### Step 3: Enable the GitHub Actions schedule
The workflow includes the schedule `0 4-12 * * 1-5` in UTC, which runs hourly during
09:00–17:00 Pakistan time, Monday–Friday.
GitHub may pause scheduled workflows in repositories with no recent activity; opening the
Actions page or pushing a normal commit reactivates the schedule. If an older cron-job.org
trigger is still configured, disable it to avoid duplicate hourly notifications.

### B2 configuration and state lifecycle
- Before the monitor starts, `b2_sync.py` downloads both B2 objects into `/tmp`.
- The monitor reads the symbols from the downloaded B2 configuration; names and quote details come from PSX/DPS market data when available.
- After the monitor finishes, the workflow uploads both configuration and runtime state back to B2. The state includes the last same-day interval snapshot fingerprint as well as EOD delivery markers.
- The temporary files are deleted after every run; no configuration or runtime-state cache is retained in GitHub.
- If either required B2 object is missing, the workflow fails rather than silently using stale repository data.

The runtime state object may contain:

```json
{
  "eod_sent": [],
  "last_interval": {
    "date": "2026-09-30",
    "signature": "timestamp-free-market-snapshot-hash"
  }
}
```

The interval signature covers the values displayed in the KSE-100 and
watchlist sections, but deliberately excludes the notification timestamp.
The signature is reset by date, so the first unchanged-looking snapshot of a
new trading day is still delivered.

### Manual workflow test
Use **Actions → KSE Market Monitor → Run workflow** and select `auto` with `force=false`.
The run should show successful **Restore EOD state from B2** and **Upload EOD state to B2** steps.
To test notifications outside market hours, select `interval` or `summary` and set `force=true`.

---

## 💻 Local Development & Testing

### 1. Prerequisites
- Python 3.10+ installed.
- Git installed.

### 2. Setup Virtual Environment
```bash
# Clone repository
git clone https://github.com/rehanbabar17-art/kse-market-monitor.git
cd kse-market-monitor/kse-monitor

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate   # On Windows use: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Set Test Environment Variable
```bash
export NTFY_TOPIC="your-test-topic"   # On Windows use: set NTFY_TOPIC=your-test-topic
```

For local B2 synchronization tests, also set `B2_KEY_ID`, `B2_APPLICATION_KEY`,
`B2_BUCKET`, and `B2_ENDPOINT` in your shell. Never commit these values.

### 4. Running Test Commands
```bash
# Test interval alert immediately (ignores trading hours)
python main.py --mode interval --force

# Test End-of-Day (EOD) summary immediately
python main.py --mode summary --force

# Run in normal auto mode (respects market schedule)
python main.py --mode auto
```

The `--force` option only bypasses the market-hours check; it does not bypass
same-day interval deduplication. This prevents external `workflow_dispatch`
triggers that pass `force=true` from sending the same market snapshot again.
To test a notification, wait for a market value to change or remove the
`last_interval` entry from the restored B2 state before running the workflow.

To mirror GitHub Actions locally, run the B2 restore before `main.py` and the B2 upload afterward:

```bash
cd kse-monitor
export B2_CONFIG_FILE=/tmp/kse-monitor-config.yaml
export B2_STATE_FILE=/tmp/kse-monitor-last_eod.json
export KSE_STATE_FILE=/tmp/kse-monitor-last_eod.json
B2_COMMAND=download python b2_sync.py
python main.py --config "$B2_CONFIG_FILE" --mode auto
B2_COMMAND=upload python b2_sync.py
rm -f "$B2_CONFIG_FILE" "$B2_STATE_FILE"
```

---

## 👨‍💻 Developer Guide: Modifying the Python Scripts

If you want to customize how the application operates under the hood, here is a breakdown of what each Python module controls:

### 1. B2 object `kse-market-monitor/config.yaml`
- Contains only the symbols in the `stocks` list.
- Company names, prices, and quote details are fetched from DPS/PSX sources when available.

### 2. `kse-monitor/fetcher.py`
- **`fetch_all(stocks: list)`**: Orchestrates the scraping pipeline.
- **`fetch_kse100()`**: Parses the KSE 100 Index table from the PSX Data Portal, with a homepage fallback.
- **`_parse_futures(month: str)`**: Sends an AJAX POST request to retrieve future contracts.
- **`_fetch_investify_fallback(symbol: str)`**: Parses current Investify quote metadata and retains compatibility with older embedded JSON.

### 3. `kse-monitor/notifier.py`
- **`build_interval_message(data)`**: Formats the text and visual emojis for live trading hours notifications.
- **`build_eod_message(data)`**: Formats the closing summary table.
- **`send_ntfy(topic, message, title, priority, tags)`**: Dispatches the HTTP POST payload to `ntfy.sh`. You can adjust alert priorities (`high`, `default`, `low`) or customize sound tags (e.g. `chart_with_upwards_trend`, `moneybag`, `warning`).

### 4. `kse-monitor/main.py`
- Evaluates the current market time against the built-in PSX trading schedule.
- Checks the B2-restored `last_eod.json` to guarantee only one EOD alert is dispatched per calendar day.

---

## ❓ Troubleshooting & FAQs

#### Q: The notification says "Investify Fallback" or PSX is slow.
**A**: The official DPS portal (`dps.psx.com.pk`) can return `403`, `404`, or timeouts to automated runners. The scraper first tries the official PSX market-summary page, then Investify per symbol. This is expected fallback behavior, not necessarily a failure.

#### Q: A regular stock has no price in the notification.
**A**: Check that the symbol is the official PSX ticker, then run a forced interval test from GitHub Actions. Inspect the `Run KSE Monitor` log for the symbol. If the symbol is a futures contract, confirm that its month has not expired and use the current `SYMBOL-MONTH` contract.

#### Q: Why does an expired futures symbol show an error while other symbols work?
**A**: Futures are separate month-specific instruments. Remove the expired entry or replace it with the currently traded month, for example change `MLCF-SEP` to `MLCF-OCT`.

#### Q: The workflow succeeds but I still do not see a notification.
**A**: Confirm that the ntfy app is subscribed to the exact topic stored in the GitHub Actions secret `NTFY_TOPIC`. In Actions, a successful `Run KSE Monitor` step means the fetch and ntfy publish request completed; a missing alert after that usually indicates a topic, subscription, or device-notification setting issue.

#### Q: How do I test the GitHub Actions workflow manually?
**A**: Go to your GitHub repo → **Actions** tab → Select **KSE Market Monitor** → Click **Run workflow** → select `mode: interval` and `force: true` → click **Run workflow**.

#### Q: The workflow is green but no alert arrives.
**A**: Check the `Run KSE Monitor` step. A message such as `Auto: skipping — before market hours`
means the workflow ran outside the built-in PSX schedule. The workflow now evaluates the
schedule in code and runs hourly on weekdays. A successful run during a trading window should
show `Fetching market data` and a successful ntfy publish rather than an `Auto: skipping` message.

#### Q: Can I track stocks across different indices (e.g. KSE 30, KMI 30)?
**A**: Yes. Download `kse-market-monitor/config.yaml` from B2, add the valid PSX symbol to its `stocks` list, and upload it again. Any stock listed on the Pakistan Stock Exchange can be tracked.

---

## 📄 License
MIT License. Open source and free to use for personal portfolio tracking.
