# muse-thinktank

> **One prompt, a council of models, zero hallucinations.**

[English](README.md)

**为 Muse 用户打造。**多模型智囊团编排器：一个问题并行发给 N 个模型（panel），双 judge 交叉验证，synth 综合出结论。纯 Python 标准库，零依赖。

**模型渠道：**目前仅支持 OpenRouter，未来会支持更多（见路线图）。

```
你的问题 → [panel: N 个模型并行] → [judge ×2 交叉验证] → [synth 综合] → 结论
```

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/)
[![Zero dependencies](https://img.shields.io/badge/dependencies-zero-green.svg)]()
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

> **新手？**先看[用户使用说明](docs/USER-GUIDE_zh.md)——15 分钟跑起第一个智囊团。
> （New here? Start with the [User Guide](docs/USER-GUIDE.md).）

## 5 分钟快跑

```bash
export OPENROUTER_API_KEY=<redacted>   # https://openrouter.ai/keys 免费获取
python3 thinktank.py ask \
  --models nvidia/nemotron-3-ultra-550b-a55b:free,nvidia/nemotron-3-super-120b-a12b:free \
  --judge-model nvidia/nemotron-3-ultra-550b-a55b:free \
  "分析特斯拉未来3个月的风险"
```

终端直接出结论（stdout），每步进展走 stderr。先跑 `--estimate` 看费用预估：

```bash
python3 thinktank.py ask --estimate --models <...> "你的问题"
# 输出：调用次数、token 上限、费用上限、预计耗时
```

## 架构

```mermaid
flowchart LR
    Q[问题] --> E[--estimate 费用预估]
    E --> H[health-check 存活检测]
    H --> P[panel: N 模型并行]
    P --> J1[judge-A 打分]
    P --> J2[judge-B 打分]
    J1 --> C{一致?}
    J2 --> C
    C -->|一致| S[synth 综合]
    C -->|分歧| HU[人终审]
    S --> O[结论]
```

核心文件就一个：`thinktank.py`（纯标准库，`urllib` + `json` + `argparse`）。

**AI 助手**：看 [AI_SETUP.md](AI_SETUP.md) 获取机器可读的安装与操作指令。

## 核心特性

| 特性 | 解决什么痛点 | 效果 |
|---|---|---|
| **双 judge 交叉验证** | 单 judge 自己幻觉没人发现 | winner 不一致自动转人终审 |
| **实时数据注入** (`--context-data`) | 模型训练数据过时（如 2024 年知识答 2026 年股票） | 调度器先搜实时数据注入，模型用真数字分析 |
| **动态成员选择** | 免费模型时好时坏 | 按历史成功率 × 延迟自动过滤 |
| **Fail-open / Fail-closed** | 某模型挂了整轮报废 | panel 降级继续；judge 全挂转人工 |
| **分歧熵追踪** | 不知道模型们分歧有多大 | 每轮计算 entropy，为多轮辩论铺路 |

## 进阶用法

```bash
# 实时数据注入（时效性敏感问题必备）
python3 thinktank.py ask --context-data data.json \
  --models <...> "分析 MSFT 当前估值"
# data.json: {"preamble": "...", "as_of": "...", "facts": {"现价": "..."}}

# 双 judge（默认单 judge）
python3 thinktank.py ask --judge-model <A> --judge-model2 <B> "..."

# 只看 judge 结论，省一次 synth
python3 thinktank.py ask --verdict "..."

# 并列展示所有答案，人终审
python3 thinktank.py ask --show-all "..."

# 动态成员选择（跨轮次记住模型表现）
python3 thinktank.py ask --member-state ./members.json --capability-scores ./scores.json "..."
```

看 `examples/stock-analysis/` 了解"先备数据再跑 panel"的完整模式。

## 贡献 & 路线图

- 提 Issue / PR 欢迎，`good first issue` 标签见 Issues 页
- PR 请附 `--estimate` 输出（证明没烧掉预算）
- 路线图：流式输出 → Web UI → 基准测试套件 → 多轮辩论收敛 → **多渠道支持**（OpenRouter 之外）

## 设计文档

见 [docs/design.md](docs/design.md)（工作模式、Judge 三项权力、评审框架）与
[docs/model-profiles.md](docs/model-profiles.md)（模型能力档案）。

## 状态

v0.4（2026-10-12）：修复 4 个代码评审 blocker——prompt 注入防护（`sanitize_context`）、judge/panel 全局超时、运行时费用熔断器、拆成 `tt/` 包。red-team 对抗轮（M2）待做。

## License

Apache-2.0
