"""Сканер токенов NEAR: карточка токена с ценой, холдерами и графиком (как сканеры в TON).

Данные:
  • DexScreener — цена, FDV, ликвидность, объём, сделки, изменения цены
  • NEAR RPC (FastNEAR) — название, тикер, decimals, total supply из контракта
  • FastNEAR API — топ держателей токена
  • GeckoTerminal — свечи для графика (если пул там проиндексирован)
"""
from __future__ import annotations

import base64
import io
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from detector import f, usd

log = logging.getLogger("scanner")

RPC_URLS = ["https://rpc.mainnet.fastnear.com", "https://free.rpc.fastnear.com", "https://rpc.mainnet.near.org"]
FASTNEAR = "https://api.fastnear.com"
GECKO = "https://api.geckoterminal.com/api/v2"
DEXS = "https://api.dexscreener.com"
UA = {"User-Agent": "near-dex-alert-bot/1.0"}

# Адрес токена NEAR: something.near / something.tg / 64 hex-символа
ADDR_RE = re.compile(r"(?<![\w.-])((?:[a-z0-9_\-]+\.)+(?:near|tg)|[0-9a-f]{64})(?![\w.-])")
URL_RES = [
    re.compile(r"nearly\.trade/([a-z0-9_\-.]+)"),
    re.compile(r"justhoot\.fun/p/([a-z0-9_\-.]+)"),
    re.compile(r"nearblocks\.io/(?:token|address)/([a-z0-9_\-.]+)"),
]
DS_PAIR_RE = re.compile(r"dexscreener\.com/near/([a-z0-9_\-.:]+)")
GT_POOL_RE = re.compile(r"geckoterminal\.com/near/pools/([a-z0-9_\-.:]+)")

# Контракты DEX / лаунчпадов: среди холдеров помечаем их как пул, а не как человека
POOL_ACCOUNTS = {"nearlytrade.near", "launchpad.justhoot.near", "v2-launchpad.justhoot.near", "intents.near",
                 "veax.near", "v1.orderbook.near", "dex.intear.near", "aidols.near"}
POOL_SUFFIXES = (".ref-finance.near", ".ref-labs.near", ".rhealab.near", "ref-finance.near")


@dataclass
class TokenCard:
    address: str
    name: str = "?"
    symbol: str = "?"
    decimals: int = 0
    supply_raw: int = 0
    price: float = 0.0
    fdv: float = 0.0
    liq: float = 0.0
    vol24: float = 0.0
    txns24: int = 0
    chg: dict = field(default_factory=dict)
    created_ms: float = 0.0
    dex: str = ""
    pair_address: str = ""
    pair_url: str = ""
    holders: list = field(default_factory=list)   # [(account, pct, is_pool)]
    holders_total: int = 0
    holders_more: bool = False                     # держателей больше, чем вернул API
    all_holders: list = field(default_factory=list)  # все полученные [(account, pct, is_pool)] — для bubble map
    candles: list = field(default_factory=list)   # [(ts, o, h, l, c, v)] по возрастанию времени
    ath_mcap: float = 0.0

    @property
    def supply(self) -> float:
        return self.supply_raw / 10 ** self.decimals if self.decimals else float(self.supply_raw)

    @property
    def top10(self) -> float:
        return sum(p for _, p, pool in self.holders if not pool)


def extract_address(text: str) -> tuple[str | None, str | None]:
    """Ищет в тексте адрес токена или ссылку. Возвращает (адрес токена, адрес пары/пула для дорезолва)."""
    t = (text or "").strip().lower()
    for rx in URL_RES:
        m = rx.search(t)
        if m:
            return m.group(1).rstrip("."), None
    m = DS_PAIR_RE.search(t)
    if m:
        return None, "ds:" + m.group(1)
    m = GT_POOL_RE.search(t)
    if m:
        return None, "gt:" + m.group(1)
    m = ADDR_RE.search(t)
    return (m.group(1), None) if m else (None, None)


