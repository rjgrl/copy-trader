# Telegram → MetaTrader 5 Signal Copier

Lightweight Windows desktop application that listens to selected Telegram groups/channels (via your personal Telegram account), parses trading signals, validates entry conditions intelligently, and executes corresponding orders in MetaTrader 5.

> **Status:** Phase 1–7 complete + Windows packaging (PyInstaller ONEDIR). Integration polish optional.

---

## MT5 (Phase 4)

MetaTrader 5 must be installed and running. Connect and inspect account/symbols:

```bash
python run.py mt5
```

Symbol names differ by broker. This project is configured for **XM Ultra Low** where gold is `GOLD#`:

```json
{
  "symbol_mappings": {
    "XAUUSD": "GOLD#",
    "GOLD": "GOLD#"
  }
}
```

(On XM Standard the symbol is typically `GOLD` — change the mapping accordingly.)
Pricing always uses live MT5 `point` / `digits` / tick size — never hard-coded XAUUSD point assumptions.

BUY execution price = ask · SELL = bid. Spread is reported in both price units and MT5 points.

---

## Safe startup (critical)

On listen/start the app always:

1. Connect Telegram  
2. Restore SQLite state  
3. Reconcile incomplete `EXECUTING` / `PARTIALLY_EXECUTED` → `EXECUTION_REQUIRES_REVIEW` (no auto-retry)  
4. Fetch per-chat **top message ID watermarks** (do not execute them)  
5. Activate the live listening point  
6. Register NewMessage handlers  
7. Wait for messages with `message_id > watermark` only  

Duplicate identity is always `telegram_chat_id + telegram_message_id` (UNIQUE in SQLite). Timestamps are stored in UTC for latency/display only — never as the primary gate.

---

## False-positive protection

Messages are classified before trading:

- Chatter / analysis / “TP1 HIT” / “Move SL” → **SKIPPED** (no new trades)  
- Incomplete signals (missing SL/TP/entry) → **REJECTED**  
- Valid structured signals → **VALIDATED** (execution in later phases)  

```bash
python run.py inspect
```

Paste any Telegram message to see detection, validation, and rejection reasons.

---

## Requirements

| Component | Requirement |
|-----------|-------------|
| OS | Windows 10/11 |
| Python | 3.12+ |
| MetaTrader 5 | Installed and running (for live/demo trading phases) |
| Telegram | Personal account that is a member of the signal groups/channels |

### Python dependencies

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

---

## Architecture

```
Telegram Group/Channel
        ↓
Telegram Listener (event-driven, new messages only)
        ↓
Signal Detection → Parser → Validator
        ↓
Intelligent Entry Validation (deviation, TP proximity, spread)
        ↓
Safety Limits → MT5 Trade Engine (1 order per TP)
        ↓
SQLite persistence + duplicate protection
```

Clear separation of concerns:

- `app/config` — settings & conservative defaults
- `app/signals` — parse / validate / dedupe
- `app/trading` — entry logic, risk, lifecycle, safety
- `app/database` — SQLite schema & repositories
- `app/telegram` — Telethon client (Phase 3)
- `app/mt5` — MetaTrader5 integration (Phase 4–6)
- `app/gui` — PySide6 UI (Phase 7)

---

## Quick start

```bash
# Bootstrap config + database
python run.py

# Launch desktop GUI (recommended)
python run.py gui

# Run unit tests (no MT5 / live Telegram required)
pytest -q

# Inject a sample signal without Telegram
python run.py simulate
```

### Telegram login (first time)

