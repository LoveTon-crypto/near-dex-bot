"""Логика поиска аномалий. Не зависит от Telegram и сети — легко тестировать."""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

DEFAULT_SETTINGS = {
    "min_liq": 5_000,       # мин. ликвидность пула, $
    "min_vol5m": 2_000,     # мин. объём за 5 мин для сигнала о всплеске объёма, $
    "vol_x": 5.0,           # во сколько раз объём 5м выше среднего 5-минутного за 6ч
    "min_vol1h": 10_000,    # мин. объём за 1ч для часового всплеска, $
    "pump": 15.0,           # рост цены за 5/15 мин, %
    "dump": 15.0,           # падение цены за 5/15 мин, %
    "min_vol_move": 1_000,  # мин. объём за 15 мин, чтобы засчитать памп/дамп, $
    "pd_rise": 30.0,        # pump&dump: рост от минимума до пика, %
    "pd_fall": 20.0,        # pump&dump: падение от пика, %
    "pd_window": 60,        # окно поиска pump&dump, мин
    "cooldown": 30,         # пауза между одинаковыми алертами по пулу, мин
    "skip_bridged": 1,      # 1 = не присылать по мостовым монетам (*.omft.near, Near Intents)
    "nearly": 1,            # 1 = следить за мемпадом nearly.trade
    "hoot": 1,              # 1 = следить за мемпадом justhoot.fun
    "nearly_new": 1,        # 1 = сообщать о новых токенах на мемпадах
    "nearly_min_liq": 1_000,   # мемпады: мин. ликвидность, $
    "nearly_min_vol": 300,     # мемпады: мин. объём за 5 мин для всплеска и пампа/дампа, $
    "nearly_min_vol1h": 1_500, # мемпады: мин. объём за 1 ч для часового всплеска, $
}

# Крупные монеты и стейблкоины: по ним алерты не шлём (если они не в вотчлисте)
DEFAULT_IGNORE = {
    "USDT", "USDC", "USDT.E", "USDC.E", "DAI", "USDE", "SUSDE", "FRAX", "USD1", "FDUSD", "PYUSD", "USN",
    "NEAR", "WNEAR", "STNEAR", "LINEAR", "RNEAR", "NEARX", "XRNEAR",
    "ETH", "WETH", "STETH", "WSTETH", "BTC", "WBTC", "NBTC", "CBBTC", "SOL", "WSOL",
    "BNB", "WBNB", "XRP", "TRX", "ZEC", "TON", "AVAX", "MATIC", "POL", "ARB", "OP",
    "LTC", "DOGE", "BCH", "ADA", "SUI", "XLM", "LINK", "DOT", "APT", "HBAR", "TAO", "UNI", "AAVE",
}


def is_bridged(pool) -> bool:
    return pool.base_address.endswith(".omft.near") or "intents" in pool.dex.lower()


def f(x, default: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


@dataclass
class Pool:
    address: str
    name: str
    dex: str
    base_symbol: str
    base_address: str
    price: float
    liq: float
    fdv: float
    vol: dict          # m5, m15, m30, h1, h6, h24
    chg: dict          # m5, m15, m30, h1, h6, h24 (проценты)
    tx_m5: dict        # buys, sells
    created_at: str = ""
    source: str = "gecko"   # gecko | nearly | hoot


@dataclass
class Alert:
    kind: str          # volume5m | volume1h | pump | dump | pumpdump
    pool: Pool
    args: dict         # параметры для текста (текст собирается в i18n на языке чата)


@dataclass
class PriceHistory:
    """Хранит цены пулов за последние 3 часа, чтобы ловить pump & dump."""
    max_age: int = 3 * 3600
    data: dict = field(default_factory=dict)

    def add(self, address: str, price: float, ts: float | None = None):
        if price <= 0:
            return
        ts = ts or time.time()
        dq = self.data.setdefault(address, deque())
        dq.append((ts, price))
        while dq and dq[0][0] < ts - self.max_age:
            dq.popleft()

    def window(self, address: str, minutes: int, now: float | None = None):
        now = now or time.time()
        return [(t, p) for t, p in self.data.get(address, ()) if t >= now - minutes * 60]


def detect(pool: Pool, s: dict, history: PriceHistory, watched: bool = False,
           now: float | None = None) -> list[Alert]:
    """Возвращает список сигналов по пулу для настроек одного чата."""
    alerts: list[Alert] = []
    if pool.source != "gecko":  # мемпады: пороги для маленьких монет
        s = {**s, "min_liq": s["nearly_min_liq"], "min_vol5m": s["nearly_min_vol"],
             "min_vol_move": s["nearly_min_vol"], "min_vol1h": s["nearly_min_vol1h"]}
    if not watched and pool.liq < s["min_liq"]:
        return alerts

    v = pool.vol
    # 1. Всплеск объёма за 5 минут относительно среднего за 6 часов
    avg5 = v.get("h6", 0) / 72
    if v.get("m5", 0) >= s["min_vol5m"]:
        ratio = v["m5"] / avg5 if avg5 > 0 else float("inf")
        if ratio >= s["vol_x"]:
            r = "∞" if ratio == float("inf") else f"×{ratio:.1f}"
            alerts.append(Alert("volume5m", pool, {"v": usd(v["m5"]), "r": r}))

    # 2. Всплеск объёма за час относительно среднего за сутки
    avg1h = v.get("h24", 0) / 24
    if v.get("h1", 0) >= s["min_vol1h"]:
        ratio = v["h1"] / avg1h if avg1h > 0 else float("inf")
        if ratio >= s["vol_x"]:
            r = "∞" if ratio == float("inf") else f"×{ratio:.1f}"
            alerts.append(Alert("volume1h", pool, {"v": usd(v["h1"]), "r": r}))

    # 3. Резкий памп / дамп по данным индексатора
    if v.get("m15", v.get("m5", 0)) >= s["min_vol_move"]:
        c5, c15 = pool.chg.get("m5", 0), pool.chg.get("m15", 0)
        up_w, up = (5, c5) if c5 >= c15 else (15, c15)
        dn_w, dn = (5, c5) if c5 <= c15 else (15, c15)
        if up >= s["pump"]:
            alerts.append(Alert("pump", pool, {"c": f"{up:+.1f}%", "m": up_w}))
        if dn <= -s["dump"]:
            alerts.append(Alert("dump", pool, {"c": f"{dn:+.1f}%", "m": dn_w}))

    # 4. Pump & dump: цена выросла от минимума до пика и откатилась — по собственной истории
    pts = history.window(pool.address, int(s["pd_window"]), now)
    if len(pts) >= 3:
        peak_i = max(range(len(pts)), key=lambda i: pts[i][1])
        before = pts[: peak_i + 1]
        low = min(p for _, p in before)
        peak = pts[peak_i][1]
        cur = pts[-1][1]
        rise = (peak / low - 1) * 100 if low > 0 else 0
        fall = (cur / peak - 1) * 100
        if peak_i < len(pts) - 1 and rise >= s["pd_rise"] and fall <= -s["pd_fall"]:
            alerts.append(Alert("pumpdump", pool,
                                {"rise": f"{rise:+.0f}%", "fall": f"{fall:+.0f}%", "m": int(s["pd_window"])}))
    return alerts


def usd(x: float) -> str:
    x = f(x)
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if abs(x) >= div:
            return f"${x / div:.1f}{suf}"
    return f"${x:,.0f}"


def price_str(p: float) -> str:
    if p == 0:
        return "$0"
    if p >= 1:
        return f"${p:,.4f}"
    return f"${p:.10f}".rstrip("0")
