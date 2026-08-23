#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
除权除息(股本变迁)数据获取 —— 通过 pytdx 从通达信行情服务器拉取。

与 Go 库 injoyai/tdx 的 GetGbbq 同源: 服务器返回相同数据, 解析字段一致
(Go: protocol/model_gbbq.go gbbq.Decode; Python: pytdx parser/get_xdxr_info.py)。
只保留 category==1(除权除息) 的记录, 其余股本变动类别不参与复权。
"""

import datetime as dt
import logging
from typing import List, Optional

from .adjust import XRXDEvent

log = logging.getLogger(__name__)

# 通达信市场编码: 深=0, 沪=1, 北=2 (与 pytdx / Go protocol.Exchange 一致)
MARKET_MAP = {"sh": 1, "sz": 0, "bj": 2}

# 通达信行情服务器(7709)。顺序尝试, 取第一个能连上的。
# 前几个为常见公共主站(含本次实测可达的服务器), 后续可自行增删。
DEFAULT_HOSTS = [
    "119.147.212.81",   # 深圳
    "115.238.56.198",   # 杭州
    "180.153.18.170",   # 上海
    "218.75.126.9",     # 浙江
    "60.12.136.250",    # 杭州
    "60.191.117.167",   # 杭州
    "jstdx.gtjas.com",  # 国泰君安
    "shtdx.gtjas.com",  # 国泰君安(上海)
    "sztdx.gtjas.com",  # 国泰君安(深圳)
]

DEFAULT_PORT = 7709
CONNECT_TIMEOUT = 3.0  # 单台服务器建连超时(秒)


def _auto_connect(api, port: int, connect_timeout: float):
    """顺序尝试 DEFAULT_HOSTS, 返回第一个能建立连接的服务器 IP(失败返回 None)。"""
    for ip in DEFAULT_HOSTS:
        try:
            if api.connect(ip, port, time_out=connect_timeout):
                return ip
        except Exception:
            continue
    return None


def market_from_code(code: str) -> int:
    """由带前缀的证券代码返回通达信市场编码: 'sh600519' -> 1, 'sz000001' -> 0, 'bj...' -> 2。"""
    prefix = code[:2].lower()
    if prefix not in MARKET_MAP:
        raise ValueError(f"无法识别的市场前缀: {code[:2]!r} (code={code!r})")
    return MARKET_MAP[prefix]


def number_from_code(code: str) -> str:
    """由带前缀的证券代码返回 6 位数字代码主体: 'sh600519' -> '600519'。"""
    return code[2:]


def fetch_xdxr_events(
    code: str,
    host: Optional[str] = None,
    port: int = DEFAULT_PORT,
    use_best_ip: bool = True,
    connect_timeout: float = CONNECT_TIMEOUT,
) -> List[XRXDEvent]:
    """从通达信行情服务器拉取指定股票的除权除息(category==1)事件。

    Args:
        code:           带交易所前缀的证券代码, 如 'sh600519' / 'sz000001' / 'sh510880'。
        host:           指定行情服务器 IP/域名。None 时自动尝试 DEFAULT_HOSTS。
        port:           行情服务器端口, 默认 7709。
        use_best_ip:    是否允许自动选服务器(host 为 None 时生效)。设为 False 且 host 为 None 会报错。
        connect_timeout:单台服务器建连超时(秒)。

    Returns:
        XRXDEvent 列表, 按除权日升序。无事件(如 ETF/指数)时返回空列表。

    Raises:
        ValueError:      代码前缀无法识别 / 未指定 host 且禁止自动选服务器。
        ConnectionError: 连接/拉取失败。
    """
    code = code.lower().strip()
    market = market_from_code(code)
    number = number_from_code(code)

    from pytdx.hq import TdxHq_API
    api = TdxHq_API()

    if host is not None:
        if not api.connect(host, port, time_out=connect_timeout):
            raise ConnectionError(f"无法连接通达信行情服务器: {host}:{port}")
        ip = host
    elif use_best_ip:
        ip = _auto_connect(api, port, connect_timeout)
        if ip is None:
            raise ConnectionError(
                f"无法连接任何通达信行情服务器(已尝试 {DEFAULT_HOSTS})"
            )
    else:
        raise ValueError("未指定 host 且 use_best_ip=False, 无法确定行情服务器")

    try:
        rows = api.get_xdxr_info(market, number)
    finally:
        api.disconnect()

    events: List[XRXDEvent] = []
    for r in rows or []:
        if r.get("category") != 1:
            continue
        events.append(
            XRXDEvent(
                date=dt.date(int(r["year"]), int(r["month"]), int(r["day"])),
                fenhong=float(r.get("fenhong") or 0.0),
                peigujia=float(r.get("peigujia") or 0.0),
                songzhuangu=float(r.get("songzhuangu") or 0.0),
                peigu=float(r.get("peigu") or 0.0),
            )
        )
    events.sort(key=lambda e: e.date)
    log.info("代码 %s 除权除息事件 %d 条 (来自 %s)", code, len(events), ip)
    return events
