# recursive/flint-v1.0:free · 隐含波动率曲面插值（v3.1：非报价点）

- 日期：2026-10-22
- tokens：5813
- 费用：$0.000000
- 尝试次数：1
- 状态：ok

---

```python
import pandas as pd
import numpy as np
from scipy.interpolate import CubicSpline

TARGET_STRIKE = 102.0

df = pd.read_csv("./s4_iv.csv")

splines = {}
for expiry_days, g in df.groupby("expiry_days", sort=True):
    g = g.dropna(subset=["strike", "iv"]).sort_values("strike")
    x = g["strike"].to_numpy(dtype=float)
    y = g["iv"].to_numpy(dtype=float)
    splines[float(expiry_days)] = CubicSpline(x, y)

iv_30 = float(splines[30.0](TARGET_STRIKE))
iv_90 = float(splines[90.0](TARGET_STRIKE))

slope = (iv_90 - iv_30) / (90.0 - 30.0) * 252.0

print(f"30 天 strike={TARGET_STRIKE} 处隐波: {iv_30:.6f}")
print(f"90 天 strike={TARGET_STRIKE} 处隐波: {iv_90:.6f}")
print(f"期限结构斜率: {slope:.8f}")
```

如果环境没有 `scipy`，可用 `scipy.interpolate.PchipInterpolator` 或自行实现分段三次 Hermite 插值；这里优先使用 `CubicSpline`。

### 为什么用插值而不是直接取最近报价点？

因为 IV 数据是 **离散** 的，只有在已报 strike 上的点；交易和策略常常需要定价到 **任意行权价**，比如 `102`；Black-Scholes 需要的是连续的 IV **平滑** 曲线；用三次样条构造 **连续曲面** 最合理。直接 nearest 只能给粗糙值，插值才能得到更合理 IV。