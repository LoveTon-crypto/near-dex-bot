"""Bubble map холдеров токена NEAR: пузыри по долям + связи между кошельками.

Связи ищем по истории переводов (FastNEAR Transfers API, нужен FASTNEAR_API_KEY):
  • холдер отправлял этот токен другому холдеру;
  • холдер отправлял NEAR другому холдеру (или получал от него);
  • оба кошелька получили первые NEAR от одного и того же «спонсора»
    (если этот спонсор финансировал немного холдеров — иначе это биржа или сервис).
Плюс бесплатная связь без API: субаккаунты одного владельца (a.alice.near и b.alice.near).
"""
from __future__ import annotations

import asyncio
import io
import logging
import math
import os
import time
from dataclasses import dataclass, field

import httpx

from detector import f

log = logging.getLogger("bubbles")

TRANSFERS = "https://transfers.main.fastnear.com/v0/transfers"
MAX_HOLDERS = 50          # сколько крупнейших холдеров рисуем
MAX_QUERIED = 40          # для скольких ищем связи (по 3 запроса на кошелёк)
FUNDER_MAX_FANOUT = 6     # «спонсор» больше стольких холдеров — скорее биржа/сервис, не считаем связью
# биржи, релейеры и сервисы: общий «спонсор» из этого списка — не признак одного владельца
SERVICE_HINTS = ("binance", "okx", "bybit", "kucoin", "gate", "huobi", "htx", "mexc", "bitget", "coinbase",
                 "kraken", "relay", "faucet", "intents", "hot", "sweat", "meteor", "mynear", "here", "bitte",
                 "intear", "nearlytrade", "justhoot", "ref-finance", "rhea", "aurora", "wallet", "bridge")
COLORS = [("#ff4d4f", "🔴"), ("#52c41a", "🟢"), ("#1677ff", "🔵"), ("#fadb14", "🟡"), ("#9254de", "🟣"),
          ("#fa8c16", "🟠"), ("#13c2c2", "🩵"), ("#eb2f96", "🩷"), ("#a0522d", "🟤"), ("#ffffff", "⚪")]


@dataclass
class BubbleMap:
    holders: list                        # [(account, pct, is_pool)] по убыванию доли
    links: set = field(default_factory=set)            # {(i, j)} индексы в holders
    clusters: list = field(default_factory=list)       # [[i, j, ...]] по убыванию суммарной доли
    has_api: bool = False

    @property
    def captured(self) -> float:
        return sum(p for _, p, _ in self.holders)


def _parent(acc: str) -> str | None:
    """bob.alice.near -> alice.near (у implicit-аккаунтов и верхнего уровня родителя нет)."""
    parts = acc.split(".")
    return ".".join(parts[1:]) if len(parts) >= 3 else None


def _is_service(acc: str) -> bool:
    a = acc.lower()
    return a in ("near", "tg", "system") or any(h in a for h in SERVICE_HINTS)


