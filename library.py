"""星际公民数据查询的纯逻辑（UEX API 客户端，不依赖 AstrBot，可单独测试）。

数据源：UEX（uexcorp.space）公开 API v2，含飞船参数、商品与各终端实时买卖价。
本模块负责：HTTP 拉取 + 带缓存的端点访问 + 模糊匹配 + 生成给回复模型看的摘要文本。
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

UEX_BASE = "https://api.uexcorp.space/2.0"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AstrBot-SC-Plugin"

# 各端点的缓存时长（秒）
CACHE_TTL = {"vehicles": 86400, "commodities": 21600, "terminals": 86400, "prices": 1800}


def _http_get_json(url: str, timeout: int = 25):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as exc:
        raise RuntimeError(f"数据源访问失败: {exc}") from exc
    if isinstance(body, dict) and "data" in body:
        return body["data"]
    return body


def _match(query: str, *candidates: str) -> float:
    """粗略模糊匹配：小写化后的包含/前缀打分。"""
    q = str(query or "").strip().lower()
    if not q:
        return 0.0
    best = 0.0
    for cand in candidates:
        c = str(cand or "").lower()
        if not c:
            continue
        if q == c:
            best = max(best, 1.0)
        if q in c:
            best = max(best, 0.8)
        if c in q:
            best = max(best, 0.6)
        # 词级匹配（如 "polaris" 命中 "rsi polaris"）
        words = [w for w in c.replace("_", " ").split() if len(w) > 2]
        if any(q == w for w in words):
            best = max(best, 0.9)
    return best


class UEXClient:
    def __init__(self, base: str = UEX_BASE, timeout: int = 25) -> None:
        self.base = base.rstrip("/")
        self.timeout = timeout
        self._cache: dict[str, tuple[float, list]] = {}

    def get(self, endpoint: str, **params):
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
        url = f"{self.base}/{endpoint.strip('/')}/" + (f"?{query}" if query else "")
        return _http_get_json(url, self.timeout)

    def _cached(self, key: str, endpoint: str) -> list:
        now = time.time()
        hit = self._cache.get(key)
        if hit and now - hit[0] < CACHE_TTL.get(key, 3600):
            return hit[1]
        data = self.get(endpoint) or []
        self._cache[key] = (now, data)
        return data

    # ---------------- 飞船 ----------------
    def vehicles(self) -> list:
        return self._cached("vehicles", "vehicles")

    def find_vehicle(self, name: str) -> dict | None:
        vehicles = self.vehicles()
        best, best_score = None, 0.0
        for v in vehicles:
            score = _match(
                name, v.get("name"), v.get("name_full"), v.get("slug")
            )
            if score > best_score:
                best, best_score = v, score
        return best if best_score >= 0.6 else None

    @staticmethod
    def vehicle_summary(v: dict) -> str:
        flags = []
        flag_map = {
            "is_cargo": "货运", "is_mining": "采矿", "is_salvage": "打捞",
            "is_exploration": "探索", "is_medical": "医疗", "is_military": "军用",
            "is_carrier": "母舰", "is_racing": "竞速", "is_refinery": "精炼",
            "is_science": "科研", "is_ground_vehicle": "地面载具", "is_concept": "概念船",
            "is_starter": "新手船", "is_stealth": "隐形",
        }
        for key, label in flag_map.items():
            if v.get(key):
                flags.append(label)
        lines = [
            f"船名：{v.get('name_full') or v.get('name')}",
            f"厂商：{v.get('company_name') or '未知'}",
        ]
        if flags:
            lines.append("定位：" + "、".join(flags))
        if v.get("crew"):
            lines.append(f"标准/满员船员：{v['crew']}")
        if v.get("scu"):
            lines.append(f"货舱：{v['scu']} SCU")
        for k, label, unit in (
            ("length", "长", "米"), ("beam", "宽", "米"), ("height", "高", "米"),
        ):
            if v.get(k):
                lines.append(f"{label}: {v[k]} {unit}")
        if v.get("mass"):
            lines.append(f"质量：{int(v['mass']) / 1000:.0f} 吨")
        if v.get("fuel_quantum"):
            lines.append(f"量子燃料：{v['fuel_quantum']}")
        if v.get("fuel_hydrogen"):
            lines.append(f"氢燃料：{v['fuel_hydrogen']}")
        if v.get("url_store"):
            lines.append(f"官方页面：{v['url_store']}")
        return "\n".join(lines)

    # ---------------- 商品 ----------------
    def commodities(self) -> list:
        return self._cached("commodities", "commodities")

    def find_commodity(self, name: str) -> dict | None:
        best, best_score = None, 0.0
        for c in self.commodities():
            score = _match(name, c.get("name"), c.get("code"), c.get("slug"))
            if score > best_score:
                best, best_score = c, score
        return best if best_score >= 0.6 else None

    @staticmethod
    def commodity_summary(c: dict) -> str:
        lines = [f"商品：{c.get('name')}（{c.get('kind') or '未知类型'}）"]
        if c.get("price_buy") is not None:
            lines.append(f"参考买入均价：{c['price_buy']} aUEC")
        if c.get("price_sell") is not None:
            lines.append(f"参考卖出均价：{c['price_sell']} aUEC")
        if c.get("wiki"):
            lines.append(f"百科：{c['wiki']}")
        lines.append("提示：具体到各终端的实时价可用 sc_commodity_prices 查询。")
        return "\n".join(lines)

    # ---------------- 终端实时价 ----------------
    def terminals(self) -> list:
        return self._cached("terminals", "terminals")

    def terminal_name(self, terminal_id) -> str:
        tid = str(terminal_id or "")
        for t in self.terminals():
            if str(t.get("id")) == tid:
                return f"{t.get('name')}（{t.get('location_name') or ''}）".replace("（）", "")
        return f"终端#{tid}"

    def commodity_prices(self, name: str, limit: int = 6) -> tuple[str, str] | None:
        c = self.find_commodity(name)
        if not c:
            return None
        rows = self.get("commodities_prices", commodity_name=str(c.get("slug") or "")) or []
        if not rows:
            rows = self.get("commodities_prices", id_commodity=c.get("id")) or []
        if not rows:
            return (c.get("name"), "没有查到各终端的实时价格。")
        buys = sorted(
            (r for r in rows if r.get("price_buy") not in (None, 0, "0")),
            key=lambda r: -float(r["price_buy"]),
        )
        sells = sorted(
            (r for r in rows if r.get("price_sell") not in (None, 0, "0")),
            key=lambda r: float(r["price_sell"]),
        )
        lines = [f"商品：{c.get('name')}"]
        if buys:
            lines.append("买价最高的终端（卖给这里最赚）：")
            for r in buys[:limit]:
                lines.append(
                    f"- {self.terminal_name(r.get('id_terminal'))}：买入 {r['price_buy']} aUEC"
                )
        if sells:
            lines.append("卖价最低的终端（从这里买最省）：")
            for r in sells[:limit]:
                lines.append(
                    f"- {self.terminal_name(r.get('id_terminal'))}：卖出 {r['price_sell']} aUEC"
                )
        return (c.get("name"), "\n".join(lines))
