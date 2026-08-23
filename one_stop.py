#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一站式前复权日线: 直接读 .day 文件 -> 自动拉取除权除息 -> 计算前复权。

用法:
    from utilis.tdx.one_stop import qfq_day_file
    df_qfq = qfq_day_file(r"D:\\Tdx\\vipdoc\\sh\\lday\\sh510880.day")
    # df_qfq 为前复权后的 DataFrame: date/open/high/low/close/volume/amount(升序)

底层流程:
    1. parse_tdx_day_file()  解析 .day 原始(不复权)K线   [utilis/tdx/parse_tdx_day_file.py]
    2. fetch_xdxr_events()   网络拉取除权除息事件        [utilis/tdx/gbbq.py]
    3. apply_qfq()           计算仿射因子并复权 OHLC      [utilis/tdx/adjust.py]
"""

from pathlib import Path

import pandas as pd

from .adjust import apply_qfq
from .gbbq import DEFAULT_PORT, fetch_xdxr_events
from .parse_tdx_day_file import parse_tdx_day_file


def code_from_day_file(path) -> str:
    """从 .day 文件名推导证券代码。

    兼容两种命名:
        'sh510880.day'  -> 'sh510880'
        'SH.510880'     -> 'sh510880' (通达信导出点分名)
    """
    name = Path(path).stem.lower().replace(".", "")
    if len(name) < 8 or name[:2] not in ("sh", "sz", "bj") or not name[2:].isdigit():
        raise ValueError(
            f"无法从文件名推导证券代码: {path!r} (期望形如 sh510880.day / SH.510880)"
        )
    return name


def qfq_day_file(
    day_file_path,
    host: str = None,
    port: int = DEFAULT_PORT,
    use_best_ip: bool = True,
    return_events: bool = False,
):
    """一站式前复权: 读取 .day 文件 -> 拉取除权除息 -> 返回前复权后 DataFrame。

    Args:
        day_file_path: .day 文件路径(股票代码由文件名推导, 如 sh510880.day)。
        host:          指定通达信行情服务器 IP; None 自动选最快服务器。
        port:          行情服务器端口(默认 7709)。
        use_best_ip:   是否允许自动选服务器(host 为 None 时生效)。
        return_events: True 时额外返回除权除息事件列表。

    Returns:
        pd.DataFrame: 前复权后的日K, 列 date/open/high/low/close/volume/amount(升序)。
        若 return_events=True, 返回 (df, events) 元组。
    """
    raw = parse_tdx_day_file(str(day_file_path))
    if raw is None or raw.empty:
        raise ValueError(f"无法解析 .day 文件: {day_file_path}")

    code = code_from_day_file(day_file_path)
    events = fetch_xdxr_events(code, host=host, port=port, use_best_ip=use_best_ip)
    adj = apply_qfq(raw, events)

    if return_events:
        return adj, events
    return adj
