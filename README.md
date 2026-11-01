# NEAR DEX Alerts + Token Scanner

**Never miss a move on NEAR DEXes.** A Telegram bot that watches every NEAR pool and alerts your chat about volume spikes, pumps, dumps and pump & dumps — plus a token scanner for any NEAR contract.

**Try it live:** [@nearaidex_bot](https://t.me/nearaidex_bot) · 🇷🇺 [README на русском](README.ru.md)

Part of the NEAR degen toolkit built for NEAR HACKATHON — see [Toolkit](#toolkit).

## Features

- **Alerts** 📊📈🚀🩸🎢 — 5-minute and 1-hour volume spikes, pumps and dumps over 5/15 min, and pump & dump patterns, across all NEAR DEX pools
- **Memepads** — new tokens 🆕 and alerts for nearly.trade and justhoot.fun
- **Token scanner** — send a token address or a nearly.trade / justhoot.fun / DexScreener / NearBlocks link: price, FDV, ATH, liquidity, volume, holders linked to their wallets, 15m candle chart
- **Per-chat tuning** — every chat sets its own thresholds, watchlist and muted coins
- Majors, stablecoins and bridged tokens are skipped by default, so alerts stay on small caps

## Commands

| Command | What it does |
|---|---|
| `/start`, `/stop` | enable / disable alerts in this chat |
| `/scan <address>` | token card (in DM just paste the address) |
| `/settings`, `/set <param> <value>` | alert thresholds |
| `/watch`, `/unwatch`, `/watchlist` | watchlist |
| `/ignored`, `/ignore`, `/unignore`, `/resetignore` | muted coins |
| `/top` | top NEAR pools by 1h volume |
| `/nearly`, `/hoot` | top memepad tokens |
| `/lang en` / `/lang ru` | chat language (English by default) |
| `/status` | scanner status |

In groups the bot reads plain messages with addresses only if it is an admin or privacy mode is off (@BotFather → /setprivacy → Disable); otherwise use `/scan`.

### Default alert thresholds

| Setting | Default | Meaning |
|---|---|---|
| `min_liq` | $5,000 | minimum pool liquidity |
| `min_vol5m` / `vol_x` | $2,000 / 5× | 5-min volume spike vs the 6h average |
| `min_vol1h` | $10,000 | 1-hour volume spike |
| `pump` / `dump` | 15% | price move over 5/15 min |
| `pd_rise` / `pd_fall` / `pd_window` | 30% / 20% / 60 min | pump & dump pattern |
| `cooldown` | 30 min | pause between identical alerts per pool |

## How it works

```
GeckoTerminal (pools, OHLCV) ──► gecko.py ──┐
DexScreener (memepads, prices) ► dexscreener.py ─┼─► detector.py (spike / pump / dump / P&D rules)
FastNear RPC + API (metadata, holders) ► scanner.py ┘          │
                                                        bot.py ─► Telegram (python-telegram-bot)
                                                        SQLite: chats, settings, watchlists
```

| File | Role |
|---|---|
| `bot.py` | Telegram handlers, scheduled scans, alert delivery |
| `detector.py` | Alert rules and price history |
| `gecko.py` | GeckoTerminal client |
| `dexscreener.py` | DexScreener client, memepad detection |
| `scanner.py` | Token card and chart |
| `i18n.py` | English / Russian texts |

All data sources are free, no API keys.

## Run it yourself

Requirements: Python 3.10+, a bot token from [@BotFather](https://t.me/BotFather).

```bash
git clone https://github.com/LoveTon-crypto/near-dex-bot.git
cd near-dex-bot
python3 -m venv venv
venv/bin/pip install -r requirements.txt
cp .env.example .env        # then put your BOT_TOKEN in .env
venv/bin/python bot.py
```

Send `/start` to the bot to enable alerts, or paste a token contract such as `batman-4.nearlytrade.near` to scan it.

### Production (systemd)

```bash
git clone https://github.com/LoveTon-crypto/near-dex-bot.git /opt/near-dex-bot
cd /opt/near-dex-bot && python3 -m venv venv
cp .env.example .env        # put BOT_TOKEN
```

Create a systemd service `nearbot` (`WorkingDirectory=/opt/near-dex-bot`, `ExecStart=/opt/near-dex-bot/venv/bin/python bot.py`), then run `bash deploy.sh`. Updates afterwards: `nearbot-update`.

## Toolkit

Three open-source Telegram tools for NEAR memecoin traders, each in its own repo:

| Tool | Live | Repo |
|---|---|---|
| **NEAR Analyzer** — token scanner, wallet PnL, memepad alerts, new deploys feed, caller PnL | [@nearai_agent](https://t.me/nearai_agent) · [chat](https://t.me/neardegen) · [deploys](https://t.me/neardeploys) | [near-analyzer-bot](https://github.com/LoveTon-crypto/near-analyzer-bot) |
| **NEAR DEX Alerts** — volume spikes, pumps, dumps and pump & dumps across NEAR DEXes | [@nearaidex_bot](https://t.me/nearaidex_bot) | this repo |
| **NEAR Wallet Tracker** — real-time activity of named wallets | [@nearwallettrack_bot](https://t.me/nearwallettrack_bot) | [near-wallet-tracker](https://github.com/LoveTon-crypto/near-wallet-tracker) |
