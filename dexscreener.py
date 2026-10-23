"""Мемпады NEAR (nearly.trade, justhoot.fun): токены торгуются на Rhea. Данные — DexScreener."""
from __future__ import annotations

import asyncio
import logging

import httpx

from detector import Pool, f

log = logging.getLogger("dexscreener")
BASE = "https://api.dexscreener.com"
# код мемпада: (суффикс адреса токена, название, ссылка на токен, поисковые запросы)
PADS = {
    "nearly": (".nearlytrade.near", "Nearly", "https://nearly.trade/{a}",
               ["nearlytrade", "nearlytrade.near", "nearlytrade wNEAR", "nearlytrade NEARLY", "nearlytrade RHEA"]),
    "hoot": (".justhoot.near", "JustHoot", "https://justhoot.fun/p/{a}",
             ["justhoot", "hoot.near", "launchpad.justhoot.near", "v2-launchpad.justhoot.near", "justhoot wNEAR"]),
}


def pad_of(addr: str) -> str | None:
    for key, (suffix, *_rest) in PADS.items():
        if addr.endswith(suffix):
            return key
    return None


def is_nearly(addr: str) -> bool:  # любой поддерживаемый мемпад
    return pad_of(addr) is not None


def pad_link(p) -> str:
    return PADS[p.source][2].format(a=p.base_address)


def pad_name(p) -> str:
    return PADS[p.source][1]


class DexScreener:
    def __init__(self):
        self.client = httpx.AsyncClient(base_url=BASE, timeout=20,
                                        headers={"User-Agent": "near-dex-alert-bot/1.0"})

    async def _get(self, path: str, params: dict | None = None):
        for attempt in range(3):
            try:
                r = await self.client.get(path, params=params)
            except httpx.HTTPError as e:
                log.warning("Сеть: %s %s", path, e)
                await asyncio.sleep(3 * (attempt + 1))
                continue
            if r.status_code == 429:
                await asyncio.sleep(20 * (attempt + 1))
                continue
            if r.status_code >= 400:
                log.warning("HTTP %s на %s", r.status_code, path)
                return None
            return r.json()
        return None

    @staticmethod
    def _pool(d: dict) -> Pool | None:
        base, quote = d.get("baseToken") or {}, d.get("quoteToken") or {}
        if d.get("chainId") != "near" or not is_nearly(base.get("address", "")):
            return None
        tx = (d.get("txns") or {}).get("m5") or {}
        pad = pad_of(base.get("address", ""))
        return Pool(
            address=d.get("pairAddress", ""),
            name=f"{base.get('symbol', '?')} / {quote.get('symbol', '?')}",
            dex=f"{PADS[pad][1]} · Rhea",
            base_symbol=base.get("symbol", "?"),
            base_address=base.get("address", ""),
            price=f(d.get("priceUsd")),
            liq=f((d.get("liquidity") or {}).get("usd")),
            fdv=f(d.get("fdv") or d.get("marketCap")),
            vol={k: f(v) for k, v in (d.get("volume") or {}).items()},
            chg={k: f(v) for k, v in (d.get("priceChange") or {}).items()},
            tx_m5={"buys": int(f(tx.get("buys"))), "sells": int(f(tx.get("sells")))},
            created_at=str(d.get("pairCreatedAt") or ""),
            source=pad,
        )

    async def discover(self) -> dict[str, Pool]:
        """Ищет токены мемпадов через поиск DexScreener. Возвращает {адрес токена: лучший пул}."""
        found: dict[str, Pool] = {}
        for q in [q for pad in PADS.values() for q in pad[3]]:
            data = await self._get("/latest/dex/search", {"q": q}) or {}
            for d in data.get("pairs") or []:
                p = self._pool(d)
                if p and (p.base_address not in found or p.liq > found[p.base_address].liq):
                    found[p.base_address] = p
        return found

    async def pools_for(self, tokens: list[str]) -> dict[str, Pool]:
        """Главный (самый ликвидный) пул для каждого токена."""
        out: dict[str, Pool] = {}
        for i in range(0, len(tokens), 30):
            data = await self._get("/tokens/v1/near/" + ",".join(tokens[i:i + 30]))
            for d in data if isinstance(data, list) else []:
                p = self._pool(d)
                if p and (p.base_address not in out or p.liq > out[p.base_address].liq):
                    out[p.base_address] = p
        return out

    async def close(self):
        await self.client.aclose()
