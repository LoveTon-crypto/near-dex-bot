"""Telegram-бот: следит за DEX-активностью сети NEAR и шлёт алерты в чаты (RU / EN)."""
from __future__ import annotations

import asyncio
import hashlib
import html
import json
import logging
import os
import re
import sqlite3
import time

from dotenv import load_dotenv
from telegram import (BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto,
                      LinkPreviewOptions, Update)
from telegram.constants import ChatAction, ChatType, ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from detector import DEFAULT_IGNORE, DEFAULT_SETTINGS, Alert, PriceHistory, detect, f, is_bridged, price_str, usd
from dexscreener import PADS, DexScreener, is_nearly, pad_link, pad_name, pad_of
from gecko import Gecko
from i18n import COMMANDS, SETTING_HELP, lang_of, t
from scanner import Scanner, TokenCard, age_fmt, extract_address, pct_fmt, price_fmt, render_chart

load_dotenv()
logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("bot")

BOT_TOKEN = os.environ["BOT_TOKEN"]
NETWORK = os.getenv("NETWORK", "near")
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "120"))   # сек между сканами
TOP_PAGES = int(os.getenv("TOP_PAGES", "3"))             # 20 пулов на страницу
DB_PATH = os.getenv("DB_PATH", "bot.db")
DEFAULT_LANG = os.getenv("DEFAULT_LANG", "ru")           # язык чатов, где язык ещё не определён
DISCOVER_INTERVAL = int(os.getenv("DISCOVER_INTERVAL", "600"))  # поиск новых токенов мемпадов, сек

NO_PREVIEW = LinkPreviewOptions(is_disabled=True)
EMOJI = {"volume5m": "📊", "volume1h": "📈", "pump": "🚀", "dump": "🩸", "pumpdump": "🎢"}