def is_pool_account(acc: str, token: str) -> bool:
    return acc == token or acc in POOL_ACCOUNTS or acc.endswith(POOL_SUFFIXES)


class Scanner:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=15, headers=UA)
        self._gt_pool: dict[str, str | None] = {}       # токен -> пул GeckoTerminal (кэш)
        self._chart_cache: dict[str, tuple[float, list]] = {}
        self._ath_cache: dict[str, tuple[float, float]] = {}     # токен -> (время, макс. цена)

    async def _json(self, method: str, url: str, **kw):
        try:
            r = await self.client.request(method, url, **kw)
            if r.status_code >= 400:
                log.info("HTTP %s %s", r.status_code, url)
                return None
            return r.json()
        except (httpx.HTTPError, ValueError) as e:
            log.info("Ошибка запроса %s: %s", url, e)
            return None

    async def _view(self, account: str, method: str):
        payload = {"jsonrpc": "2.0", "id": "1", "method": "query",
                   "params": {"request_type": "call_function", "finality": "final", "account_id": account,
                              "method_name": method, "args_base64": base64.b64encode(b"{}").decode()}}
        for url in RPC_URLS:
            data = await self._json("POST", url, json=payload)
            if not data:
                continue
            res = (data.get("result") or {}).get("result")
            if res is None:
                return None  # метода нет — это не токен
            try:
                return json.loads(bytes(res).decode())
            except ValueError:
                return None
        return None

    async def resolve_pair(self, ref: str) -> str | None:
        """Ссылка на пару DexScreener / пул GeckoTerminal -> адрес токена."""
        kind, pid = ref.split(":", 1)
        if kind == "ds":
            data = await self._json("GET", f"{DEXS}/latest/dex/pairs/near/{pid}")
            pairs = (data or {}).get("pairs") or []
            return pairs[0]["baseToken"]["address"] if pairs else None
        data = await self._json("GET", f"{GECKO}/networks/near/pools/{pid}")
        try:
            return data["data"]["relationships"]["base_token"]["data"]["id"].split("_", 1)[1]
        except (TypeError, KeyError, IndexError):
            return None

    async def card(self, address: str, with_chart: bool = True) -> TokenCard | None:
        c = TokenCard(address=address)
        meta = await self._view(address, "ft_metadata")
        if not isinstance(meta, dict):
            return None
        c.name = str(meta.get("name") or "?")[:60]
        c.symbol = str(meta.get("symbol") or "?")[:20]
        c.decimals = int(f(meta.get("decimals")))
        supply = await self._view(address, "ft_total_supply")
        try:
            c.supply_raw = int(supply)
        except (TypeError, ValueError):
            c.supply_raw = 0

        await self._fill_market(c)
        await self._fill_holders(c)
        if with_chart:
            await self._fill_chart(c)
        return c

    async def _fill_market(self, c: TokenCard):
        data = await self._json("GET", f"{DEXS}/tokens/v1/near/{c.address}")
        pairs = [p for p in (data if isinstance(data, list) else [])
                 if (p.get("baseToken") or {}).get("address") == c.address]
        if not pairs:
            return
        best = max(pairs, key=lambda p: f((p.get("liquidity") or {}).get("usd")))
        c.price = f(best.get("priceUsd"))
        c.liq = sum(f((p.get("liquidity") or {}).get("usd")) for p in pairs)
        c.vol24 = sum(f((p.get("volume") or {}).get("h24")) for p in pairs)
        c.txns24 = sum(int(f(((p.get("txns") or {}).get("h24") or {}).get(k)))
                       for p in pairs for k in ("buys", "sells"))
        c.chg = {k: f(v) for k, v in (best.get("priceChange") or {}).items()}
        c.created_ms = min(f(p.get("pairCreatedAt")) or 9e15 for p in pairs)
        c.created_ms = 0 if c.created_ms >= 9e15 else c.created_ms
        c.dex = best.get("dexId", "")
        c.pair_address = best.get("pairAddress", "")
        c.pair_url = best.get("url") or f"https://dexscreener.com/near/{c.pair_address}"
        c.fdv = f(best.get("fdv") or best.get("marketCap")) or c.price * c.supply

    async def _fill_holders(self, c: TokenCard):
        data = await self._json("GET", f"{FASTNEAR}/v1/ft/{c.address}/top")
        accounts = (data or {}).get("accounts") or []
        if not accounts or not c.supply_raw:
            return
        rows = []
        for a in accounts:
            try:
                bal = int(a.get("balance") or 0)
            except ValueError:
                continue
            if bal > 0:
                acc = a.get("account_id", "")
                rows.append((acc, bal * 100 / c.supply_raw, is_pool_account(acc, c.address)))
        rows.sort(key=lambda r: r[1], reverse=True)
        c.holders_total = len(rows)
        c.all_holders = rows
        c.holders_more = len(accounts) >= 100
        people = [r for r in rows if not r[2]][:10]
        pools = [r for r in rows if r[2]][:2]
        c.holders = people + pools

    async def _fill_chart(self, c: TokenCard):
        if c.address not in self._gt_pool:
            data = await self._json("GET", f"{GECKO}/networks/near/tokens/{c.address}/pools", params={"page": 1})
            pools = (data or {}).get("data") or []
            try:
                self._gt_pool[c.address] = pools[0]["attributes"]["address"] if pools else None
            except (KeyError, TypeError):
                self._gt_pool[c.address] = None
        pool = self._gt_pool.get(c.address)
        if not pool:  # пула нет или запрос не прошёл — проверим снова при следующем скане
            self._gt_pool.pop(c.address, None)
        if not pool:
            return
        cached = self._chart_cache.get(c.address)
        if cached and time.time() - cached[0] < 60:
            c.candles = cached[1]
        else:
            data = await self._json("GET", f"{GECKO}/networks/near/pools/{pool}/ohlcv/minute",
                                    params={"aggregate": 15, "limit": 96, "currency": "usd", "token": c.address})
            ohlcv = (((data or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
            c.candles = sorted((tuple(float(x) for x in row[:6]) for row in ohlcv if len(row) >= 6),
                               key=lambda r: r[0])
            self._chart_cache[c.address] = (time.time(), c.candles)
        ath_price = max((r[2] for r in c.candles), default=0.0)
        cached_ath = self._ath_cache.get(c.address)
        if cached_ath and time.time() - cached_ath[0] < 600:
            ath_price = max(ath_price, cached_ath[1])
        else:  # 4-часовые свечи примерно за полгода — для ATH
            data = await self._json("GET", f"{GECKO}/networks/near/pools/{pool}/ohlcv/hour",
                                    params={"aggregate": 4, "limit": 1000, "currency": "usd", "token": c.address})
            rows = (((data or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
            long_max = max((float(row[2]) for row in rows if len(row) >= 6), default=0.0)
            self._ath_cache[c.address] = (time.time(), long_max)
            ath_price = max(ath_price, long_max)
        if ath_price and c.supply:
            c.ath_mcap = max(ath_price * c.supply, c.fdv)

    async def close(self):
        await self.client.aclose()


# ---------- форматирование ----------
SUB = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")


def price_fmt(p: float) -> str:
    """$0.0₅1417 — как в сканерах: число нулей после запятой пишется маленькой цифрой."""
    if p <= 0:
        return "$0"
    if p >= 1:
        return f"${p:,.4f}"
    s = f"{p:.20f}".split(".")[1]
    zeros = len(s) - len(s.lstrip("0"))
    digits = s[zeros:zeros + 4].rstrip("0") or "0"
    if zeros >= 4:
        return f"$0.0{str(zeros).translate(SUB)}{digits}"
    return f"$0.{'0' * zeros}{digits}"


def age_fmt(created_ms: float) -> str:
    if not created_ms:
        return "?"
    sec = max(0, time.time() - created_ms / 1000)
    if sec < 3600:
        return f"{int(sec // 60)}m"
    if sec < 86400:
        return f"{int(sec // 3600)}h"
    return f"{int(sec // 86400)}d"


def pct_fmt(x: float) -> str:
    return f"{x:+.2f}%"


def render_chart(c: TokenCard) -> bytes | None:
    """Свечной график 15m с шапкой (тикер, MCAP, LIQ, VOL, TXNS, 1H, 6H) — картинка PNG."""
    if len(c.candles) < 3:
        return None
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    bg, fg, dim, up, down = "#15161c", "#e8e8ea", "#8a8d98", "#26a69a", "#ef5350"
    fig = plt.figure(figsize=(8, 4.8), dpi=130, facecolor=bg)
    head = fig.add_axes([0, 0.68, 1, 0.32], facecolor=bg)
    head.axis("off")
    head.set_ylim(0, 1)
    ax = fig.add_axes([0.04, 0.09, 0.84, 0.52], facecolor=bg)

    ch = c.chg.get("h24", 0)
    head.text(0.03, 0.84, c.symbol.upper(), color=fg, fontsize=17, fontweight="bold", va="center")
    head.text(0.03, 0.62, f"{c.name}  ·  {age_fmt(c.created_ms)}", color=dim, fontsize=10, va="center")
    head.text(0.97, 0.84, f"{'↑' if ch >= 0 else '↓'}{abs(ch):.2f}%", color=up if ch >= 0 else down,
              fontsize=17, fontweight="bold", ha="right", va="center")
    cols = [("MCAP", usd(c.fdv), fg), ("LIQ", usd(c.liq), fg), ("VOL", usd(c.vol24), fg),
            ("TXNS", str(c.txns24), fg)]
    for k in ("h1", "h6"):
        v = c.chg.get(k, 0)
        cols.append((k[1:] + "H", f"{'↑' if v >= 0 else '↓'}{abs(v):.2f}%", up if v >= 0 else down))
    for i, (label, val, color) in enumerate(cols):
        x = 0.03 + i * 0.16
        head.text(x, 0.36, label, color=dim, fontsize=9, va="center")
        head.text(x, 0.17, val, color=color, fontsize=11, fontweight="bold", va="center")

    w = 0.6
    for i, (_, o, h, l, cl, _) in enumerate(c.candles):
        color = up if cl >= o else down
        ax.plot([i, i], [l, h], color=color, linewidth=0.9)
        ax.add_patch(Rectangle((i - w / 2, min(o, cl)), w, max(abs(cl - o), (h - l) * 0.02 or 1e-18),
                               facecolor=color, edgecolor=color))
    last = c.candles[-1][4]
    ax.axhline(last, color=down, linestyle=":", linewidth=0.8)
    ax.set_xlim(-1, len(c.candles))
    lo, hi = min(r[3] for r in c.candles), max(r[2] for r in c.candles)
    pad = (hi - lo) * 0.08 or hi * 0.05 or 1e-18
    ax.set_ylim(lo - pad, hi + pad)
    ax.yaxis.tick_right()
    ax.tick_params(colors=dim, labelsize=8, length=0)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: price_fmt(v)[1:]))
    step = max(1, len(c.candles) // 6)
    idx = list(range(0, len(c.candles), step))
    ax.set_xticks(idx)
    ax.set_xticklabels([datetime.fromtimestamp(c.candles[i][0], timezone.utc).strftime("%H:%M") for i in idx])
    for s in ax.spines.values():
        s.set_visible(False)
    ax.grid(color="#262833", linewidth=0.6)
    ax.text(0.0, 1.02, "USD 15m · UTC", transform=ax.transAxes, color=dim, fontsize=8)
    ax.text(len(c.candles) + 0.3, last, " " + price_fmt(last)[1:] + " ", color="white", fontsize=8,
            va="center", ha="left", bbox=dict(facecolor=down, edgecolor="none", pad=1.5), clip_on=False)
    fig.text(0.5, 0.4, "NEAR Scanner", color="#ffffff", alpha=0.05, fontsize=40, ha="center", va="center",
             fontweight="bold")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=bg)
    plt.close(fig)
    return buf.getvalue()
