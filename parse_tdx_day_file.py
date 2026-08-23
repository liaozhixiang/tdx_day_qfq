#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通达信 .day 日线解析器(独立模块, 可随 tdx 包发布到 GitHub)。

读取通达信 .day 文件并解析为 pandas DataFrame。.day 每条记录固定 32 字节,
按小端字节序解包: 日期(uint32, YYYYMMDD)、开/高/低/收(int, 缩放整数)、
成交额(float)、成交量(int)、保留字段(int)。

价格小数位(通达信按品种区分):
    - 股票 / 指数: 2 位小数, 原始整数 / 100
    - 基金(ETF/LOF/封闭式/分级等): 3 位小数, 原始整数 / 1000
  默认按证券代码自动识别, 也可用 price_scale 参数强制指定。

依赖: pandas(仅标准库之外依赖)。
"""

import os
import re
import struct
from datetime import datetime

import pandas as pd

# 基金代码段(通达信 3 位小数价格): 沪 50/51/52/53/56/58, 深 15/16
SH_FUND_PREFIXES = ("50", "51", "52", "53", "56", "58")
SZ_FUND_PREFIXES = ("15", "16")


def is_fund_code(code: str) -> bool:
    """6 位证券代码是否为基金(ETF/LOF/封闭式/分级等)。

    通达信规则: 沪市基金以 50/51/52/53/56/58 开头, 深市基金以 15/16 开头。
    基金在 .day 文件中价格保留 3 位小数。
    """
    if len(code) != 6 or not code.isdigit():
        return False
    return code[:2] in SH_FUND_PREFIXES or code[:2] in SZ_FUND_PREFIXES


def _extract_code(file_path) -> str:
    """从 .day 文件名推导证券代码(小写、去点), 如 'sh510880.day' -> 'sh510880'。"""
    name = os.path.basename(str(file_path)).lower().replace(".day", "").replace(".", "")
    return name


def _code_digits(file_path):
    """提取文件名中的 6 位数字代码, 用于基金识别; 无法识别返回 None。"""
    m = re.search(r"(?:sh|sz|bj)?(\d{6})$", _extract_code(file_path))
    return m.group(1) if m else None


def parse_tdx_day_file(file_path, price_scale=None, verbose=True):
    """解析单个通达信 .day 文件。

    Args:
        file_path:     .day 文件路径。
        price_scale:   价格缩放系数: 100(2 位小数, 股票/指数) 或 1000(3 位小数, 基金)。
                       None 时按证券代码自动识别(基金 /1000, 其余 /100)。
        verbose:       是否打印解析进度信息。

    Returns:
        pandas.DataFrame or None: 列 date/stock_code/open/high/low/close/volume/amount,
        按日期升序; 文件不存在或解析失败返回 None。
    """
    if not os.path.exists(file_path):
        if verbose:
            print(f"错误: 文件不存在 -> {file_path}")
        return None

    stock_code = _extract_code(file_path)

    if price_scale is None:
        digits = _code_digits(file_path)
        price_scale = 1000 if (digits and is_fund_code(digits)) else 100

    if verbose:
        print(f"--- 开始解析股票: {stock_code} (价格缩放 /{price_scale}) ---")

    record_size = 32
    data_list = []

    try:
        with open(file_path, "rb") as f:
            while True:
                buffer = f.read(record_size)
                if len(buffer) < record_size:
                    break
                try:
                    # 格式: <I日期 I开 I高 I低 I收 f成交额 I成交量 I保留
                    unpacked_data = struct.unpack("<IIIIIfII", buffer)
                    date_int = unpacked_data[0]

                    try:
                        date_str = datetime.strptime(str(date_int), "%Y%m%d").strftime(
                            "%Y-%m-%d"
                        )
                    except ValueError:
                        if verbose:
                            print(f"警告: 发现无效日期格式 {date_int}, 跳过该条记录。")
                        continue

                    open_price = unpacked_data[1] / price_scale
                    high_price = unpacked_data[2] / price_scale
                    low_price = unpacked_data[3] / price_scale
                    close_price = unpacked_data[4] / price_scale
                    amount = unpacked_data[5]
                    volume = unpacked_data[6]

                    data_list.append(
                        {
                            "date": date_str,
                            "stock_code": stock_code,
                            "open": open_price,
                            "high": high_price,
                            "low": low_price,
                            "close": close_price,
                            "volume": volume,
                            "amount": amount,
                        }
                    )
                except struct.error:
                    if verbose:
                        print("警告: 数据记录解析错误, 可能文件已损坏或到达末尾。")
                    continue
    except Exception as e:
        if verbose:
            print(f"读取文件时发生严重错误: {e}")
        return None

    if not data_list:
        if verbose:
            print("未解析到任何有效数据。")
        return None

    df = pd.DataFrame(data_list)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(by="date", ascending=True).reset_index(drop=True)

    if verbose:
        print(f"成功解析 {len(df)} 条记录")
        if not df.empty:
            print(
                f"数据时间范围: {df['date'].min().strftime('%Y-%m-%d')} 到 "
                f"{df['date'].max().strftime('%Y-%m-%d')}"
            )

    return df


if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else r"D:\Tdx\vipdoc\sh\lday\sh510880.day"
    stock_df = parse_tdx_day_file(path)
    if stock_df is not None:
        print("\n--- 数据预览 (前5行) ---")
        print(stock_df.head())
        print("\n--- 数据预览 (后5行) ---")
        print(stock_df.tail())
