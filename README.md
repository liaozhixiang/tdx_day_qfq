# tdx_day_qfq 通达信前复权工具包

通达信 **.day 日线文件一站式前复权 (QFQ)** 工具包。直接读取通达信 `.day` 文件，自动拉取除权除息数据，将不复权日 K 转为前复权日 K，结果对齐通达信桌面端。

复刻自 Go 库 [injoyai/tdx](https://github.com/injoyai/tdx) 的前复权算法（`model_gbbq.go` / `gbbq.go`），支持 A 股、ETF/LOF 等基金。

## 特性

- **仿射变换复权**（非纯比例缩放）：`price_adj = Mul * price_raw + Add`
- **对齐通达信桌面端**：结果四舍五入到分（逢五进一，非 Python 银行家舍入）
- **自动识别市场与价位**：股票/指数 2 位小数、基金 3 位小数
- **自动选择行情服务器**：内置公共主站列表，自动选最快可达服务器
- **处理停牌缺口**：缺口内多个除权事件自动复合
- **丢弃未来分红**：已公告但未除权的事件不会误复权
- OHLC 均复权，成交量/额不变

## 安装

```bash
pip install pandas numpy pytdx
```

## 快速上手

### 一键前复权

从 `.day` 文件直接得到前复权日 K：

```python
from tdx_day_qfq import qfq_day_file

df = qfq_day_file(r"D:\Tdx\vipdoc\sh\lday\sh510880.day")
# df: date/open/high/low/close/volume/amount（升序，已前复权）
```

### 低层 API

```python
import pandas as pd
from tdx_day_qfq import (
    parse_tdx_day_file,   # 解析 .day 不复权 K 线
    fetch_xdxr_events,    # 网络拉取除权除息事件
    apply_qfq,            # 应用前复权到 DataFrame
)

raw = parse_tdx_day_file("sh600519.day")
events = fetch_xdxr_events("sh600519")
df_qfq = apply_qfq(raw, events)
```

### 合成用例验证

不带参数运行示例脚本，可运行算法断言（无事件/送转/分红/配股/未来分红/停牌缺口/舍入）：

```bash
python -m tdx_day_qfq.example_qfq [day_file_path]
```

## 模块划分

| 模块 | 说明 |
| --- | --- |
| `adjust.py` | 复权算法核心：仿射因子、逢五进一舍入、应用复权 |
| `gbbq.py` | 除权除息数据获取（pytdx 网络拉取） |
| `parse_tdx_day_file.py` | 通达信 `.day` 文件解析器（独立可复用） |
| `one_stop.py` | 一站式入口：读 `.day` + 拉取事件 + 前复权 |
| `example_qfq.py` | 示例与合成用例断言 |

## 复权模型

前复权采用**仿射变换**，锚定最新交易日（A=1, B=0），自今向过去回溯，遇除权日复合：

```
A <- A / m ;  B <- B - A_new * c
```

单个除权事件仿射系数（10 股为单位）：

```
m = (10 + 送转股 + 配股) / 10
c = (分红 - 配股 * 配股价) / 10
```

## 依赖

- Python ≥ 3.8
- pandas / numpy
- pytdx（网络拉取除权除息）

## 致谢 / 参考

- [injoyai/tdx](https://github.com/injoyai/tdx) — 复权算法来源

## License

[MIT](LICENSE)
