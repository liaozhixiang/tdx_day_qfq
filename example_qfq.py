#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
示例 + 验证脚本。

1) 一站式前复权演示: 给一个 .day 文件路径, 打印除权除息事件、
   原始 vs 前复权对比(最近 N 根 + 每次除权日附近)。
2) 合成用例断言: 验证复权算法正确性(无事件/送转/分红/配股/
   未来分红/停牌缺口多事件/舍入)。

用法(需在项目根目录运行, 确保 utilis 可导入):
    python -m utilis.tdx.example_qfq [day_file_path]
    # 例:
    python -m utilis.tdx.example_qfq D:\\Tdx\\vipdoc\\sh\\lday\\sh510880.day

    # 不带参数: 只运行合成用例断言
    python -m utilis.tdx.example_qfq
"""

import datetime as dt
import sys

import pandas as pd

from .adjust import (
    QFQFactor,
    XRXDEvent,
    apply_qfq,
    compute_factors,
    event_mc,
    round_half_away_from_zero,
)
from .one_stop import qfq_day_file
from .parse_tdx_day_file import parse_tdx_day_file


# ---------------------------------------------------------------------------
# 合成用例断言
# ---------------------------------------------------------------------------

def _mk_df(closes, dates=None, open_off=0.0, high_off=0.2, low_off=0.1):
    """构造简单日K DataFrame(date/open/high/low/close/volume/amount)。"""
    if dates is None:
        dates = pd.bdate_range("2024-01-01", periods=len(closes))
    return pd.DataFrame(
        {
            "date": list(dates),
            "open": [c + open_off for c in closes],
            "high": [c + high_off for c in closes],
            "low": [c - low_off for c in closes],
            "close": list(closes),
            "volume": [100] * len(closes),
            "amount": [1000.0] * len(closes),
        }
    )


def _test_no_events():
    """无除权事件 -> 因子全 1, 数据不变(价格被"归一化"到分精度, 与 .day 一致)。"""
    df = _mk_df([10.0, 10.2, 10.4, 10.6])
    adj = apply_qfq(df, [])
    # 无事件时等价于把每个价格四舍五入到分(原始 .day 价格本就是 int/100, 恒等)
    for col in ("open", "high", "low", "close"):
        expected = df[col].map(lambda v: round_half_away_from_zero(v, 2))
        assert adj[col].equals(expected), (col, adj[col].tolist(), expected.tolist())
    # 成交量/额不变
    assert adj["volume"].equals(df["volume"]) and adj["amount"].equals(df["amount"])
    print("[PASS] 无事件: 数据不变(价格归一到分)")


def _test_10_to_10():
    """10送10 (songzhuangu=10) -> m=2, c=0: 除权日前收盘减半, 除权日及之后不变。"""
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"])
    df = _mk_df([10.0, 10.0, 10.0, 10.0], dates=dates)
    events = [XRXDEvent(date=dt.date(2024, 1, 4), songzhuangu=10)]
    adj = apply_qfq(df, events)
    assert adj["close"].tolist() == [5.0, 5.0, 10.0, 10.0], adj["close"].tolist()
    print("[PASS] 10送10: 除权前减半, 除权日及之后不变")


def _test_10_pai_5():
    """10派5 (fenhong=5) -> m=1, c=0.5: 除权日前收盘 -0.5。"""
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"])
    df = _mk_df([10.0, 10.0, 10.0, 10.0], dates=dates)
    events = [XRXDEvent(date=dt.date(2024, 1, 4), fenhong=5)]
    adj = apply_qfq(df, events)
    assert adj["close"].tolist() == [9.5, 9.5, 10.0, 10.0], adj["close"].tolist()
    print("[PASS] 10派5: 除权前 -0.5")


def _test_peigu():
    """10配3, 配股价5元 (peigu=3, peigujia=5) -> m=1.3, c=-1.5:
       除权前价 = (P+1.5)/1.3。"""
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"])
    closes = [11.0, 11.0, 11.0, 11.0]
    df = _mk_df(closes, dates=dates)
    events = [XRXDEvent(date=dt.date(2024, 1, 4), peigujia=5, peigu=3)]
    adj = apply_qfq(df, events)
    # 除权前: (11 + 1.5)/1.3 = 12.5/1.3 = 9.6153846... 四舍五入到分 = 9.62
    expected = round_half_away_from_zero((11.0 + 1.5) / 1.3, 2)
    assert adj["close"].iloc[0] == expected, (adj["close"].iloc[0], expected)
    assert adj["close"].iloc[2] == 11.0  # 除权日及之后不变
    print(f"[PASS] 配股: 除权前=(P+1.5)/1.3={expected}")


def _test_future_event():
    """ex-date 晚于最新交易日(已公告未生效) -> 忽略, 全部不变。"""
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"])
    df = _mk_df([10.0, 10.2, 10.4, 10.6], dates=dates)
    events = [XRXDEvent(date=dt.date(2024, 6, 1), fenhong=9)]  # 未来分红
    adj = apply_qfq(df, events)
    assert adj["close"].equals(df["close"])
    print("[PASS] 未来分红事件被忽略")


def _test_suspension_multi_event():
    """停牌缺口多事件(均未命中交易日) -> 自动复合。

    交易日: 01-02, 01-03, 01-10(01-04~01-09 停牌)。
    事件:   01-04 10送10(m=2), 01-06 10派4(m=1,c=0.4)。
    前复权锚定最新日(01-10): a=1,b=0。
    对 01-03 及之前: 先施加 01-06(m=1,c=0.4): a=1, b=-0.4;
                      再施加 01-04(m=2): a=0.5, b=-0.4。
    """
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-10"])
    df = _mk_df([10.0, 10.0, 10.0], dates=dates)
    events = [
        XRXDEvent(date=dt.date(2024, 1, 4), songzhuangu=10),
        XRXDEvent(date=dt.date(2024, 1, 6), fenhong=4),
    ]
    adj = apply_qfq(df, events)
    # 01-03: 0.5*10 - 0.4 = 4.6; 01-10: 10.0
    assert adj["close"].iloc[0] == 4.6, adj["close"].iloc[0]
    assert adj["close"].iloc[1] == 4.6, adj["close"].iloc[1]
    assert adj["close"].iloc[2] == 10.0, adj["close"].iloc[2]
    print("[PASS] 停牌缺口多事件复合: 01-03=4.6, 01-10=10.0")


def _test_rounding():
    """四舍五入为"逢五进一(远离零)", 而非银行家舍入。"""
    # 2.625 在二进制中精确, 便于断言
    assert round_half_away_from_zero(2.625, 2) == 2.63, round_half_away_from_zero(2.625, 2)
    assert round_half_away_from_zero(-2.625, 2) == -2.63
    assert round_half_away_from_zero(10.125, 2) == 10.13
    # 与 Python 内置 round 的差异示例(银行家舍入 -> 2.67, 我们需要 2.68 语义)
    print("[PASS] 四舍五入逢五进一(远离零)")


def _test_factor_mapping():
    """compute_factors 返回的因子与交易日一一对应, 且含 QFQFactor 字段。"""
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    events = [XRXDEvent(date=dt.date(2024, 1, 3), fenhong=2)]
    factors = compute_factors(dates, events)
    assert len(factors) == 3
    assert all(isinstance(f, QFQFactor) for f in factors)
    assert factors[-1].qfq_mul == 1.0 and factors[-1].qfq_add == 0.0  # 最新日锚定
    assert factors[0].qfq_add == -0.2  # 除权前日: 10派2 -> -0.2
    print("[PASS] compute_factors 因子映射正确")


def run_synthetic_tests():
    """运行全部合成用例断言。"""
    print("=" * 60)
    print("合成用例断言")
    print("=" * 60)
    _test_rounding()
    _test_no_events()
    _test_10_to_10()
    _test_10_pai_5()
    _test_peigu()
    _test_future_event()
    _test_suspension_multi_event()
    _test_factor_mapping()
    print("-" * 60)
    print("全部合成用例通过 ✔")
    print()


# ---------------------------------------------------------------------------
# 真实 .day 文件演示
# ---------------------------------------------------------------------------

def demo_day_file(day_file_path: str):
    """一站式演示: 读取 .day -> 拉取事件 -> 前复权, 打印对比。"""
    print("=" * 60)
    print(f"一站式前复权: {day_file_path}")
    print("=" * 60)

    # 一站式: 读 .day -> 拉取除权除息 -> 前复权
    adj, events = qfq_day_file(day_file_path, return_events=True)

    # 另读原始(不复权)K线用于对比
    raw = parse_tdx_day_file(day_file_path)

    print(
        f"\n共 {len(raw)} 根日K, 时间范围 {raw['date'].min():%Y-%m-%d} ~ "
        f"{raw['date'].max():%Y-%m-%d}"
    )

    # --- 除权除息事件 ---
    if events:
        print(f"\n除权除息事件 {len(events)} 条:")
        for ev in events:
            m, c = event_mc(ev)
            print(
                f"  {ev.date}  分红(10派) {ev.fenhong:<6.2f} 送转 {ev.songzhuangu:<6.2f} "
                f"配股 {ev.peigu:<5.2f} @ {ev.peigujia:<6.2f}元  =>  m={m:.4f} c={c:.4f}"
            )
    else:
        print("\n无除权除息事件(复权因子恒为 1, 数据不变)")

    # --- 每次除权日附近的原始 vs 前复权 ---
    if events:
        print("\n除权日附近对比 (原始收盘 -> 前复权收盘):")
        for ev in events:
            ex = pd.Timestamp(ev.date)
            before = raw[raw["date"] < ex]
            on = raw[raw["date"] >= ex]
            if before.empty or on.empty:
                continue
            b_idx, a_idx = before.index[-1], on.index[0]
            b, ba = raw.loc[b_idx], adj.loc[b_idx]
            a, aa = raw.loc[a_idx], adj.loc[a_idx]
            print(
                f"  ex-day {ev.date} | 前一日 {b['date']:%Y-%m-%d} 收 {b['close']:>9.2f} -> "
                f"{ba['close']:>9.2f} | 除权日 {a['date']:%Y-%m-%d} 收 {a['close']:>9.2f} -> "
                f"{aa['close']:>9.2f}"
            )

    # --- 最近 N 根对比 ---
    n = 10
    print(f"\n最近 {n} 根日K (原始 -> 前复权):")
    for i in range(len(raw) - n, len(raw)):
        r, a = raw.iloc[i], adj.iloc[i]
        print(f"  {r['date']:%Y-%m-%d}  原始 {r['close']:>9.2f}  ->  前复权 {a['close']:>9.2f}")

    print("\n请与通达信桌面端(前复权)逐分核对以上数值。")
    print()


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main(argv=None):
    # Windows 控制台/管道默认 GBK, 强制 UTF-8 以支持 ✔ 等字符
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    argv = argv if argv is not None else sys.argv[1:]

    run_synthetic_tests()

    if argv:
        day_file = argv[0]
        demo_day_file(day_file)
    else:
        print("用法: python -m utilis.tdx.example_qfq <day文件路径>")
        print("未提供 .day 文件, 仅运行了合成用例断言。\n")


if __name__ == "__main__":
    main()
