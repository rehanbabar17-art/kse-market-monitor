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

1. **cron-job.org** sends a scheduled HTTP request every hour to GitHub's Actions API (`workflow_dispatch`).
2. **GitHub Actions** launches an ephemeral Ubuntu runner, restores state from B2, and executes `kse-monitor/main.py --mode auto`.
3. **`fetcher.py`** queries live PSX data with multi-source fallback redundancy.
4. **`notifier.py`** formats the market report and pushes it instantly to your **ntfy** topic.
5. The workflow uploads the updated EOD state to the private `kse-market-monitor/` B2 prefix; it no longer commits runtime state to Git.

---

## 📁 Project Structure

```text
kse-market-monitor/
├── .github/
│   └── workflows/
│       └── market-monitor.yml       # GitHub Actions workflow triggered by cron
├── kse-monitor/
│   ├── config.yaml                  # Watchlist, trading hours, ntfy settings
│   ├── main.py                      # Main entrypoint & schedule evaluation logic
│   ├── fetcher.py                   # Multi-source scraper (PSX Portal, Futures, Investify)
│   ├── notifier.py                  # Message builder & ntfy push dispatcher
│   ├── requirements.txt             # Python libraries (requests, pyyaml, etc.)
│   ├── server.py                    # Optional lightweight FastAPI/Flask local server
│   ├── b2_sync.py                   # B2 state restore/upload helper
│   └── state/
│       └── last_eod.json            # Runner copy; authoritative state is stored in B2
├── Dockerfile                       # Container definition for self-hosting
└── README.md                        # Documentation & operator manual
```

---

## 🎯 How to Manage Your Stock Watchlist

To add, edit, or remove stocks from your alerts, you only need to edit **`kse-monitor/config.yaml`**.

### 1. Opening `config.yaml`
Locate the `stocks:` section at the bottom of `kse-monitor/config.yaml`:

```yaml
stocks:
  - symbol: "MLCF-OCT"
    name: "Maple Leaf Cement Futures"
  - symbol: "HASCOL"
    name: "Hascol Petroleum"
  - symbol: "HUBC"
    name: "Hub Power Company"
  - symbol: "SYS"
    name: "Systems Limited"
  - symbol: "BIPL"
    name: "BankIslami Pakistan"
```

### 2. Adding a Regular Stock
Add a new item with the stock's standard PSX ticker symbol:
```yaml
  - symbol: "OGDC"
    name: "Oil & Gas Development Company"
```

### 3. Adding a Future Contract
PSX 30-day and 90-day futures follow the `SYMBOL-MONTH` format (e.g. `MLCF-OCT`, `OGDC-NOV`, `TRG-DEC`):
```yaml
  - symbol: "MLCF-OCT"
    name: "Maple Leaf Cement October Futures"
```
The scraper automatically detects the hyphenated month pattern, queries the PSX Futures AJAX table for that specific contract month, and parses its open, high, low, current price, and volume.

### 4. Removing a Stock
Simply delete or comment out (`#`) the symbol lines in `config.yaml`, commit the change, and push to GitHub:
```bash
git add kse-monitor/config.yaml
git commit -m "Update stock watchlist"
git push origin main
```
*The next scheduled run will immediately reflect your updated watchlist.*

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
* **End of Day (EOD) Summary (Market Close)**:
  - Sent once per trading day after market close (from 5:00 PM PKT onwards).
  - Includes Day High, Day Low, Close Price, Total Volume, and Net Day Change.

---

## ⏰ Trading Windows & Market Schedule (PKT)

Pakistan Stock Exchange trading sessions run in the **`Asia/Karachi`** timezone (PKT / UTC+5).

The trading schedule is configured inside `kse-monitor/config.yaml`:
```yaml
market:
  timezone: "Asia/Karachi"

trading_windows:
  mon:
    - [9, 17]      # 9:00 AM to 5:00 PM
  tue:
    - [9, 17]
  wed:
    - [9, 17]
  thu:
    - [9, 17]
  fri:
    - [9, 13]      # Morning session (9:00 AM - 1:00 PM)
    - [14, 17]     # Afternoon session after Jumma break (2:00 PM - 5:00 PM)
```

### Auto Mode Behavior:
- **During a Trading Window**: Sends regular interval price alerts.
- **At Market Close (5:00 PM PKT)**: Sends the full EOD summary and records the date in the private B2 object `kse-market-monitor/last_eod.json` to prevent duplicate alerts.
- **Friday Jumma Break (1:00 PM - 2:00 PM PKT)**: Skips notifications during prayer break.
- **Weekends & Off-Hours**: Does not send notifications unless explicitly invoked with `--force`.

