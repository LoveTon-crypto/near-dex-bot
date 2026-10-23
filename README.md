# NEAR DEX Alerts + Token Scanner — Telegram-бот

Бот для сети NEAR:

- **Алерты** о всплесках объёма 📊📈, пампах 🚀, дампах 🩸 и pump & dump 🎢 на DEX сети NEAR (данные GeckoTerminal).
- **Мемпады** nearly.trade и justhoot.fun: новые токены 🆕 и алерты по ним (данные DexScreener).
- **Сканер токенов**: пришлите адрес токена или ссылку (nearly.trade, justhoot.fun, dexscreener, nearblocks) —
  бот ответит карточкой с ценой, FDV, ATH, ликвидностью, объёмом, холдерами (со ссылками на кошельки в NearBlocks)
  и свечным графиком 15m.
- **Языки**: русский и английский — по языку Telegram пользователя, или вручную `/lang ru|en`.

## Команды

| Команда | Что делает |
|---|---|
| `/start`, `/stop` | включить / выключить алерты в чате |
| `/scan <адрес>` | карточка токена (в личке можно просто прислать адрес) |
| `/settings`, `/set <параметр> <значение>` | пороги алертов |
| `/watch`, `/unwatch`, `/watchlist` | вотчлист |
| `/ignored`, `/ignore`, `/unignore`, `/resetignore` | монеты без алертов |
| `/top` | топ пулов NEAR за 1ч |
| `/nearly`, `/hoot` | топ токенов мемпадов |
| `/lang ru` / `/lang en` | язык в чате |
| `/status` | состояние сканера |

В группах бот видит обычные сообщения с адресами, только если он админ группы
или у него выключен privacy mode (@BotFather → /setprivacy → Disable). Иначе используйте `/scan`.

## Обновление на сервере

```bash
nearbot-update
```

Команда скачивает свежую версию из этого репозитория, ставит библиотеки и перезапускает бота.
Токен бота (`.env`) и база (`bot.db`) хранятся только на сервере и в репозиторий не попадают.

## Первая установка

```bash
apt-get install -y git python3-venv
git clone https://github.com/LoveTon-crypto/near-dex-bot.git /opt/near-dex-bot
cd /opt/near-dex-bot && python3 -m venv venv
cp .env.example .env && nano .env   # вписать BOT_TOKEN
```

Затем создать сервис systemd `nearbot` (`ExecStart=/opt/near-dex-bot/venv/bin/python bot.py`,
`WorkingDirectory=/opt/near-dex-bot`) и выполнить `bash deploy.sh`.

## Источники данных

GeckoTerminal (пулы и свечи), DexScreener (мемпады, цены), NEAR RPC FastNEAR (метаданные токена),
FastNEAR API (холдеры), NearBlocks (ссылки на кошельки). Все бесплатные, без ключей.
