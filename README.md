# MiniWar AFK Bot

[![GitHub](https://img.shields.io/badge/GitHub-loadingproxies%2FMiniWarAFKBot-181717?logo=github)](https://github.com/loadingproxies/MiniWarAFKBot)

**MiniWar AFK Bot** is a Windows desktop assistant for [Roblox Mini War](https://www.roblox.com/games/). It watches your game window for the shop restock banner, opens the vendor, reads item names and stock with OCR, and automatically purchases the items you choose.

**Repository:** [github.com/loadingproxies/MiniWarAFKBot](https://github.com/loadingproxies/MiniWarAFKBot) · [Releases](https://github.com/loadingproxies/MiniWarAFKBot/releases) · [Issues](https://github.com/loadingproxies/MiniWarAFKBot/issues)

The bot uses **screen capture and normal mouse/keyboard input only** — like an advanced autoclicker. It does not inject into the game, read memory, or modify game files.

---

## Table of contents

1. [Quick start (Windows .exe)](#quick-start-windows-exe)
2. [Requirements](#requirements)
3. [In-game setup](#in-game-setup)
4. [Using the launcher](#using-the-launcher)
5. [Test mode vs Live mode](#test-mode-vs-live-mode)
6. [Settings reference](#settings-reference)
7. [Logs & activity feed](#logs--activity-feed)
8. [Discord notifications](#discord-notifications)
9. [Auto-updates](#auto-updates)
10. [How the bot works](#how-the-bot-works)
11. [Troubleshooting](#troubleshooting)
12. [Running from source (developers)](#running-from-source-developers)
13. [License](#license)

---

## Quick start (Windows .exe)

1. Download the latest **`MiniWarAFKBot-vX.X.X-win64.zip`** from [Releases](https://github.com/loadingproxies/MiniWarAFKBot/releases).
2. **Unblock the zip** before extracting (right-click zip → **Properties** → check **Unblock** at the bottom → OK). See [Downloaded zip blocked?](#downloaded-zip-blocked-windows).
3. Extract the zip. **`MiniWarAFKBot.exe`** must stay in the same folder as **`_internal`**.
4. If this is a **fresh PC**, install the [Windows runtimes](#windows-exe-runtimes) below.
5. Double-click **`MiniWarAFKBot.exe`**.
6. Set up Roblox as described in [In-game setup](#in-game-setup).
7. In the launcher, pick your wishlist items and leave **Test mode** on for your first run.
8. Stand next to the shop NPC in Mini War, then click **Start Bot**.
9. When you are confident it behaves correctly, switch to **Live mode** in Settings.

> **First launch:** The OCR engine downloads its language model once (~100 MB). An internet connection is required that one time.

---

## Requirements

| Requirement | Details |
|-------------|---------|
| **OS** | Windows 10 or Windows 11 (**64-bit**) |
| **.NET 8 Desktop Runtime (x64)** | Required for the launcher GUI — see [Windows exe runtimes](#windows-exe-runtimes) |
| **WebView2 Runtime** | Required for the launcher window — see [Windows exe runtimes](#windows-exe-runtimes) |
| **Roblox** | Mini War, **Windowed** mode (not Exclusive Fullscreen) |
| **Position** | Character standing at the shop vendor (so **E** opens the shop) |
| **Display** | Game window visible and not fully covered by other apps while the bot runs |

For running from Python source, see [Running from source](#running-from-source-developers).

### Windows exe runtimes

The **`MiniWarAFKBot.exe`** launcher uses a web-based UI (pywebview). On first run it will:

1. **Unblock** files in the install folder (fixes downloaded-zips from GitHub).
2. **Auto-install** missing runtimes via **winget** when available (.NET 8 Desktop + WebView2).
3. If winget cannot install them, open the download pages and show a short setup message.

On a clean PC you may still need to install manually once:

1. **[.NET 8 Desktop Runtime — Windows x64](https://dotnet.microsoft.com/download/dotnet/8.0)**  
   On the download page, under **Run desktop apps** / **Desktop Runtime**, choose **Windows → x64** (not the SDK).  
   Restart your PC after installing.

2. **[Microsoft Edge WebView2 Runtime](https://go.microsoft.com/fwlink/p/?LinkId=2124703)**  
   Install the Evergreen bootstrapper. Windows 11 often has this already; many Windows 10 PCs do not.

Extract the release zip so **`MiniWarAFKBot.exe`** sits in the same folder as **`_internal`** — do not copy only the exe.

If the exe crashes on startup with **`Python.Runtime.Loader.Initialize`**, try in order:

1. [Unblock the downloaded zip](#downloaded-zip-blocked-windows) and extract again (most common fix).
2. Install **.NET 8 Desktop Runtime (x64)** and restart.
3. Add the folder to your antivirus allow list.

### Downloaded zip blocked? (Windows)

Files downloaded from GitHub/Discord are often **marked as from the internet**. Windows can block **`Python.Runtime.dll`** inside `_internal`, which causes exactly:

`Failed to resolve Python.Runtime.Loader.Initialize`

**Fix (do this before extracting):**

1. **Delete** any folder you already extracted.
2. Right-click the **`.zip`** file → **Properties**.
3. At the bottom, check **Unblock** → **OK**.
4. **Extract all** again and run **`MiniWarAFKBot.exe`**.

**Or** after extracting, unblock the DLL:  
`_internal\pythonnet\runtime\Python.Runtime.dll` → Properties → **Unblock**.

Why it works on the developer's PC: a **local build** is not downloaded, so Windows does not block those DLLs.

---

## In-game setup

Before starting the bot:

1. Open Roblox in **Windowed** mode and maximize the game window.
2. Join **Mini War**.
3. Open the **Settings** menu (gear icon, top-right).
4. Recommended:
   - Enable **Low Performance**
   - Disable **Alliances** (reduces UI noise for OCR)

**Game language:** The bot supports **English, French, German, Spanish, Portuguese**, and **Auto** (all at once — default). In the launcher go to **Settings → Game UI language**. Wishlist names stay in English in the UI; the bot maps translated in-game names (e.g. *Forteresse aérienne* → Air Fortress) automatically.

Stand next to the shop NPC. The bot presses **E** to open the vendor when a restock is detected.

---

## Using the launcher

The launcher is the main control panel.

### Main screen

- **Wishlist** — Check the items you want the bot to buy when they appear in stock.
- **Categories** — Factory, Houses, Military, and Special tabs. Only enabled categories are scanned.
- **Start / Stop** — Starts or stops the background bot. You can also press **F7** to stop.
- **Status** — Shows whether the bot is watching, scanning, buying, or idle.
- **Restock timer** — Estimated time until the next shop restock (based on observed intervals).

### Settings

Open **Settings** from the launcher for advanced options. Changes are saved to `config.json` automatically.

### Test vs Live

See [Test mode vs Live mode](#test-mode-vs-live-mode) — always verify in Test mode first.

---

## Test mode vs Live mode

| Mode | Setting | Behavior |
|------|---------|----------|
| **Test** | `dry_run: true` | Detects restocks, opens the shop, scans items, and **logs** what it *would* buy — **no clicks** on buy buttons. |
| **Live** | `dry_run: false` | Same flow, but **clicks buy** for in-stock wishlist items. |

Toggle this in **Settings → Buying → Test mode (dry run)** or from the main screen if exposed there.

**Recommended workflow:**

1. Start in **Test mode**.
2. Wait for (or trigger) a restock and confirm the activity feed shows correct item names and stock.
3. Switch to **Live mode** when results look correct.

---

## Settings reference

Settings are stored in `config.json` next to the executable (or project root when running from source).

### Buying

| Option | Description |
|--------|-------------|
| **Auto-buy enabled** | Master switch for purchasing (scanning can still run when off, depending on config). |
| **Test mode (dry run)** | Safe mode — no purchase clicks. |
| **Max per item** | Maximum units to buy per item per restock (`0` = buy all available stock). |
| **Max total per restock** | Cap across all items in one restock cycle (`0` = unlimited). |
| **Verify purchases** | After each buy click, re-reads stock to confirm the purchase succeeded. |
| **Military first** | When enabled, scans Military before other categories (overrides default tab order). |
| **Wishlist scroll only** | Scrolls only until wishlist items are found — faster scans. |

### Alerts

| Option | Description |
|--------|-------------|
| **Sound alert** | Plays a sound when a restock is detected. |
| **Desktop notification** | Windows toast when a restock is detected. |

### Discord

| Option | Description |
|--------|-------------|
| **Enabled** | Send webhook messages to your Discord server. |
| **Webhook URL** | Your Discord webhook (see [Discord notifications](#discord-notifications)). |
| **Notify restock / buy / error / scan** | Choose which events post to Discord. |

### Logs & debug

| Option | Description |
|--------|-------------|
| **Clear logs when stopped** | Deletes `logs/` and debug screenshots when you stop the bot. Turn **off** while troubleshooting. |
| **Save debug screenshots** | Saves capture images when OCR or detection needs investigation. |

### Updates

| Option | Description |
|--------|-------------|
| **Check on start** | Looks for a new version using `update.manifest_url` in config. |
| **Manifest URL** | URL to a hosted `update.json` (see [Auto-updates](#auto-updates)). |

---

## Logs & activity feed

### Activity feed (launcher UI)

The launcher shows a live stream of bot events:

- Restock detected
- Shop opened / tabs scanned
- Items found, out of stock, or stock unclear
- Purchase attempts and verification results
- Errors (window not found, OCR failures, etc.)

### Log files

When the bot runs, it writes structured logs under the **`logs/`** folder:

| File | Purpose |
|------|---------|
| **`purchases.jsonl`** | One JSON line per purchase attempt (item, category, confirmed or not). |
| **`restocks.jsonl`** | Restock detection timestamps. |
| **`bot.log`** | General runtime log (status changes, errors). |

If **Clear logs when stopped** is enabled in Settings, these folders are wiped when you click **Stop** or press **F7**.

### Event screenshots

With **`events.enabled`** in config, the bot saves a full-game screenshot on each restock to the **`events/`** folder (oldest removed when `keep` limit is reached).

---

## Discord notifications

Discord is **optional**. To enable:

1. In Discord: **Server Settings → Integrations → Webhooks → New Webhook**.
2. Copy the webhook URL.
3. In the launcher: **Settings → Discord** — paste the URL, enable Discord, choose notification types.
4. Save and restart the bot if it is already running.

The bot can notify on restocks, purchases (with verification summary), scan summaries, and errors.

> **Security:** Never share your webhook URL publicly. If it leaks, delete the webhook in Discord and create a new one.

---

## Auto-updates

The bot can check for updates on launch when configured:

1. The project hosts **`update.json`** on GitHub (see the repo root).
2. Default manifest URL:
   `https://raw.githubusercontent.com/loadingproxies/MiniWarAFKBot/main/update.json`
3. When a newer version is published on [Releases](https://github.com/loadingproxies/MiniWarAFKBot/releases), the launcher offers to download and apply the update.

---

## How the bot works

High-level flow from idle to purchase:

```
┌─────────────────┐
│  Watching game  │  Polls Roblox window every ~0.5s
└────────┬────────┘
         │ Green "Shop has been restocked!" banner detected (color + OCR)
         ▼
┌─────────────────┐
│  Confirm banner │  OCR reads banner text; optional sound/desktop alert
└────────┬────────┘
         │ Press and hold E → shop UI opens
         ▼
┌─────────────────┐
│  Scan categories│  Factory → Military (or order from settings)
└────────┬────────┘
         │ For each tab: scroll item list, OCR names/rarity/stock
         ▼
┌─────────────────┐
│  Match wishlist │  Compare scanned items to your selected items
└────────┬────────┘
         │ In-stock wishlist items + Live mode
         ▼
┌─────────────────┐
│  Auto-buy       │  Click green buy button; optional verify (stock drop / OOS)
└────────┬────────┘
         │ Close shop → return to watch loop; cooldown before next check
         ▼
┌─────────────────┐
│  Wait for next  │  Discord / logs updated; restock timer reset
│  restock        │
└─────────────────┘
```

### Components (for developers)

| Part | Role |
|------|------|
| **`watcher.py`** | Main loop — banner detection, orchestration |
| **`navigator.py`** | Shop tabs, scrolling, buy clicks, wishlist early-stop |
| **`vision.py` / `parser.py`** | OCR and text parsing (stock numbers, "Out of Stock") |
| **`capture.py` / `window.py`** | Find Roblox window and capture regions |
| **`inventory.py`** | Stock labels and wishlist matching |
| **`notify.py`** | Discord webhooks |
| **`botlogs.py`** | File logging and cleanup on stop |
| **`tools/launcher.py`** | GUI (pywebview) — settings, logs, start/stop |

Coordinates in `config.json` are **fractions (0–1)** of the Roblox client area so layouts scale with window size. If a game UI update breaks alignment, run `python tools/calibrate.py` (source install) to recalibrate.

---

## Troubleshooting

| Problem | What to try |
|---------|-------------|
| **Bot does not start / no window** | Roblox must be open in Windowed mode with title containing "Roblox". |
| **Game in French / other language** | Settings → **Game UI language** → **Auto** (default) or pick your language. Restart the bot after saving. |
| **Restock not detected** | Stand at vendor; ensure banner region is visible; check Low Performance mode. |
| **Wrong items or "stock unclear"** | Run in Test mode; check activity feed; enable debug screenshots temporarily. |
| **Buys not confirmed (0/N)** | Enable **Verify purchases**; ensure sufficient in-game funds. |
| **Shop scroll takes too long** | Enable **Wishlist scroll only**; reduce wishlist to items you actually want. |
| **Launcher will not open** | Extract the full zip (`_internal` must be next to the exe). Install [.NET 8 Desktop Runtime x64](#windows-exe-runtimes) and [WebView2](#windows-exe-runtimes); restart PC. Allow the folder through antivirus. |
| **`Python.Runtime.Loader.Initialize` error** | **1)** [Unblock the zip](#downloaded-zip-blocked-windows) before extract, delete old folder, extract again. **2)** Install [.NET 8 Desktop Runtime x64](#windows-exe-runtimes) + restart. **3)** Antivirus exception for the bot folder. |
| **Discord not posting** | Verify webhook URL, enable Discord in Settings, check notify toggles. |

Press **F7** or use **Stop** in the launcher to halt the bot immediately.

---

## Running from source (developers)

**Requirements:** Python 3.12+, Windows 10/11.

```bat
python -m pip install -r requirements.txt
python tools/launcher.py
```

Or double-click **`launcher.bat`**.

Build the Windows executable:

```bat
build_exe.bat
```

Output: **`dist/MiniWarAFKBot/`** — distribute that folder or the generated **`-win64.zip`**.

Release builds copy **`config.default.json`** (empty webhook, Test mode, empty wishlist) — not your personal `config.json`.

---

## License

MIT License — see [LICENSE](LICENSE).
