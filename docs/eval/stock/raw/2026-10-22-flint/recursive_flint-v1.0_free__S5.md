# recursive/flint-v1.0:free · 多因子组合优化（v3.1：答案修正）

- 日期：2026-10-22
- tokens：6153
- 费用：$0.000000
- 尝试次数：1
- 状态：ok

---

下面是可以直接运行的 Python 脚本。它读取 `./s5_stocks.csv`，用相关性 `0.3` 构造协方差矩阵，并分别求：

1. 不做空：`w_i >= 0`, `sum(w) = 1` 的最大夏普组合；
2. 允许做空：`w_i >= -0.2` 的最大夏普组合。

```python
import pandas as pd
import numpy as np
from scipy.optimize import minimize

DATA_PATH = "./s5_stocks.csv"
RISK_FREE = 0.02
CORR = 0.3

df = pd.read_csv(DATA_PATH)
mu = df["exp_return"].to_numpy(dtype=float)
vol = df["volatility"].to_numpy(dtype=float)
n = len(df)

# 相关矩阵 * 波动率外积，然后修正对角线为 vol^2
Sigma = CORR * np.outer(vol, vol)
np.fill_diagonal(Sigma, vol ** 2)

def calc_stats(w):
    ret = float(np.dot(w, mu) - RISK_FREE)
    var = float(np.dot(w, Sigma @ w))
    sd = np.sqrt(max(var, 0.0))
    sharpe = ret / sd if sd > 0 else -np.inf
    return ret, sd, sharpe

def optimize_max_sharpe(bounds):
    cons = (
        {"type": "eq", "fun": lambda w: np.sum(w) - 1.0},
    )
    res = minimize(
        fun=lambda w: -((np.dot(w, mu) - RISK_FREE) / np.sqrt(np.dot(w, Sigma @ w))),
        x0=np.ones(n) / n,
        bounds=bounds,
        constraints=cons,
        method="SLSQP",
        options={"maxiter": 2000, " ftol": 1e-12},
    )
    w = res.x
    ret, sd, sharpe = calc_stats(w)
    return w, ret, sd, sharpe, res

# 1) 不允许做空：权重 >= 0
w_ns, ret_ns, sd_ns, sharpe_ns, res_ns = optimize_max_sharpe([(0.0, 1.0)] * n)

# 2) 允许做空，最低权重 -0.2
lower_short = -0.2
upper_short = 1.0 + 0.2 * (n - 1)  # 因为 sum(w)=1，且每个 w_i >= -0.2
w_sh, ret_sh, sd_sh, sharpe_sh, res_sh = optimize_max_sharpe([(lower_short, upper_short)] * n)

def report(title, w, ret, sd, sharpe):
    print(title)
    for ticker, weight in zip(df["ticker"].astype(str), w):
        print(f"{ticker},{weight:.6f}")
    print(f"组合预期收益: {ret:.6f}")
    print(f"组合波动率: {sd:.6f}")
    print(f"夏普比率: {sharpe:.6f}")
    print()

report("最优权重（不允许做空）", w_ns, ret_ns, sd_ns, sharpe_ns)
report("最优权重（允许做空，最低 -0.2）", w_sh, ret_sh, sd_sh, sharpe_sh)

print("优化状态（不允许做空）:", res_ns.message)
print("优化状态（允许做空）:", res_sh.message)
```

运行前需要安装：

```bash
pip install pandas numpy scipy
```

运行：

```bash
python your_script_name.py
```

输出里会有两组最优权重：

- 一组是 `w_i >= 0`，权重和为 1；
- 一组是 `w_i >= -0.2`，也就是允许最多 20% 的做空。

组合预期收益、组合波动率、夏普比率都会按：

\[
Sharpe = \frac{w^T \mu - r_f}{\sqrt{w^T \Sigma w}}
\]

输出。

关于做空是否会提高夏普：

- 不做空时，可行域是 `w >= 0`；
- 允许 20% 以内做空时，可行域变成 `w >= -0.2`；
- 可行域变大后，最大夏普比率理论上不会变小；
- 如果优化时出现更优的做空结构，比如通过做空低预期收益或高相关性的股票来降低组合波动，同时保留高预期收益部分，那么夏普比率会上升；
- 如果实际脚本输出的做空版夏普比率比不做空版高，说明限制 -0.2 为止仍能找到更优风险调整收益；
- 如果实际输出几乎持平，说明最优组合本身不需要超过 -0.2 的做空，或者做空收益不足以改善风险调整后收益。

最终数值一定要以你运行脚本后打印出来的实际数字为准。因为完整数据在 `./s5_stocks.csv`，我这里没有直接读取你当前这份文件，所以不能替你编一组数值。脚本跑完后把输出发来，我可以直接帮你解释为什么做空版夏普变了。