class BubbleBuilder:
    def __init__(self):
        self.key = os.getenv("FASTNEAR_API_KEY", "").strip()
        headers = {"User-Agent": "near-dex-alert-bot/1.0"}
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        self.client = httpx.AsyncClient(timeout=20, headers=headers)
        self.sem = asyncio.Semaphore(6)
        self.cache: dict[str, tuple[float, BubbleMap]] = {}

    async def _transfers(self, account: str, direction: str, asset: str, desc: bool, limit: int) -> list:
        body = {"account_id": account, "direction": direction, "asset_id": asset, "desc": desc,
                "limit": limit, "ignore_system": True}
        async with self.sem:
            try:
                r = await self.client.post(TRANSFERS, json=body)
                if r.status_code >= 400:
                    log.info("Transfers %s: HTTP %s %s", account, r.status_code, r.text[:200])
                    return []
                return (r.json() or {}).get("transfers") or []
            except (httpx.HTTPError, ValueError) as e:
                log.info("Transfers %s: %s", account, e)
                return []

    async def build(self, token: str, holders: list) -> BubbleMap:
        cached = self.cache.get(token)
        if cached and time.time() - cached[0] < 600:
            return cached[1]
        hs = holders[:MAX_HOLDERS]
        bm = BubbleMap(holders=hs, has_api=bool(self.key))
        index = {acc: i for i, (acc, _, _) in enumerate(hs)}
        people = [i for i, (_, _, pool) in enumerate(hs) if not pool]

        def link(a: str, b: str):
            if a in index and b in index and a != b:
                i, j = sorted((index[a], index[b]))
                if not hs[i][2] and not hs[j][2]:  # пулы не связываем — через них торгуют все
                    bm.links.add((i, j))

        # 1) субаккаунты одного владельца
        by_parent: dict[str, list[str]] = {}
        for i in people:
            p = _parent(hs[i][0])
            if p and p.count(".") == 1 and not _is_service(p):  # alice.near, но не user.platform.near
                by_parent.setdefault(p, []).append(hs[i][0])
        for accs in by_parent.values():
            if 2 <= len(accs) <= FUNDER_MAX_FANOUT:
                for a in accs[1:]:
                    link(accs[0], a)
        for i in people:  # сам родитель тоже холдер
            p = _parent(hs[i][0])
            if p in index:
                link(hs[i][0], p)

        # 2) история переводов
        if self.key:
            queried = [hs[i][0] for i in people[:MAX_QUERIED]]
            tasks = []
            for acc in queried:
                tasks.append(self._transfers(acc, "sender", token, True, 100))         # кому слал токен
                tasks.append(self._transfers(acc, "sender", "native:near", True, 100))  # кому слал NEAR
                tasks.append(self._transfers(acc, "receiver", "native:near", False, 3))  # первые пополнения
            results = await asyncio.gather(*tasks)
            funders: dict[str, set[str]] = {}
            for n, acc in enumerate(queried):
                sent_ft, sent_near, first_in = results[3 * n: 3 * n + 3]
                for row in sent_ft + sent_near:
                    other = row.get("other_account_id") or row.get("receipt_account_id") or ""
                    link(acc, other)
                for row in first_in:
                    src = row.get("other_account_id") or row.get("predecessor_id") or ""
                    if src and src != acc:
                        link(acc, src)
                        funders.setdefault(src, set()).add(acc)
            for src, accs in funders.items():
                if 2 <= len(accs) <= FUNDER_MAX_FANOUT and not _is_service(src) and src not in index:
                    accs = sorted(accs)
                    for a in accs[1:]:
                        link(accs[0], a)

        # кластеры (компоненты связности)
        parent = list(range(len(hs)))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for i, j in bm.links:
            parent[find(i)] = find(j)
        groups: dict[int, list[int]] = {}
        for i in range(len(hs)):
            groups.setdefault(find(i), []).append(i)
        bm.clusters = sorted((sorted(g) for g in groups.values() if len(g) >= 2),
                             key=lambda g: -sum(hs[i][1] for i in g))
        self.cache[token] = (time.time(), bm)
        return bm

    async def close(self):
        await self.client.aclose()


# ---------- картинка ----------
def _layout(bm: BubbleMap, radii: list[float]) -> list[tuple[float, float]]:
    """Простая силовая раскладка: связанные пузыри притягиваются, все отталкиваются, лёгкая гравитация к центру."""
    import numpy as np
    n = len(radii)
    rng = np.random.default_rng(7)
    golden = math.pi * (3 - math.sqrt(5))
    pos = np.array([[math.cos(i * golden) * 6 * math.sqrt(i + 1), math.sin(i * golden) * 6 * math.sqrt(i + 1)]
                    for i in range(n)], dtype=float)
    pos += rng.normal(0, 0.5, pos.shape)
    r = np.array(radii)
    links = list(bm.links)
    for step in range(400):
        delta = pos[:, None, :] - pos[None, :, :]
        dist = np.linalg.norm(delta, axis=2) + 1e-6
        min_d = r[:, None] + r[None, :] + 1.5
        overlap = np.clip(min_d - dist, 0, None)
        np.fill_diagonal(overlap, 0)
        force = (delta / dist[..., None] * overlap[..., None]).sum(axis=1) * 0.5
        for i, j in links:
            d = pos[j] - pos[i]
            dl = np.linalg.norm(d) + 1e-6
            target = r[i] + r[j] + 3
            pull = (dl - target) * 0.08 * d / dl
            force[i] += pull
            force[j] -= pull
        force -= pos * 0.004
        pos += force * (1 - step / 450)
    return [tuple(p) for p in pos]


