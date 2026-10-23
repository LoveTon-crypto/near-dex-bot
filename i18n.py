"""Тексты бота на русском и английском."""
from __future__ import annotations

RU_LANGS = ("ru", "uk", "be", "kk")  # для этих языков Telegram — русский, для остальных — английский


def lang_of(language_code: str | None) -> str:
    return "ru" if (language_code or "").lower().startswith(RU_LANGS) else "en"


T = {
    # --- алерты ---
    "volume5m": {"ru": "Всплеск объёма: {v} за 5 мин ({r} к среднему)",
                 "en": "Volume spike: {v} in 5 min ({r} vs average)"},
    "volume1h": {"ru": "Всплеск объёма: {v} за 1 ч ({r} к среднему)",
                 "en": "Volume spike: {v} in 1h ({r} vs average)"},
    "pump": {"ru": "Памп: {c} за {m} мин", "en": "Pump: {c} in {m} min"},
    "dump": {"ru": "Дамп: {c} за {m} мин", "en": "Dump: {c} in {m} min"},
    "pumpdump": {"ru": "Pump & Dump: {rise} до пика, затем {fall} за {m} мин",
                 "en": "Pump & Dump: {rise} to peak, then {fall} within {m} min"},
    "watched": {"ru": "⭐ в вотчлисте", "en": "⭐ watchlist"},
    "price_line": {"ru": "Цена: {p} ({c5} 5м, {c1} 1ч, {c24} 24ч)",
                   "en": "Price: {p} ({c5} 5m, {c1} 1h, {c24} 24h)"},
    "vol_line": {"ru": "Объём: {v5} 5м · {v1} 1ч · {v24} 24ч", "en": "Volume: {v5} 5m · {v1} 1h · {v24} 24h"},
    "liq_line": {"ru": "Ликвидность: {l}", "en": "Liquidity: {l}"},
    "tx_line": {"ru": "Сделки 5м: {b} buy / {s} sell", "en": "Trades 5m: {b} buy / {s} sell"},
    "new_token": {"ru": "🆕 <b>Новый токен на {pad}: {sym}</b>", "en": "🆕 <b>New token on {pad}: {sym}</b>"},
    "new_price": {"ru": "Цена: {p} · Ликвидность: {l}", "en": "Price: {p} · Liquidity: {l}"},
    "new_vol": {"ru": "Объём 1ч: {v}", "en": "Volume 1h: {v}"},

    # --- команды ---
    "help": {
        "ru": ("<b>NEAR DEX Alerts</b> — слежу за DEX сети NEAR и пишу о резких скачках объёма, "
               "пампах, дампах и pump&dump.\n\n"
               "/start — включить алерты в этом чате\n"
               "/stop — выключить\n"
               "/settings — пороги срабатывания\n"
               "/set &lt;параметр&gt; &lt;значение&gt; — изменить порог\n"
               "/watch &lt;адрес токена или пула&gt; — добавить в вотчлист (без фильтра ликвидности)\n"
               "/unwatch &lt;адрес&gt; — убрать из вотчлиста\n"
               "/watchlist — вотчлист\n"
               "/ignored — монеты, по которым алерты не приходят\n"
               "/ignore &lt;тикер&gt; — не присылать по монете (можно несколько через пробел)\n"
               "/unignore &lt;тикер&gt; — снова присылать\n"
               "/top — топ пулов по объёму за 1ч\n"
               "/nearly — топ токенов мемпада nearly.trade\n"
               "/hoot — топ токенов мемпада justhoot.fun\n"
               "/scan &lt;адрес токена&gt; — карточка токена: цена, холдеры, график "
               "(можно просто прислать адрес или ссылку nearly.trade / justhoot.fun / dexscreener)\n"
               "/lang ru|en — язык бота в этом чате\n"
               "/status — состояние сканера"),
        "en": ("<b>NEAR DEX Alerts</b> — I watch NEAR DEXes and report sharp volume spikes, "
               "pumps, dumps and pump&dumps.\n\n"
               "/start — enable alerts in this chat\n"
               "/stop — disable alerts\n"
               "/settings — alert thresholds\n"
               "/set &lt;param&gt; &lt;value&gt; — change a threshold\n"
               "/watch &lt;token or pool address&gt; — add to watchlist (no liquidity filter)\n"
               "/unwatch &lt;address&gt; — remove from watchlist\n"
               "/watchlist — show watchlist\n"
               "/ignored — coins with alerts muted\n"
               "/ignore &lt;ticker&gt; — mute a coin (several allowed, space-separated)\n"
               "/unignore &lt;ticker&gt; — unmute\n"
               "/top — top pools by 1h volume\n"
               "/nearly — top tokens on the nearly.trade memepad\n"
               "/hoot — top tokens on the justhoot.fun memepad\n"
               "/scan &lt;token address&gt; — token card: price, holders, chart "
               "(or just send an address or a nearly.trade / justhoot.fun / dexscreener link)\n"
               "/lang ru|en — bot language in this chat\n"
               "/status — scanner status"),
    },
    "started": {"ru": "✅ Алерты включены.\n\n", "en": "✅ Alerts enabled.\n\n"},
    "stopped": {"ru": "⏸ Алерты выключены. /start — включить снова.",
                "en": "⏸ Alerts disabled. /start to turn them back on."},
    "admins_only": {"ru": "Менять настройки могут только админы чата.",
                    "en": "Only chat admins can change settings."},
    "not_subscribed": {"ru": "Чат не подписан. Нажмите /start.", "en": "This chat is not subscribed. Send /start."},
    "settings_title": {"ru": "⚙️ Настройки:", "en": "⚙️ Settings:"},
    "settings_example": {"ru": "Пример: <code>/set pump 25</code>", "en": "Example: <code>/set pump 25</code>"},
    "set_usage": {"ru": "Формат: <code>/set параметр значение</code>\nПараметры: {p}",
                  "en": "Usage: <code>/set param value</code>\nParams: {p}"},
    "set_bad_value": {"ru": "Значение должно быть неотрицательным числом.", "en": "The value must be a non-negative number."},
    "watch_usage": {"ru": "Формат: <code>/watch адрес_токена</code>, например <code>/watch token.v2.ref-finance.near</code>",
                    "en": "Usage: <code>/watch token_address</code>, e.g. <code>/watch token.v2.ref-finance.near</code>"},
    "watch_pad_missing": {"ru": "Не нашёл пул этого токена на DexScreener.",
                          "en": "Couldn't find a pool for this token on DexScreener."},
    "watch_missing": {"ru": "Не нашёл такой токен или пул в сети NEAR на GeckoTerminal.",
                      "en": "Couldn't find this token or pool on NEAR in GeckoTerminal."},
    "watch_added": {"ru": "⭐ Добавлено:", "en": "⭐ Added:"},
    "liq_short": {"ru": "ликв.", "en": "liq."},
    "unwatch_usage": {"ru": "Формат: /unwatch адрес_пула или часть названия",
                      "en": "Usage: /unwatch pool_address or part of its name"},
    "unwatch_done": {"ru": "Удалено: {n}", "en": "Removed: {n}"},
    "watchlist_empty": {"ru": "Вотчлист пуст. Добавьте: /watch адрес_токена",
                        "en": "Watchlist is empty. Add one: /watch token_address"},
    "watchlist_title": {"ru": "⭐ Вотчлист:", "en": "⭐ Watchlist:"},
    "ignored_list": {"ru": ("🚫 Не присылаю алерты по (если монета не в вотчлисте):\n{s}\n\n"
                            "/ignore ТИКЕР — добавить, /unignore ТИКЕР — убрать, /resetignore — вернуть список по умолчанию"),
                     "en": ("🚫 No alerts for (unless the coin is on the watchlist):\n{s}\n\n"
                            "/ignore TICKER — add, /unignore TICKER — remove, /resetignore — restore the default list")},
    "ignore_usage": {"ru": "Формат: <code>/ignore AURORA REF</code>", "en": "Usage: <code>/ignore AURORA REF</code>"},
    "ignore_done": {"ru": "🚫 Больше не присылаю по: {s}", "en": "🚫 Muted: {s}"},
    "unignore_usage": {"ru": "Формат: <code>/unignore NEAR</code>", "en": "Usage: <code>/unignore NEAR</code>"},
    "unignore_done": {"ru": "✅ Снова присылаю по: {s}", "en": "✅ Unmuted: {s}"},
    "resetignore_done": {"ru": "Список исключений сброшен к стандартному. /ignored — посмотреть.",
                         "en": "Mute list restored to default. /ignored to view it."},
    "top_fail": {"ru": "GeckoTerminal не ответил, попробуйте позже.", "en": "GeckoTerminal didn't respond, try again later."},
    "top_title": {"ru": "🔥 Топ NEAR по объёму за 1ч:", "en": "🔥 Top NEAR pools by 1h volume:"},
    "h1": {"ru": "1ч", "en": "1h"},
    "h24": {"ru": "24ч", "en": "24h"},
    "pad_wait": {"ru": "Список токенов {name} ещё собирается, попробуйте через пару минут.",
                 "en": "Still collecting the {name} token list, try again in a couple of minutes."},
    "pad_title": {"ru": "🟢 {name}: топ по объёму за 24ч (отслеживаю {n} токенов)",
                  "en": "🟢 {name}: top by 24h volume (tracking {n} tokens)"},
    "lang_set": {"ru": "✅ Язык бота в этом чате: русский", "en": "✅ Bot language in this chat: English"},
    "lang_usage": {"ru": "Формат: /lang ru или /lang en", "en": "Usage: /lang ru or /lang en"},
    # --- сканер токенов ---
    "scan_usage": {"ru": "Пришлите адрес токена NEAR или ссылку, например:\n<code>/scan raven.nearlytrade.near</code>",
                   "en": "Send a NEAR token address or link, e.g.:\n<code>/scan raven.nearlytrade.near</code>"},
    "scan_not_token": {"ru": "Это не похоже на токен NEAR: у контракта <code>{a}</code> нет ft_metadata.",
                       "en": "This doesn't look like a NEAR token: <code>{a}</code> has no ft_metadata."},
    "scan_no_pair": {"ru": "Не нашёл пару для этой ссылки.", "en": "Couldn't find a pair for this link."},
    "scan_no_market": {"ru": "📭 Торгов на DEX пока не найдено", "en": "📭 No DEX trading found yet"},
    "volume_24h": {"ru": "VOLUME 24ч", "en": "VOLUME 24h"},
    "holders_line": {"ru": "👥 <b>{n}</b> холдеров · ТОП-10: <b>{p}</b>",
                     "en": "👥 <b>{n}</b> Holders · TOP 10: <b>{p}</b>"},
    "pools_line": {"ru": "🏊 Пулы / контракты:", "en": "🏊 Pools / contracts:"},
    "no_holders": {"ru": "👥 Холдеры: нет данных", "en": "👥 Holders: no data"},
    "btn_refresh": {"ru": "🔄 Обновить", "en": "🔄 Refresh"},
    "btn_holders": {"ru": "👥 Холдеры", "en": "👥 Holders"},
    "refreshed": {"ru": "Обновлено", "en": "Updated"},
    "scan_expired": {"ru": "Пришлите адрес токена ещё раз.", "en": "Please send the token address again."},
    "never": {"ru": "ещё не было", "en": "not yet"},
    "ago": {"ru": "{s} сек назад", "en": "{s} sec ago"},
    "status": {"ru": ("Сеть: {net}\nПоследний скан: {ago}\nПулов в скане: {pools}\nАлертов за скан: {alerts}\n"
                      "Чатов подписано: {chats}\nИнтервал: {iv} сек\n\n"
                      "Pump&dump начинает ловиться примерно через {w} мин после запуска — боту нужна история цен."),
               "en": ("Network: {net}\nLast scan: {ago}\nPools in scan: {pools}\nAlerts in scan: {alerts}\n"
                      "Subscribed chats: {chats}\nInterval: {iv} sec\n\n"
                      "Pump&dump detection starts about {w} min after launch — the bot needs price history.")},
}

