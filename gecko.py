"""Клиент GeckoTerminal (бесплатно, без ключа). Данные по всем DEX сети NEAR."""
from __future__ import annotations

import asyncio
import logging
import time

import httpx

from detector import Pool, f

log = logging.getLogger("gecko")
BASE = "https://api.geckoterminal.com/api/v2"
HEADERS = {"Accept": "application/json;version=20230302", "User-Agent": "near-dex-alert-bot/1.0"}


class Gecko:
    def __init__(self, network: str = "near", min_interval: float = 6.5):
        self.network = network
        self.min_interval = min_interval  # бесплатный лимит ~10 запросов/мин
        self._last = 0.0
        self._lock = asyncio.Lock()
        self.client = httpx.AsyncClient(base_url=BASE, headers=HEADERS, timeout=20)

    async def _get(self, path: str, params: dict | None = None) -> dict | None:
        async with self._lock:
            for attempt in range(4):
                wait = self._last + self.min_interval - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
                self._last = time.monotonic()
                try:
                    r = await self.client.get(path, params=params)
                except httpx.HTTPError as e:
                    log.warning("Сеть: %s %s", path, e)
                    await asyncio.sleep(5 * (attempt + 1))
                    continue
                if r.status_code == 429:
                    log.warning("Лимит GeckoTerminal, жду…")
                    await asyncio.sleep(30 * (attempt + 1))
                    continue
                if r.status_code == 404:
                    return None
                if r.status_code >= 400:
                    log.warning("HTTP %s на %s", r.status_code, path)
                    return None
                return r.json()
        return None

    @staticmethod
    def _parse(payload: dict | None) -> list[Pool]:
        if not payload:
            return []
        data = payload.get("data") or []
        if isinstance(data, dict):
            data = [data]
        inc = {i["id"]: i.get("attributes", {}) for i in payload.get("included", [])}
        pools = []
        for d in data:
            a = d.get("attributes", {})
            rel = d.get("relationships", {})
            base_id = ((rel.get("base_token") or {}).get("data") or {}).get("id", "")
            dex_id = ((rel.get("dex") or {}).get("data") or {}).get("id", "")
            base = inc.get(base_id, {})
            dex = inc.get(dex_id, {})
            tx = (a.get("transactions") or {}).get("m5") or {}
            pools.append(Pool(
                address=a.get("address", ""),
                name=a.get("name", "?"),
                dex=dex.get("name") or dex_id,
                base_symbol=base.get("symbol") or a.get("name", "?").split("/")[0].strip(),
                base_address=base.get("address") or base_id.split("_", 1)[-1],
                price=f(a.get("base_token_price_usd")),
                liq=f(a.get("reserve_in_usd")),
                fdv=f(a.get("fdv_usd")),
                vol={k: f(v) for k, v in (a.get("volume_usd") or {}).items()},
                chg={k: f(v) for k, v in (a.get("price_change_percentage") or {}).items()},
                tx_m5={"buys": int(f(tx.get("buys"))), "sells": int(f(tx.get("sells")))},
                created_at=a.get("pool_created_at") or "",
            ))
        return pools

    async def top_pools(self, page: int = 1) -> list[Pool]:
        return self._parse(await self._get(f"/networks/{self.network}/pools",
                                           {"page": page, "include": "base_token,quote_token,dex"}))

    async def new_pools(self, page: int = 1) -> list[Pool]:
        return self._parse(await self._get(f"/networks/{self.network}/new_pools",
                                           {"page": page, "include": "base_token,quote_token,dex"}))

    async def pools_multi(self, addresses: list[str]) -> list[Pool]:
        out = []
        for i in range(0, len(addresses), 30):
            chunk = ",".join(addresses[i:i + 30])
            out += self._parse(await self._get(f"/networks/{self.network}/pools/multi/{chunk}",
                                               {"include": "base_token,quote_token,dex"}))
        return out

    async def resolve(self, address: str) -> list[Pool]:
        """Адрес токена → его пулы; иначе пробуем как адрес пула."""
        pools = self._parse(await self._get(f"/networks/{self.network}/tokens/{address}/pools",
                                            {"include": "base_token,quote_token,dex"}))
        if pools:
            return pools[:3]
        return self._parse(await self._get(f"/networks/{self.network}/pools/{address}",
                                           {"include": "base_token,quote_token,dex"}))

    async def close(self):
        await self.client.aclose()