# ---------- хранилище ----------
class Store:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS chats (chat_id INTEGER PRIMARY KEY, settings TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS watch (chat_id INTEGER, pool TEXT, label TEXT,
                                              PRIMARY KEY (chat_id, pool));
            CREATE TABLE IF NOT EXISTS nearly_tokens (address TEXT PRIMARY KEY, symbol TEXT, first_seen REAL);
            CREATE TABLE IF NOT EXISTS ignore_list (chat_id INTEGER PRIMARY KEY, symbols TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS calls (chat_id INTEGER, token TEXT, user TEXT, mcap REAL, ts REAL,
                                              PRIMARY KEY (chat_id, token));
            CREATE TABLE IF NOT EXISTS scan_keys (key TEXT PRIMARY KEY, token TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS chat_lang (chat_id INTEGER PRIMARY KEY, lang TEXT NOT NULL,
                                                  manual INTEGER NOT NULL DEFAULT 0);
        """)
        self.db.commit()

    def subscribe(self, chat_id: int):
        self.db.execute("INSERT OR IGNORE INTO chats VALUES (?, ?)", (chat_id, json.dumps(DEFAULT_SETTINGS)))
        self.db.commit()

    def unsubscribe(self, chat_id: int):
        self.db.execute("DELETE FROM chats WHERE chat_id=?", (chat_id,))
        self.db.execute("DELETE FROM watch WHERE chat_id=?", (chat_id,))
        self.db.commit()

    def chats(self) -> dict[int, dict]:
        rows = self.db.execute("SELECT chat_id, settings FROM chats").fetchall()
        return {cid: {**DEFAULT_SETTINGS, **json.loads(s)} for cid, s in rows}

    def settings(self, chat_id: int) -> dict | None:
        row = self.db.execute("SELECT settings FROM chats WHERE chat_id=?", (chat_id,)).fetchone()
        return {**DEFAULT_SETTINGS, **json.loads(row[0])} if row else None

    def set(self, chat_id: int, key: str, value: float):
        s = self.settings(chat_id) or dict(DEFAULT_SETTINGS)
        s[key] = value
        self.db.execute("INSERT OR REPLACE INTO chats VALUES (?, ?)", (chat_id, json.dumps(s)))
        self.db.commit()

    # язык чата: берётся из языка Telegram у того, кто пишет команды, или задаётся /lang
    def lang(self, chat_id: int) -> str:
        row = self.db.execute("SELECT lang FROM chat_lang WHERE chat_id=?", (chat_id,)).fetchone()
        return row[0] if row else DEFAULT_LANG

    def auto_lang(self, chat_id: int, lang: str):
        row = self.db.execute("SELECT manual FROM chat_lang WHERE chat_id=?", (chat_id,)).fetchone()
        if row and row[0]:
            return  # язык выбран вручную через /lang — не трогаем
        self.db.execute("INSERT OR REPLACE INTO chat_lang VALUES (?, ?, 0)", (chat_id, lang))
        self.db.commit()

    def set_lang(self, chat_id: int, lang: str):
        self.db.execute("INSERT OR REPLACE INTO chat_lang VALUES (?, ?, 1)", (chat_id, lang))
        self.db.commit()

    def ignored(self, chat_id: int) -> set[str]:
        row = self.db.execute("SELECT symbols FROM ignore_list WHERE chat_id=?", (chat_id,)).fetchone()
        return set(json.loads(row[0])) if row else set(DEFAULT_IGNORE)

    def set_ignored(self, chat_id: int, symbols: set[str] | None):
        if symbols is None:
            self.db.execute("DELETE FROM ignore_list WHERE chat_id=?", (chat_id,))
        else:
            self.db.execute("INSERT OR REPLACE INTO ignore_list VALUES (?, ?)",
                            (chat_id, json.dumps(sorted(symbols))))
        self.db.commit()

    def nearly_tokens(self) -> list[str]:
        return [r[0] for r in self.db.execute("SELECT address FROM nearly_tokens").fetchall()]

    def add_nearly(self, address: str, symbol: str) -> bool:
        cur = self.db.execute("INSERT OR IGNORE INTO nearly_tokens VALUES (?, ?, ?)",
                              (address, symbol, time.time()))
        self.db.commit()
        return cur.rowcount > 0

    # сканер: кто первым прислал токен в чат и при какой капитализации
    def call(self, chat_id: int, token: str, user: str, mcap: float) -> tuple[str, float]:
        row = self.db.execute("SELECT user, mcap FROM calls WHERE chat_id=? AND token=?", (chat_id, token)).fetchone()
        if row:
            return row[0], row[1]
        if mcap > 0:
            self.db.execute("INSERT INTO calls VALUES (?, ?, ?, ?, ?)", (chat_id, token, user, mcap, time.time()))
            self.db.commit()
        return user, mcap

    def scan_key(self, token: str) -> str:
        key = hashlib.sha1(token.encode()).hexdigest()[:16]
        self.db.execute("INSERT OR IGNORE INTO scan_keys VALUES (?, ?)", (key, token))
        self.db.commit()
        return key

    def token_by_key(self, key: str) -> str | None:
        row = self.db.execute("SELECT token FROM scan_keys WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def add_watch(self, chat_id: int, pool: str, label: str):
        self.db.execute("INSERT OR REPLACE INTO watch VALUES (?, ?, ?)", (chat_id, pool, label))
        self.db.commit()

    def remove_watch(self, chat_id: int, addr: str) -> int:
        cur = self.db.execute("DELETE FROM watch WHERE chat_id=? AND (pool=? OR label LIKE ?)",
                              (chat_id, addr, f"%{addr}%"))
        self.db.commit()
        return cur.rowcount

    def watches(self, chat_id: int | None = None) -> list[tuple[int, str, str]]:
        if chat_id is None:
            return self.db.execute("SELECT chat_id, pool, label FROM watch").fetchall()
        return self.db.execute("SELECT chat_id, pool, label FROM watch WHERE chat_id=?", (chat_id,)).fetchall()


store = Store(DB_PATH)
gecko = Gecko(NETWORK)
dex = DexScreener()
scanner = Scanner()
history = PriceHistory()
cooldowns: dict[tuple[int, str, str], float] = {}
last_scan = {"ts": 0.0, "pools": 0, "alerts": 0}


def L(update: Update) -> str:
    """Язык для ответа на команду. Заодно запоминает язык чата для алертов."""
    lang = lang_of(update.effective_user.language_code if update.effective_user else None)
    store.auto_lang(update.effective_chat.id, lang)
    return store.lang(update.effective_chat.id)


# ---------- форматирование ----------
def pct(x: float) -> str:
    return f"{x:+.1f}%"


def fmt_alert(alerts: list[Alert], watched: bool, lang: str) -> str:
    p = alerts[0].pool
    v = p.vol
    lines = [f"{EMOJI.get(a.kind, '⚡')} <b>{html.escape(t(lang, a.kind, **a.args))}</b>" for a in alerts] + [
        f"<b>{html.escape(p.name)}</b> · {html.escape(p.dex)}" + (f" · {t(lang, 'watched')}" if watched else ""),
        t(lang, "price_line", p=price_str(p.price), c5=pct(p.chg.get("m5", 0)), c1=pct(p.chg.get("h1", 0)),
          c24=pct(p.chg.get("h24", 0))),
        t(lang, "vol_line", v5=usd(v.get("m5", 0)), v1=usd(v.get("h1", 0)), v24=usd(v.get("h24", 0))),
        t(lang, "liq_line", l=usd(p.liq)) + (f" · FDV {usd(p.fdv)}" if p.fdv else ""),
        t(lang, "tx_line", b=p.tx_m5["buys"], s=p.tx_m5["sells"]),
        f"<code>{html.escape(p.base_address)}</code>",
        links(p),
    ]
    return "\n".join(lines)


def fmt_new(p, lang: str) -> str:
    return "\n".join([
        t(lang, "new_token", pad=pad_name(p), sym=html.escape(p.base_symbol)),
        f"<b>{html.escape(p.name)}</b> · Rhea",
        t(lang, "new_price", p=price_str(p.price), l=usd(p.liq)) + (f" · FDV {usd(p.fdv)}" if p.fdv else ""),
        t(lang, "new_vol", v=usd(p.vol.get("h1", 0))),
        f"<code>{html.escape(p.base_address)}</code>",
        links(p),
    ])


def links(p) -> str:
    a = html.escape(p.base_address)
    if p.source != "gecko":
        return (f'<a href="{html.escape(pad_link(p))}">{pad_name(p)}</a>'
                f' · <a href="https://dexscreener.com/near/{html.escape(p.address)}">DexScreener</a>')
    return (f'<a href="https://www.geckoterminal.com/{NETWORK}/pools/{html.escape(p.address)}">GeckoTerminal</a>'
            f' · <a href="https://dexscreener.com/search?q={a}">DexScreener</a>')


async def send(ctx, cid: int, text: str) -> bool:
    try:
        await ctx.bot.send_message(cid, text, parse_mode=ParseMode.HTML, link_preview_options=NO_PREVIEW)
        return True
    except Exception as e:  # чат удалён / бот выгнан
        log.warning("Не удалось отправить в %s: %s", cid, e)
        if "chat not found" in str(e).lower() or "kicked" in str(e).lower():
            store.unsubscribe(cid)
        return False


async def is_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE, lang: str) -> bool:
    chat = update.effective_chat
    if chat.type == ChatType.PRIVATE:
        return True
    member = await ctx.bot.get_chat_member(chat.id, update.effective_user.id)
    if member.status in ("administrator", "creator"):
        return True
    await update.effective_message.reply_text(t(lang, "admins_only"))
    return False


# ---------- сканер ----------
async def scan(ctx: ContextTypes.DEFAULT_TYPE):
    chats = store.chats()
    if not chats:
        return
    watches = store.watches()
    watched_by_chat: dict[int, set[str]] = {}
    for cid, pool, _ in watches:
        watched_by_chat.setdefault(cid, set()).add(pool)

    pools = {}
    gecko_pools = []
    for page in range(1, TOP_PAGES + 1):
        gecko_pools += await gecko.top_pools(page)
    gecko_pools += await gecko.new_pools(1)
    for p in gecko_pools:
        if not is_nearly(p.base_address):  # токены мемпадов берём из DexScreener
            pools[p.address] = p
    watch_addrs = sorted({pool for _, pool, _ in watches if not pool.startswith("ref")} - set(pools))
    if watch_addrs:
        for p in await gecko.pools_multi(watch_addrs):
            pools[p.address] = p
    if any(s["nearly"] or s["hoot"] for s in chats.values()) or any(w.startswith("ref") for _, w, _ in watches):
        for p in (await dex.pools_for(store.nearly_tokens())).values():
            pools[p.address] = p

    now = time.time()
    for p in pools.values():
        history.add(p.address, p.price, now)

    sent = 0
    for cid, s in chats.items():
        mine = watched_by_chat.get(cid, set())
        skip = store.ignored(cid)
        lang = store.lang(cid)
        for p in pools.values():
            watched = p.address in mine
            if not watched:
                if p.base_symbol.upper() in skip:
                    continue  # крупная монета / стейблкоин
                if s["skip_bridged"] and is_bridged(p):
                    continue  # мостовые монеты (LTC, ETH и т.п. через Near Intents)
                if p.source != "gecko" and not s.get(p.source, 1):
                    continue  # мемпад выключен в настройках
            fresh = []
            for a in detect(p, s, history, watched=watched, now=now):
                key = (cid, p.address, a.kind)
                if now - cooldowns.get(key, 0) >= s["cooldown"] * 60:
                    cooldowns[key] = now
                    fresh.append(a)
            if fresh and await send(ctx, cid, fmt_alert(fresh, watched, lang)):  # один пул — одно сообщение
                sent += 1
    # чистим старые кулдауны
    for k in [k for k, ts in cooldowns.items() if now - ts > 6 * 3600]:
        cooldowns.pop(k, None)
    last_scan.update(ts=now, pools=len(pools), alerts=sent)
    log.info("Скан: %d пулов, %d алертов", len(pools), sent)


async def discover(ctx: ContextTypes.DEFAULT_TYPE):
    """Ищет токены мемпадов (Nearly, JustHoot) и сообщает о новых."""
    found = await dex.discover()
    if not found:
        return
    known = store.nearly_tokens()
    seeded = {pad_of(a) for a in known}  # мемпады, по которым база уже собрана
    fresh = []
    for addr, p in found.items():
        if store.add_nearly(addr, p.base_symbol) and p.source in seeded:
            created = f(p.created_at) / 1000
            if created and time.time() - created < 24 * 3600:  # пул создан за последние сутки
                fresh.append(p)
    log.info("Мемпады: найдено %d токенов, новых %d, всего в базе %d",
             len(found), len(fresh), len(store.nearly_tokens()))
    if not fresh:
        return
    for cid, s in store.chats().items():
        if not s["nearly_new"]:
            continue
        lang = store.lang(cid)
        for p in fresh:
            if s.get(p.source, 1):
                await send(ctx, cid, fmt_new(p, lang))


# ---------- сканер токенов ----------
def nb(acc: str) -> str:
    return f"https://nearblocks.io/address/{html.escape(acc)}"


def fmt_card(c: TokenCard, lang: str, caller: tuple[str, float] | None) -> str:
    link = html.escape(c.pair_url) if c.pair_url else nb(c.address)
    head = f"${html.escape(c.symbol.upper())} · ⏱ {age_fmt(c.created_ms)}"
    pad = pad_of(c.address)
    if pad:
        head += f" · {PADS[pad][1]}"
    lines = [f'<a href="{link}"><b>{html.escape(c.name)}</b></a>', head, "",
             f"<code>{html.escape(c.address)}</code>", ""]
    if c.price:
        fdv = f"💰 FDV <b>{usd(c.fdv)}</b>" + (f"   🔥 ATH <b>{usd(c.ath_mcap)}</b>" if c.ath_mcap else "")
        lines += [
            f"💵 PRICE <b>{price_fmt(c.price)}</b>",
            fdv,
            f"💧 LIQ <b>{usd(c.liq)}</b>",
            f"🔄 {t(lang, 'volume_24h')} <b>{usd(c.vol24)}</b> · TXNS <b>{c.txns24}</b>",
            f"📊 1H <b>{pct_fmt(c.chg.get('h1', 0))}</b> · 6H <b>{pct_fmt(c.chg.get('h6', 0))}</b>"
            f" · 24H <b>{pct_fmt(c.chg.get('h24', 0))}</b>",
        ]
    else:
        lines.append(t(lang, "scan_no_market"))
    if caller and caller[1] > 0 and c.fdv > 0:
        ch = (c.fdv / caller[1] - 1) * 100
        lines += ["", f"🎯 <b>{html.escape(caller[0])}</b> · {usd(caller[1])} → {usd(c.fdv)}  <b>{ch:+.2f}%</b>"]
    lines.append("")
    if c.holders:
        n = f"{c.holders_total}+" if c.holders_more else str(c.holders_total)
        lines.append(t(lang, "holders_line", n=n, p=f"{c.top10:.1f}%"))
        people = [h for h in c.holders if not h[2]]
        cells = [f'{i}. 👤 <a href="{nb(acc)}">{p:.2f}%</a>' for i, (acc, p, _) in enumerate(people, 1)]
        for i in range(0, len(cells), 2):
            lines.append("   ".join(cells[i:i + 2]))
        pools = [h for h in c.holders if h[2]]
        if pools:
            lines.append(t(lang, "pools_line") + " " + " · ".join(
                f'<a href="{nb(acc)}">{html.escape(acc if len(acc) <= 24 else acc[:21] + "…")}</a> {p:.2f}%'
                for acc, p, _ in pools))
    else:
        lines.append(t(lang, "no_holders"))
    return "\n".join(lines)


def card_keyboard(c: TokenCard, lang: str) -> InlineKeyboardMarkup:
    row = []
    if c.pair_url:
        row.append(InlineKeyboardButton("📈 DexScreener", url=c.pair_url))
    pad = pad_of(c.address)
    if pad:
        row.append(InlineKeyboardButton(PADS[pad][1], url=PADS[pad][2].format(a=c.address)))
    row.append(InlineKeyboardButton(t(lang, "btn_holders"), url=f"https://nearblocks.io/token/{c.address}#tokenHolders"))
    refresh = [InlineKeyboardButton(t(lang, "btn_refresh"), callback_data="rf:" + store.scan_key(c.address))]
    return InlineKeyboardMarkup([row, refresh])


def visible_len(s: str) -> int:
    return len(html.unescape(re.sub(r"<[^>]+>", "", s)))


async def build_card(update: Update, address: str, lang: str):
    c = await scanner.card(address)
    if c is None:
        return None, None, None, None
    user = update.effective_user.first_name if update.effective_user else "?"
    caller = store.call(update.effective_chat.id, address, user or "?", c.fdv)
    png = await asyncio.to_thread(render_chart, c) if c.candles else None
    return c, fmt_card(c, lang, caller), card_keyboard(c, lang), png


async def do_scan(update: Update, ctx: ContextTypes.DEFAULT_TYPE, text: str, quiet: bool):
    lang = L(update)
    msg = update.effective_message
    address, ref = extract_address(text)
    if ref:
        address = await scanner.resolve_pair(ref)
        if not address:
            if not quiet:
                await msg.reply_text(t(lang, "scan_no_pair"))
            return
    if not address:
        if not quiet:
            await msg.reply_html(t(lang, "scan_usage"))
        return
    await ctx.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    c, text_card, kb, png = await build_card(update, address, lang)
    if c is None:
        if not quiet:
            await msg.reply_html(t(lang, "scan_not_token", a=html.escape(address)))
        return
    if png and visible_len(text_card) <= 1024:
        await msg.reply_photo(png, caption=text_card, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        if png:
            await msg.reply_photo(png)
        await msg.reply_html(text_card, reply_markup=kb, link_preview_options=NO_PREVIEW)


async def cmd_scan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await do_scan(update, ctx, " ".join(ctx.args), quiet=False)


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Адрес токена или ссылка, присланные обычным сообщением."""
    text = update.effective_message.text or ""
    address, ref = extract_address(text)
    if address or ref:
        # в группах молчим, если адрес оказался не токеном (могли прислать просто кошелёк)
        await do_scan(update, ctx, text, quiet=update.effective_chat.type != ChatType.PRIVATE)


async def on_refresh(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    lang = L(update)
    address = store.token_by_key(q.data.split(":", 1)[1])
    if not address:
        await q.answer(t(lang, "scan_expired"), show_alert=True)
        return
    c, text_card, kb, png = await build_card(update, address, lang)
    if c is None:
        await q.answer(t(lang, "scan_expired"), show_alert=True)
        return
    try:
        if q.message.photo and png and visible_len(text_card) <= 1024:
            await q.edit_message_media(InputMediaPhoto(png, caption=text_card, parse_mode=ParseMode.HTML),
                                       reply_markup=kb)
        elif q.message.photo:
            await q.edit_message_reply_markup(reply_markup=kb)
        else:
            await q.edit_message_text(text_card, parse_mode=ParseMode.HTML, reply_markup=kb,
                                      link_preview_options=NO_PREVIEW)
    except Exception as e:  # например, «message is not modified»
        log.info("Обновление карточки: %s", e)
    await q.answer(t(lang, "refreshed"))


# ---------- команды ----------
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = L(update)
    if not await is_admin(update, ctx, lang):
        return
    store.subscribe(update.effective_chat.id)
    await update.effective_message.reply_html(t(lang, "started") + t(lang, "help"), reply_markup=LANG_KB)


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_html(t(L(update), "help"))


async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = L(update)
    if not await is_admin(update, ctx, lang):
        return
    store.unsubscribe(update.effective_chat.id)
    await update.effective_message.reply_text(t(lang, "stopped"))


async def cmd_lang(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = L(update)
    if not await is_admin(update, ctx, lang):
        return
    choice = (ctx.args[0].lower() if ctx.args else "")
    if choice not in ("ru", "en"):
        code = (update.effective_user.language_code if update.effective_user else None) or "—"
        await update.effective_message.reply_text(t(lang, "lang_pick", code=code), reply_markup=LANG_KB)
        return
    store.set_lang(update.effective_chat.id, choice)
    await update.effective_message.reply_text(t(choice, "lang_set"))


LANG_KB = InlineKeyboardMarkup([[InlineKeyboardButton("🇬🇧 English", callback_data="lang:en"),
                                 InlineKeyboardButton("🇷🇺 Русский", callback_data="lang:ru")]])


async def on_lang_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    lang = L(update)
    if update.effective_chat.type != ChatType.PRIVATE:
        member = await ctx.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
        if member.status not in ("administrator", "creator"):
            await q.answer(t(lang, "admins_only"), show_alert=True)
            return
    choice = q.data.split(":", 1)[1]
    store.set_lang(update.effective_chat.id, choice)
    await q.answer()
    try:
        await q.edit_message_text(t(choice, "lang_set"))
    except Exception:
        pass


async def cmd_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = L(update)
    s = store.settings(update.effective_chat.id)
    if s is None:
        await update.effective_message.reply_text(t(lang, "not_subscribed"))
        return
    rows = [f"<code>{k}</code> = <b>{s[k]:g}</b> — {SETTING_HELP[lang][k]}" for k in DEFAULT_SETTINGS]
    await update.effective_message.reply_html(
        t(lang, "settings_title") + "\n" + "\n".join(rows) + "\n\n" + t(lang, "settings_example"))


async def cmd_set(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = L(update)
    if not await is_admin(update, ctx, lang):
        return
    if len(ctx.args) != 2 or ctx.args[0] not in DEFAULT_SETTINGS:
        await update.effective_message.reply_html(t(lang, "set_usage", p=", ".join(DEFAULT_SETTINGS)))
        return
    try:
        val = float(ctx.args[1].replace(",", "."))
        if val < 0:
            raise ValueError
    except ValueError:
        await update.effective_message.reply_text(t(lang, "set_bad_value"))
        return
    store.set(update.effective_chat.id, ctx.args[0], val)
    await update.effective_message.reply_html(f"✅ <code>{ctx.args[0]}</code> = <b>{val:g}</b>")


async def cmd_watch(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = L(update)
    if not await is_admin(update, ctx, lang):
        return
    if not ctx.args:
        await update.effective_message.reply_html(t(lang, "watch_usage"))
        return
    cid = update.effective_chat.id
    store.subscribe(cid)
    addr = ctx.args[0].strip()
    if "nearly.trade/" in addr or "justhoot.fun/" in addr:
        addr = addr.rstrip("/").split("/")[-1]
    liq = t(lang, "liq_short")
    if is_nearly(addr):
        p = (await dex.pools_for([addr])).get(addr)
        if not p:
            await update.effective_message.reply_text(t(lang, "watch_pad_missing"))
            return
        store.add_nearly(addr, p.base_symbol)
        store.add_watch(cid, p.address, f"{p.name} ({pad_name(p)})")
        await update.effective_message.reply_html(
            f"{t(lang, 'watch_added')} {html.escape(p.name)} · {pad_name(p)} · {liq} {usd(p.liq)}")
        return
    pools = await gecko.resolve(addr)
    if not pools:
        await update.effective_message.reply_text(t(lang, "watch_missing"))
        return
    for p in pools:
        store.add_watch(cid, p.address, f"{p.name} ({p.dex})")
    await update.effective_message.reply_html(t(lang, "watch_added") + "\n" + "\n".join(
        f"• {html.escape(p.name)} · {html.escape(p.dex)} · {liq} {usd(p.liq)}" for p in pools))


async def cmd_unwatch(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = L(update)
    if not await is_admin(update, ctx, lang):
        return
    if not ctx.args:
        await update.effective_message.reply_text(t(lang, "unwatch_usage"))
        return
    n = store.remove_watch(update.effective_chat.id, ctx.args[0])
    await update.effective_message.reply_text(t(lang, "unwatch_done", n=n))


async def cmd_watchlist(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = L(update)
    rows = store.watches(update.effective_chat.id)
    if not rows:
        await update.effective_message.reply_text(t(lang, "watchlist_empty"))
        return
    await update.effective_message.reply_html(t(lang, "watchlist_title") + "\n" + "\n".join(
        f"• {html.escape(label)}\n  <code>{html.escape(pool)}</code>" for _, pool, label in rows))


def _syms(args) -> set[str]:
    return {a.strip().lstrip("$").upper() for a in args if a.strip()}


async def cmd_ignored(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = L(update)
    syms = sorted(store.ignored(update.effective_chat.id))
    await update.effective_message.reply_html(t(lang, "ignored_list", s=", ".join(syms) or "—"))


async def cmd_ignore(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = L(update)
    if not await is_admin(update, ctx, lang):
        return
    new = _syms(ctx.args)
    if not new:
        await update.effective_message.reply_html(t(lang, "ignore_usage"))
        return
    cid = update.effective_chat.id
    store.set_ignored(cid, store.ignored(cid) | new)
    await update.effective_message.reply_text(t(lang, "ignore_done", s=", ".join(sorted(new))))


async def cmd_unignore(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = L(update)
    if not await is_admin(update, ctx, lang):
        return
    rm = _syms(ctx.args)
    if not rm:
        await update.effective_message.reply_html(t(lang, "unignore_usage"))
        return
    cid = update.effective_chat.id
    store.set_ignored(cid, store.ignored(cid) - rm)
    await update.effective_message.reply_text(t(lang, "unignore_done", s=", ".join(sorted(rm))))


async def cmd_resetignore(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = L(update)
    if not await is_admin(update, ctx, lang):
        return
    store.set_ignored(update.effective_chat.id, None)
    await update.effective_message.reply_text(t(lang, "resetignore_done"))


async def cmd_top(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = L(update)
    skip = store.ignored(update.effective_chat.id)
    pools = [p for p in await gecko.top_pools(1) if p.base_symbol.upper() not in skip]
    pools.sort(key=lambda p: p.vol.get("h1", 0), reverse=True)
    if not pools:
        await update.effective_message.reply_text(t(lang, "top_fail"))
        return
    rows = [f"{i}. <b>{html.escape(p.name)}</b> — {usd(p.vol.get('h1', 0))} {t(lang, 'h1')}, "
            f"{pct(p.chg.get('h1', 0))}, {t(lang, 'liq_short')} {usd(p.liq)}" for i, p in enumerate(pools[:10], 1)]
    await update.effective_message.reply_html(t(lang, "top_title") + "\n" + "\n".join(rows))


async def pad_top(update: Update, pad: str):
    lang = L(update)
    name = PADS[pad][1]
    tokens = [a for a in store.nearly_tokens() if pad_of(a) == pad]
    if not tokens:
        await update.effective_message.reply_text(t(lang, "pad_wait", name=name))
        return
    pools = sorted((await dex.pools_for(tokens)).values(), key=lambda p: p.vol.get("h24", 0), reverse=True)
    rows = []
    for i, p in enumerate(pools[:15], 1):
        ds = f"https://dexscreener.com/near/{html.escape(p.address)}"
        rows.append(f'{i}. <a href="{ds}"><b>{html.escape(p.base_symbol)}</b></a> — '
                    f"{usd(p.vol.get('h24', 0))} {t(lang, 'h24')}, {pct(p.chg.get('h24', 0))}, "
                    f"{t(lang, 'liq_short')} {usd(p.liq)}\n"
                    f'    <a href="{ds}">DexScreener</a> · <a href="{html.escape(pad_link(p))}">{name}</a>')
    await update.effective_message.reply_html(
        t(lang, "pad_title", name=name, n=len(tokens)) + "\n\n" + "\n".join(rows), link_preview_options=NO_PREVIEW)


async def cmd_nearly(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await pad_top(update, "nearly")


async def cmd_hoot(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await pad_top(update, "hoot")


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = L(update)
    ts = last_scan["ts"]
    ago = t(lang, "ago", s=int(time.time() - ts)) if ts else t(lang, "never")
    await update.effective_message.reply_text(t(
        lang, "status", net=NETWORK, ago=ago, pools=last_scan["pools"], alerts=last_scan["alerts"],
        chats=len(store.chats()), iv=SCAN_INTERVAL, w=DEFAULT_SETTINGS["pd_window"]))


async def on_startup(app: Application):
    """Меню команд: русское для русскоязычных пользователей Telegram, английское для остальных."""
    try:
        await app.bot.set_my_commands([BotCommand(c, d) for c, d in COMMANDS["en"]])
        for code in ("ru", "uk", "be", "kk"):
            await app.bot.set_my_commands([BotCommand(c, d) for c, d in COMMANDS["ru"]], language_code=code)
    except Exception as e:
        log.warning("Не удалось задать меню команд: %s", e)


async def on_shutdown(app: Application):
    await gecko.close()
    await dex.close()
    await scanner.close()


def main():
    app = Application.builder().token(BOT_TOKEN).post_init(on_startup).post_shutdown(on_shutdown).build()
    for name, fn in [("start", cmd_start), ("help", cmd_help), ("stop", cmd_stop), ("lang", cmd_lang),
                     ("settings", cmd_settings), ("set", cmd_set), ("watch", cmd_watch),
                     ("unwatch", cmd_unwatch), ("watchlist", cmd_watchlist),
                     ("top", cmd_top), ("nearly", cmd_nearly), ("hoot", cmd_hoot),
                     ("ignored", cmd_ignored), ("ignore", cmd_ignore),
                     ("unignore", cmd_unignore), ("resetignore", cmd_resetignore), ("status", cmd_status),
                     ("scan", cmd_scan)]:
        app.add_handler(CommandHandler(name, fn))
    app.add_handler(CallbackQueryHandler(on_refresh, pattern=r"^rf:"))
    app.add_handler(CallbackQueryHandler(on_lang_button, pattern=r"^lang:(ru|en)$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.job_queue.run_repeating(discover, interval=DISCOVER_INTERVAL, first=3)
    app.job_queue.run_repeating(scan, interval=SCAN_INTERVAL, first=40)
    log.info("Бот запущен, сеть %s, интервал %ss", NETWORK, SCAN_INTERVAL)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