SETTING_HELP = {
    "ru": {
        "min_liq": "мин. ликвидность пула, $",
        "min_vol5m": "мин. объём за 5 мин для всплеска, $",
        "vol_x": "множитель объёма к среднему",
        "min_vol1h": "мин. объём за 1ч для часового всплеска, $",
        "pump": "рост цены за 5–15 мин, %",
        "dump": "падение цены за 5–15 мин, %",
        "min_vol_move": "мин. объём за 15 мин для пампа/дампа, $",
        "pd_rise": "pump&dump: рост до пика, %",
        "pd_fall": "pump&dump: откат от пика, %",
        "pd_window": "окно pump&dump, мин",
        "cooldown": "пауза между повторами, мин",
        "skip_bridged": "1 — без мостовых монет (LTC, ETH через Intents и т.п.)",
        "nearly": "1 — следить за nearly.trade, 0 — нет",
        "hoot": "1 — следить за justhoot.fun, 0 — нет",
        "nearly_new": "1 — сообщать о новых токенах мемпадов",
        "nearly_min_liq": "мемпады: мин. ликвидность, $",
        "nearly_min_vol": "мемпады: мин. объём за 5 мин, $",
        "nearly_min_vol1h": "мемпады: мин. объём за 1 ч, $",
    },
    "en": {
        "min_liq": "min pool liquidity, $",
        "min_vol5m": "min 5-min volume for a spike, $",
        "vol_x": "volume multiple vs average",
        "min_vol1h": "min 1h volume for an hourly spike, $",
        "pump": "price rise in 5–15 min, %",
        "dump": "price drop in 5–15 min, %",
        "min_vol_move": "min 15-min volume for pump/dump, $",
        "pd_rise": "pump&dump: rise to peak, %",
        "pd_fall": "pump&dump: drop from peak, %",
        "pd_window": "pump&dump window, min",
        "cooldown": "pause between repeat alerts, min",
        "skip_bridged": "1 — skip bridged coins (LTC, ETH via Intents, etc.)",
        "nearly": "1 — track nearly.trade, 0 — off",
        "hoot": "1 — track justhoot.fun, 0 — off",
        "nearly_new": "1 — announce new memepad tokens",
        "nearly_min_liq": "memepads: min liquidity, $",
        "nearly_min_vol": "memepads: min 5-min volume, $",
        "nearly_min_vol1h": "memepads: min 1h volume, $",
    },
}

# Меню команд Telegram (подсказки при вводе «/»)
COMMANDS = {
    "ru": [("start", "включить алерты"), ("stop", "выключить алерты"), ("settings", "пороги срабатывания"),
           ("watchlist", "вотчлист"), ("ignored", "монеты без алертов"), ("top", "топ пулов NEAR за 1ч"),
           ("nearly", "топ токенов nearly.trade"), ("hoot", "топ токенов justhoot.fun"),
           ("scan", "сканер токена: цена, холдеры, график"),
           ("lang", "язык: ru / en"), ("status", "состояние сканера"), ("help", "все команды")],
    "en": [("start", "enable alerts"), ("stop", "disable alerts"), ("settings", "alert thresholds"),
           ("watchlist", "watchlist"), ("ignored", "muted coins"), ("top", "top NEAR pools by 1h volume"),
           ("nearly", "top nearly.trade tokens"), ("hoot", "top justhoot.fun tokens"),
           ("scan", "token scanner: price, holders, chart"),
           ("lang", "language: ru / en"), ("status", "scanner status"), ("help", "all commands")],
}


def t(lang: str, key: str, **kw) -> str:
    s = T[key].get(lang) or T[key]["en"]
    return s.format(**kw) if kw else s
