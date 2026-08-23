#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
前复权(QFQ)仿射模型核心 —— 复刻 Go 库 injoyai/tdx 的复权算法。

算法来源:
    https://github.com/injoyai/tdx/blob/master/protocol/model_gbbq.go
    (XRXD.mc / XRXDs.Pre / PreKlines.Factors / ApplyQFQ / roundHalfUpYuan)
    https://github.com/injoyai/tdx/blob/master/gbbq.go (QFQ / GetFactors)

复权模型为【仿射变换】(不是纯比例缩放):
    price_adj = QFQMul * price_raw + QFQAdd
    - QFQ 前复权: 锚定最新交易日 A=1, B=0, 自今向过去回溯, 遇除权日复合
      A <- A / m ; B <- B - A_new * c
    - 单个除权事件仿射系数: m=(10+送转+配股)/10, c=(分红-配股*配股价)/10
      标准除权参考价 P_adj = (P - c) / m, 与 XRXD.Pre 等价。
    - 结果四舍五入到分(逢五进一), 对齐通达信桌面端。
    - 成交量/额不复权。

关键细节(与 Go 库一致, 避免踩坑):
    1. 丢弃 ex-date 严格晚于【最新交易日】的事件(已公告但尚未除权的分红)。
    2. 事件按【日期位置】施加, 不依赖 ex-day 是否命中交易日
       -> 停牌缺口内的多个事件自动复合 (m=m1*m2, B 项链式缩放)。
    3. ex-day == 交易日当天时, 该日及之后不施加(价格在除权日已自然反映)。
    4. 四舍五入用"逢五进一(远离零)"(对齐 Go math.Round),
       Python 内置 round() 是银行家舍入, 不可直接用。

