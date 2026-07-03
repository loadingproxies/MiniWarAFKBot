# MiniWar Shop Bot — YouTube Showcase Pack

Use this while screen-recording (OBS, Xbox Game Bar, etc.). Target length: **4–6 minutes**.

---

## Suggested title

**I Made a Bot That Buys Mini War Shop Restocks For Me (OCR + Auto-Buy)**

## Alternative titles

- Mini War Shop Bot — Never Miss a Divine Restock Again
- Auto-Buy Mini War Shop Items While AFK (Safe Screen-Reader Bot)

## Description (paste into YouTube)

```
Mini War shop restock bot — watches for the green "Shop has been restocked!" banner, opens the shop, scans Factory/Military tabs with OCR, and auto-buys your wishlist (Air Fortress, QCG, Supernova, etc.).

✅ Restock detection
✅ OCR item scanning
✅ Test mode (dry run) before going live
✅ Discord webhook alerts
✅ Wishlist-only fast scroll
✅ Purchase verification

Pure screen capture + mouse/keyboard — no injection, no memory reading.

Requirements: Windows 10/11, Python 3.12, Roblox windowed mode.

⚠️ Use at your own risk. Check game rules before using automation.

#MiniWar #Roblox #RobloxBot #Automation
```

## Tags

`mini war, roblox mini war, roblox shop bot, restock bot, auto buy, roblox automation, divine restock, air fortress, quantum core generator`

---

## Recording checklist

- [ ] Roblox in **windowed** mode, shop vendor visible
- [ ] Launcher open beside the game (or picture-in-picture in edit)
- [ ] Discord webhook test ready (optional)
- [ ] Start in **Test mode** first, then switch to **Live** for 10 seconds max if you want a real buy clip
- [ ] Hide webhook URL and any personal info in config

---

## Full script (voiceover + on-screen actions)

### 0:00 — Hook (5 sec)

**Say:**  
*"What if your Mini War shop restocks while you're AFK — and you still get the item?"*

**Show:** Launcher dashboard with purple theme, "Watching" status.

**On-screen text:** `Never miss a restock again`

---

### 0:05 — What it is (20 sec)

**Say:**  
*"This is a shop bot for Mini War. It watches your Roblox window for the green restock banner, opens the shop, reads items with OCR, and buys whatever you picked in the launcher. It's screen capture and clicks only — no game injection."*

**Show:** Quick montage — Roblox shop open → green banner → launcher item list.

---

### 0:25 — Setup (45 sec)

**Say:**  
*"Setup is simple. Install Python 3.12, run pip install, then double-click launcher.bat. First launch downloads the OCR model once."*

**Show:**  
1. File explorer → `launcher.bat`  
2. Launcher opens  
3. Brief flash of `pip install -r requirements.txt` in terminal (optional)

**On-screen text:** `3 minute setup`

---

### 1:10 — Pick your items (40 sec)

**Say:**  
*"Pick what you want to buy — toggle the purple dots on Factory and Military. I'm going after Quantum Core, Supernova, and Air Fortress. Turn on which tabs to scan with the category switches."*

**Show:**  
- Click items to enable buy (purple dots)  
- Toggle Factory + Military read switches  
- Activity panel updates

---

### 1:50 — Test mode (50 sec)

**Say:**  
*"Always start in Test mode. The bot runs the full restock flow but only logs what it would buy — no real clicks. When a restock hits, you'll see it detect the banner, open the shop, scroll, and report stock in the activity feed and logs."*

**Show:**  
- Settings → Test mode  
- Start bot  
- Wait for or cut to restock detection clip  
- Activity: "Shop restocked", scan results, "Out of Stock" / "In Stock" lines

**On-screen text:** `Test first — no real purchases`

---

### 2:40 — Live mode + verification (40 sec)

**Say:**  
*"When you're confident, switch to Live mode. Verify purchases is on by default — after each buy click it re-reads stock to confirm the purchase actually went through. Max one per item keeps you from overspending."*

**Show:** Settings → Live, Verify purchases, Max per item = 1

---

### 3:20 — Discord alerts (30 sec)

**Say:**  
*"Hook up a Discord webhook and you get pinged on restock, scan results, and purchases — with a screenshot on buys."*

**Show:** Settings → Discord → Send test → Discord channel notification

---

### 3:50 — Smart features (40 sec)

**Say:**  
*"Wishlist-only scroll means it stops as soon as it sees your items — no scrolling the whole catalog. Factory-first or Military-first controls which tab gets checked first. And when you stop the bot, logs auto-clear to keep low-end PCs snappy — or turn that off in Advanced when you're debugging."*

**Show:** Settings toggles briefly; logs panel; stop bot (F7)

---

### 4:30 — Outro (20 sec)

**Say:**  
*"Link in description if you want to try it. Run Test mode first, stand near the shop vendor, and good luck on those divine restocks."*

**Show:** Launcher idle, item list with wishlist items highlighted

**On-screen text:** `Test → Live → Profit?`

---

## B-roll ideas (if restock is slow)

- Scrolling military tab manually in-game  
- Discord notification popping up  
- Purchases / Timeline log tabs  
- Restock timer in launcher UI  
- "did not buy" vs "BOUGHT" in bot log (explains OOS vs success)

---

## Shorts / TikTok cut (60 sec)

1. Hook: green banner appears (3s)  
2. Bot opens shop automatically (5s)  
3. Launcher activity feed scrolling (10s)  
4. Discord ping (5s)  
5. "Test mode vs Live mode" split screen (15s)  
6. CTA: "Full setup in description" (5s)

---

## Thumbnail

Use: `assets/youtube-thumbnail-miniwar-bot.png` (generated in project)

Text on thumb: **MINIWAR SHOP BOT** / **AUTO RESTOCK**

---

## Music (royalty-free suggestions)

- YouTube Audio Library: "Electro Light" style upbeat tech  
- Keep game audio low under voiceover during demo sections

---

## Legal disclaimer (say or put in description)

*"This tool automates your own screen. Check Mini War / Roblox rules before using. Not affiliated with Roblox Corporation."*