def render_bubbles(bm: BubbleMap, symbol: str, name: str, holders_total: str, supply_txt: str) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle

    bg, fg, dim = "#0b0d1a", "#e8e8ea", "#8a8d98"
    n = len(bm.holders)
    radii = [max(0.9, math.sqrt(max(p, 0.01)) * 3.2) for _, p, _ in bm.holders]
    pos = _layout(bm, radii)
    color_of = {}
    for k, cl in enumerate(bm.clusters):
        for i in cl:
            color_of[i] = COLORS[k % len(COLORS)][0]

    fig = plt.figure(figsize=(8, 8.4), dpi=130, facecolor=bg)
    ax = fig.add_axes([0.02, 0.06, 0.96, 0.82], facecolor=bg)
    ax.set_aspect("equal")
    ax.axis("off")
    for i, j in bm.links:
        (x1, y1), (x2, y2) = pos[i], pos[j]
        ax.plot([x1, x2], [y1, y2], color=color_of.get(i, "#aaaaaa"), linewidth=1.4, alpha=0.8, zorder=1)
    for i, ((acc, p, pool), (x, y), rad) in enumerate(zip(bm.holders, pos, radii)):
        if pool:
            fc, ec, alpha = "#2f3b5c", "#6d7fb0", 0.9
        elif i in color_of:
            fc, ec, alpha = color_of[i], "#ffffff", 0.9
        else:
            fc, ec, alpha = "#3a3d4d", "#555a6e", 0.85
        ax.add_patch(Circle((x, y), rad, facecolor=fc, edgecolor=ec, linewidth=0.8, alpha=alpha, zorder=2))
        if rad >= 1.6:
            ax.text(x, y + rad * 0.12, f"#{i + 1}" if not pool else "POOL", color="#111" if i in color_of else fg,
                    fontsize=min(11, 4 + rad * 1.2), ha="center", va="center", fontweight="bold", zorder=3)
            ax.text(x, y - rad * 0.35, f"{p:.1f}%", color="#222" if i in color_of else dim,
                    fontsize=min(9, 3 + rad), ha="center", va="center", zorder=3)
    xs = [x for x, _ in pos]
    ys = [y for _, y in pos]
    pad = max(radii) + 2
    ax.set_xlim(min(xs) - pad, max(xs) + pad)
    ax.set_ylim(min(ys) - pad, max(ys) + pad)

    fig.text(0.04, 0.955, name[:40], color=fg, fontsize=17, fontweight="bold", va="center")
    fig.text(0.04, 0.915, f"${symbol.upper()}   ·   {holders_total} holders   ·   top {n} = {bm.captured:.1f}%   ·   "
             f"{len(bm.links)} links   ·   {supply_txt} total", color=dim, fontsize=9.5, va="center")
    fig.text(0.04, 0.025, "● NEAR BLOCKCHAIN", color=dim, fontsize=9, va="center")
    fig.text(0.96, 0.025, "NEAR SCANNER", color=dim, fontsize=9, va="center", ha="right")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=bg)
    plt.close(fig)
    return buf.getvalue()


def short(acc: str) -> str:
    if len(acc) == 64 and all(ch in "0123456789abcdef" for ch in acc):
        return acc[:6] + "…" + acc[-4:]
    return acc if len(acc) <= 22 else acc[:19] + "…"


def supply_fmt(x: float) -> str:
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if x >= div:
            return f"{x / div:.2f}{suf}"
    return f"{f(x):.0f}"