本模块只实现前复权 QFQ; HFQ 公式已在注释中给出(锚定最早交易日), 需要时可扩展。
"""

import math
import datetime as dt
from dataclasses import dataclass
from typing import Iterable, List, Sequence, Union

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class XRXDEvent:
    """单个除权除息事件(gbbq category==1)。

    字段含义均以"10股"为单位(与通达信/Go 库一致):
        date:         除权除息日(ex-day)
        fenhong:      分红, 10股派 n 元
        peigujia:     配股价(元)
        songzhuangu:  送转股, 10股送/转 n 股
        peigu:        配股, 10股配 n 股
    """
    date: dt.date
    fenhong: float = 0.0
    peigujia: float = 0.0
    songzhuangu: float = 0.0
    peigu: float = 0.0


@dataclass(frozen=True)
class QFQFactor:
    """某交易日前复权仿射系数: price_adj = round_half_up(Mul*price_raw + Add)。"""
    date: dt.date
    qfq_mul: float   # A (乘法因子)
    qfq_add: float   # B (加法偏移, 单位: 元)


# ---------------------------------------------------------------------------
# 舍入工具
# ---------------------------------------------------------------------------

def round_half_away_from_zero(value: float, ndigits: int = 2) -> float:
    """四舍五入(逢五进一, 远离零), 对齐 Go math.Round。

    Python 内置 round() 是银行家舍入(round-half-to-even), 与通达信不一致。
    """
    if value == 0 or not math.isfinite(value):
        return float(value)
    scale = 10 ** ndigits
    return math.copysign(math.floor(abs(value) * scale + 0.5), value) / scale


def _round_away_cents(values: np.ndarray) -> np.ndarray:
    """向量化: 把"元"值四舍五入(逢五进一)到分。对齐 Go roundHalfUpYuan。"""
    return np.copysign(np.floor(np.abs(values) * 100.0 + 0.5), values) / 100.0


# ---------------------------------------------------------------------------
# 事件 -> 仿射系数
# ---------------------------------------------------------------------------

def event_mc(event: XRXDEvent):
    """单个除权除息事件的仿射系数: P_adj = (P - c) / m。

    与 Go XRXD.mc() 等价。字段先四舍五入到 2 位小数(对齐 Go XRXD() 构造),
    避免服务端浮点带来的微小偏差。
    """
    fenhong = round_half_away_from_zero(event.fenhong, 2)
    peigujia = round_half_away_from_zero(event.peigujia, 2)
    songzhuangu = round_half_away_from_zero(event.songzhuangu, 2)
    peigu = round_half_away_from_zero(event.peigu, 2)

    m = (10 + songzhuangu + peigu) / 10   # 乘法因子(送转/配股)
    c = (fenhong - peigu * peigujia) / 10  # 每股净现金流出(分红减配股注入)
    if m == 0:
        m = 1
    return m, c


# ---------------------------------------------------------------------------
# 计算每日前复权因子
# ---------------------------------------------------------------------------

def compute_factors(
    trade_dates: Union[Sequence, pd.Series, pd.DatetimeIndex],
    events: Iterable[XRXDEvent],
) -> List[QFQFactor]:
    """计算每个交易日的前复权仿射系数(锚定最新交易日 A=1, B=0)。

    Args:
        trade_dates: 交易日序列(升序; 可为 list/datetime/pandas DatetimeIndex)
        events:      除权除息事件列表(XRXDEvent)

    Returns:
        与 trade_dates 一一对应的 QFQFactor 列表(升序)。

    算法(Go PreKlines.Factors, QFQ 分支):
        自今向过去遍历每个交易日, 在记录该日系数前,
        把所有 ex-date 严格晚于该交易日且尚未施加的事件【依次复合】。
        停牌缺口内的多个事件因此自动合成 m=m1*m2、B 项链式缩放。
    """
    dates = [pd.Timestamp(d).date() for d in sorted(trade_dates)]
    if not dates:
        return []
    latest = dates[-1]

    # 丢弃未来除权事件(ex-date 严格晚于最新交易日, 已公告未生效)
    evs = []  # (ex_date, m, c), 按 ex-date 升序
    for ev in events:
        ex = pd.Timestamp(ev.date).date()
        if ex > latest:
            continue
        m, c = event_mc(ev)
        evs.append((ex, m, c))
    evs.sort(key=lambda t: t[0])

    # QFQ: 自今向过去
    factors = [None] * len(dates)
    a, b = 1.0, 0.0
    ei = len(evs) - 1
    for i in range(len(dates) - 1, -1, -1):
        while ei >= 0 and evs[ei][0] > dates[i]:  # ex-day 严格晚于当前交易日
            m, c = evs[ei][1], evs[ei][2]
            a = a / m
            b = b - a * c
            ei -= 1
        factors[i] = QFQFactor(date=dates[i], qfq_mul=a, qfq_add=b)

    return factors


# ---------------------------------------------------------------------------
# 应用前复权
# ---------------------------------------------------------------------------

def apply_qfq(df: pd.DataFrame, events: Iterable[XRXDEvent], inplace: bool = False) -> pd.DataFrame:
    """用前复权因子把不复权日K整段转为前复权日K。

    - OHLC 均复权(四舍五入到分, 对齐通达信桌面端), 成交量/额不变。
    - df 需包含 date 列(或为 DatetimeIndex)与 open/high/low/close 列。
    - 返回新 DataFrame(除非 inplace=True), 不改原 df 的 OHLC 以外内容。
    """
    out = df.copy() if not inplace else df

    if "date" in out.columns:
        dates = pd.to_datetime(out["date"]).dt.date.to_numpy()
    else:
        dates = pd.to_datetime(out.index).to_series().dt.date.to_numpy()

    factors = compute_factors(dates.tolist(), events)
    fm = {f.date: f for f in factors}

    muls = np.empty(len(dates), dtype=float)
    adds = np.empty(len(dates), dtype=float)
    for i, d in enumerate(dates):
        f = fm.get(d)
        muls[i] = f.qfq_mul if f is not None else 1.0
        adds[i] = f.qfq_add if f is not None else 0.0

    for col in ("open", "high", "low", "close"):
        raw = out[col].to_numpy(dtype=float)
        out[col] = _round_away_cents(muls * raw + adds)

    return out


def qfq(df: pd.DataFrame, events: Iterable[XRXDEvent], inplace: bool = False) -> pd.DataFrame:
    """apply_qfq 的别名, 便于语义化调用。"""
    return apply_qfq(df, events, inplace=inplace)