1. Create an app at [https://my.telegram.org/apps](https://my.telegram.org/apps)
2. Copy `.env.example` → `.env` and set `TELEGRAM_API_ID` / `TELEGRAM_API_HASH`
3. Authenticate:

```bash
python run.py auth
```

4. List dialogs (for source selection):

```bash
python run.py dialogs
```

5. Enable sources in the GUI (**Telegram** page) or via DB, then start listening from the Dashboard or:

```bash
python run.py listen
```

The listener registers **NewMessage** handlers only — it does **not** replay chat history.

---

## Telegram API setup (Phase 3+)

1. Open [https://my.telegram.org/apps](https://my.telegram.org/apps)
2. Create an application and note **API ID** and **API Hash**
3. Copy `.env.example` → `.env` and fill in:

```env
TELEGRAM_API_ID=123456
TELEGRAM_API_HASH=your_api_hash_here
```

Sensitive files (never commit):

- `.env`
- `data/*.session` (Telethon session)
- `data/config.json` (local UI settings)

---

## Signal format

Supported examples (all normalize to one internal model):

```text
SELL XAUUSD 4291.5
TP 4287.5
TP 4283
TP 4277
SL 4306.5
```

```text
SELL XAUUSD @ 4291.5
TP1: 4287.5
TP2: 4283
TP3: 4277
SL: 4306.5
```

```text
SELL GOLD
ENTRY 4291.5
TP 4287.5 / 4283 / 4277
SL 4306.5
```

Default rule: **one MT5 order per take-profit**, all sharing the same stop loss.

---

## Intelligent entry (summary)

1. Compare current MT5 market price to the signal entry
2. If within configured max deviation → **market execute at current price** (not the Telegram entry)
3. If TP1 already reached → **reject** (delayed signal protection)
4. If too far → **reject** (default), or pending/manual per settings

---

## Configuration defaults

| Setting | Default |
|---------|---------|
| Dry Run | `true` |
| Copy Trading | `false` |
| Entry Mode | Intelligent |
| Max Entry Deviation | `3.0` price units |
| TP Proximity Protection | ON |
| Lot Mode | Fixed `0.01` |
| Max Simultaneous Trades | `5` |
| Magic Number | `123456` |

Settings overlay: `data/config.json` (created by the app). Secrets stay in `.env`.

---

## Safety warnings

- This software can place real trades. Start with **Dry Run** and a demo MT5 account.
- Past performance of signal providers does not guarantee future results.
- You are solely responsible for risk, lot sizing, and broker configuration.
- Never share your Telegram session file or API credentials.

---

## Testing

```bash
pytest -q
pytest tests/test_parser.py -v
pytest tests/test_entry_logic.py -v
```

All automated tests **mock or avoid** real MT5 order submission.

---

## Building an executable (Windows)

Primary build is a **windowed ONEDIR** folder (not onefile):

```powershell
# From repo root (uses .venv, installs deps, runs PyInstaller)
.\scripts\build_exe.ps1 -Clean
```

Output:

```
dist\TelegramMT5Copier\TelegramMT5Copier.exe
```

Optional console/debug build (for troubleshooting and first-time Telegram auth):

```powershell
.\scripts\build_debug.ps1 -Clean
```

### Persistent data (packaged EXE)

Writable files are **not** stored next to the EXE or inside PyInstaller's temp folder.
They live under:

```
%LOCALAPPDATA%\TelegramMT5Copier\
  .env                  # Telegram API secrets (create this yourself)
  data\copier.db
  data\config.json
  data\telegram_session.session
  logs\...
```

Development mode still uses the repo `data/` and `logs/` directories.

### Telegram credentials (packaged)

1. Create `%LOCALAPPDATA%\TelegramMT5Copier\.env` with `TELEGRAM_API_ID` / `TELEGRAM_API_HASH`
2. Authenticate once with the **debug** console build:

```powershell
.\dist\TelegramMT5Copier_debug\TelegramMT5Copier_debug.exe auth
```

3. Launch the normal windowed EXE — the session file persists across restarts and EXE updates

### MetaTrader 5

The packaged app does **not** include MT5. Install/run your broker terminal separately.
Configure `mt5_terminal_path` in Settings / `config.json` if auto-detect fails.

### Spec / launcher

| File | Role |
|------|------|
| `launcher.py` | PyInstaller entry → `run_gui()` (also supports `auth` etc. on debug build) |
| `build/TelegramMT5Copier.spec` | Explicit ONEDIR PyInstaller spec |
| `run.py` | Development CLI (unchanged) |

Do **not** bundle `.env` secrets into the executable.

---

## Troubleshooting

| Issue | What to check |
|-------|----------------|
| Bootstrap fails | Python 3.12+, `pip install -r requirements.txt` |
| Tests fail | Run from project root; ensure `PYTHONPATH` includes `.` |
| GUI won't start | `pip install PySide6`; try `python run.py status` first |
| Packaged EXE data location | `%LOCALAPPDATA%\TelegramMT5Copier\` |
| Telegram not authorized (EXE) | Create `.env` under LOCALAPPDATA path; run `TelegramMT5Copier_debug.exe auth` |
| Telegram not authorized in GUI | Run `python run.py auth` once, then Connect in GUI |
| MT5 connect fails | Terminal running, algorithm trading enabled, correct path |
| Telegram auth fails | API ID/Hash, phone OTP, 2FA password when prompted |

---

## License / disclaimer

For personal use. Trading involves substantial risk of loss. Use at your own risk.
