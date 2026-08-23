#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通达信 .day 一站式前复权(QFQ)工具包。

快速上手:
    from tdx_day_qfq import qfq_day_file
    df = qfq_day_file(r"D:\\Tdx\\vipdoc\\sh\\lday\\sh510880.day")

模块划分:
    adjust.py   复权算法核心(仿射因子 / 四舍五入 / 应用)
    gbbq.py     除权除息数据获取(pytdx 网络拉取)
    one_stop.py 一站式入口(读 .day + 拉取事件 + 前复权)
"""

from .adjust import (
    QFQFactor,
    XRXDEvent,
    apply_qfq,
    compute_factors,
    event_mc,
    qfq,
    round_half_away_from_zero,
)
from .gbbq import (
    CONNECT_TIMEOUT,
    DEFAULT_HOSTS,
    DEFAULT_PORT,
    MARKET_MAP,
    fetch_xdxr_events,
    market_from_code,
)
from .one_stop import code_from_day_file, qfq_day_file
from .parse_tdx_day_file import is_fund_code, parse_tdx_day_file

__version__ = "0.1.0"

__all__ = [
    # 数据结构
    "XRXDEvent",
    "QFQFactor",
    # 算法
    "round_half_away_from_zero",
    "event_mc",
    "compute_factors",
    "apply_qfq",
    "qfq",
    # 数据获取
    "fetch_xdxr_events",
    "market_from_code",
    "MARKET_MAP",
    "DEFAULT_HOSTS",
    "DEFAULT_PORT",
    "CONNECT_TIMEOUT",
    # .day 解析
    "parse_tdx_day_file",
    "is_fund_code",
    # 一站式
    "qfq_day_file",
    "code_from_day_file",
]
