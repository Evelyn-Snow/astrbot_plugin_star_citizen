"""星际公民（Star Citizen）数据查询：飞船参数、商品价格、终端行情。

数据来自 UEX（uexcorp.space）公开 API v2。以 LLM 工具形式提供，
群里直接问“北极星号参数”“农业素现在什么价”即可触发。
"""

from __future__ import annotations

import asyncio

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
from astrbot.core.config.astrbot_config import AstrBotConfig

from .library import UEXClient

NAME = "astrbot_plugin_star_citizen"


class StarCitizenData(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.conf = config
        self._client: UEXClient | None = None
        self._last_err = ""

    def _enabled(self) -> bool:
        return bool(self.conf.get("enabled", True))

    def _client_obj(self) -> UEXClient:
        if self._client is None:
            self._client = UEXClient(
                base=str(self.conf.get("uex_base") or "https://api.uexcorp.space/2.0"),
                timeout=int(self.conf.get("timeout") or 25),
            )
        return self._client

    async def _call(self, fn, *args):
        self._last_err = ""
        try:
            return await asyncio.to_thread(fn, *args)
        except Exception as exc:
            logger.warning(f"[{NAME}] UEX 查询失败: {exc}")
            self._last_err = str(exc)
            return None

    @filter.llm_tool(name="sc_ship_info")
    async def sc_ship_info(self, event: AstrMessageEvent, ship_name: str) -> str:
        """查询星际公民（Star Citizen）飞船/载具的参数：船员、货舱、尺寸、燃料、定位等。
        用户问某艘船的参数、能不能拉货、多大的时候使用。ship_name 用飞船英文名（如 Polaris、Carrack）。

        Args:
            ship_name(string): 飞船英文名或型号，例如 Polaris / Carrack / Cutlass Black
        """
        if not self._enabled():
            return "星际公民数据查询未启用。"
        client = self._client_obj()
        vehicle = await self._call(client.find_vehicle, ship_name)
        if not vehicle:
            if getattr(self, "_last_err", ""):
                return (
                    f"查询数据源失败（{self._last_err[:80]}）。"
                    "向用户说明稍等再试，然后用相同的 ship_name 重试一次。"
                )
            return (
                f"没有在飞船数据库里找到「{ship_name}」。"
                "请用飞船英文名再试（例如 Polaris、Carrack），找不到时不要编造参数。"
            )
        return client.vehicle_summary(vehicle)

    @filter.llm_tool(name="sc_commodity_info")
    async def sc_commodity_info(self, event: AstrMessageEvent, commodity_name: str) -> str:
        """查询星际公民商品的参考均价与类型（Agricum、Quantum Fuel 等采矿/精炼/贸易商品）。
        用户问某种商品值多少钱、是什么的时候使用。commodity_name 用英文名。

        Args:
            commodity_name(string): 商品英文名，例如 Agricium / Quantainium / Medical Supplies
        """
        if not self._enabled():
            return "星际公民数据查询未启用。"
        client = self._client_obj()
        commodity = await self._call(client.find_commodity, commodity_name)
        if not commodity:
            if getattr(self, "_last_err", ""):
                return (
                    f"查询数据源失败（{self._last_err[:80]}）。"
                    "向用户说明稍等再试，然后用相同的 commodity_name 重试一次。"
                )
            return f"没有找到商品「{commodity_name}」，请用英文名再试，找不到时不要编造。"
        return client.commodity_summary(commodity)

    @filter.llm_tool(name="sc_commodity_prices")
    async def sc_commodity_prices(
        self,
        event: AstrMessageEvent,
        commodity_name: str,
        limit: int = 5,
    ) -> str:
        """查询星际公民商品在各终端的实时买卖价：哪里买最便宜、卖给哪里最赚。
        用户问“XX 现在多少钱”“哪里买 XX 划算”“XX 卖哪里”时使用。commodity_name 用英文名。

        Args:
            commodity_name(string): 商品英文名，例如 Agricium / Laranite / Medical Supplies
            limit(number): 买价最高和卖价最低各列出几个终端，默认 5
        """
        if not self._enabled():
            return "星际公民数据查询未启用。"
        client = self._client_obj()
        result = await self._call(
            client.commodity_prices, commodity_name, max(1, min(int(limit or 5), 10))
        )
        if not result:
            if getattr(self, "_last_err", ""):
                return (
                    f"查询数据源失败（{self._last_err[:80]}）。"
                    "向用户说明稍等再试，然后用相同的 commodity_name 重试一次。"
                )
            return f"没有找到商品「{commodity_name}」的价格数据，不要编造。"
        _name, summary = result
        return summary