---

## ⚙️ Automated Setup (GitHub Actions + cron-job.org)

### Step 1: Add your ntfy Topic as a GitHub Secret
1. Go to your repository on GitHub: **Settings → Secrets and variables → Actions**.
2. Click **New repository secret**.
3. Name: `NTFY_TOPIC`
4. Value: `your-ntfy-topic-name` (e.g., `kse-alerts-rehan-786`)
5. Click **Add secret**.

### Step 2: Add the shared Backblaze B2 secrets
The workflow stores only the small EOD deduplication state in the namespaced object
`kse-market-monitor/last_eod.json` inside the shared `GithubRepoSecretRB17` bucket.
Add these repository secrets using **Settings → Secrets and variables → Actions**:

| Secret | Value |
|---|---|
| `B2_KEY_ID` | The Backblaze application key ID |
| `B2_APPLICATION_KEY` | The Backblaze application key |
| `B2_BUCKET` | `GithubRepoSecretRB17` |
| `B2_ENDPOINT` | `https://s3.us-east-005.backblazeb2.com` |

The application key should be restricted to the shared bucket and should not be committed to the repository.

### Step 3: Create a GitHub Personal Access Token (PAT)
To allow `cron-job.org` to trigger your GitHub Actions workflow:
1. Go to GitHub: **Settings → Developer settings → Personal access tokens → Tokens (classic)**.
2. Click **Generate new token (classic)**.
3. Note: `cron-job-kse-monitor`.
4. Select Scope: Check **`workflow`**.
5. Generate and copy your token (`ghp_...`).

### Step 4: Configure Scheduled Job on cron-job.org
1. Create a free account on [cron-job.org](https://cron-job.org).
2. Click **Create Cronjob**.
3. Fill in the fields:
   - **Title**: `KSE Market Monitor Trigger`
   - **URL**: `https://api.github.com/repos/rehanbabar17-art/kse-market-monitor/actions/workflows/market-monitor.yml/dispatches`
   - **Execution schedule**: Every hour / Custom `0 * * * 1-5` (Mon–Fri).
   - **Request Method**: `POST`
4. **Advanced Configuration**:
   - **Request Headers**:
     ```text
     Authorization: Bearer YOUR_GITHUB_PAT_TOKEN
     Content-Type: application/json
     Accept: application/vnd.github+json
     ```
   - **Request Body**:
     ```json
     {"ref":"main","inputs":{"mode":"auto","force":"false"}}
     ```
5. Save the job.

### B2 state lifecycle
- Before the monitor starts, `b2_sync.py` downloads `kse-market-monitor/last_eod.json`.
- After the monitor finishes, the workflow uploads the local state and removes the runner copy.
- If the B2 object does not exist yet, the checked-in empty state is used for the first bootstrap upload.
- Runtime state is never committed back to GitHub, so repeated runs do not create state-file commits.

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

The local commands above use the local `state/last_eod.json` file directly. To mirror
GitHub Actions, run the B2 restore before `main.py` and the B2 upload afterward:

```bash
cd kse-monitor
B2_COMMAND=download python b2_sync.py
python main.py --mode auto
B2_COMMAND=upload python b2_sync.py
```

---

## 👨‍💻 Developer Guide: Modifying the Python Scripts

If you want to customize how the application operates under the hood, here is a breakdown of what each Python module controls:

### 1. `kse-monitor/config.yaml`
- Controls stock watchlist, timezone, trading hours, and custom thresholds.
- Values like `ntfy.server` can be altered if you host your own private ntfy server instance.

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
- Evaluates the current market time against `trading_windows`.
- Checks `state/last_eod.json` to guarantee only one EOD alert is dispatched per calendar day.

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
**A**: Go to your GitHub repo → **Actions** tab → Select **PSX Market Monitor** from the left sidebar → Click **Run workflow** dropdown → Select `mode: interval` and `force: true` → Click **Run workflow**.

#### Q: Can I track stocks across different indices (e.g. KSE 30, KMI 30)?
**A**: Yes! Simply add any valid PSX ticker symbol to `config.yaml`. Any stock listed on the Pakistan Stock Exchange can be tracked.

---

## 📄 License
MIT License. Open source and free to use for personal portfolio tracking.
