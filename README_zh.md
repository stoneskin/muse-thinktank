# muse-thinktank

> **One prompt, a council of models, zero hallucinations.**

![muse-thinktank AI 智囊团](docs/thinktank-promo.webp)

[English](README.md)

**为 Muse 用户打造。**多模型智囊团编排器（multi-agent debate / LLM ensemble / AI council）：一个问题并行发给 N 个模型（panel），双 judge 交叉验证，synth 综合出结论。纯 Python 标准库，零依赖。

**模型渠道：**目前仅支持 OpenRouter，未来会支持更多（见路线图）。

## 适合谁用？

- **Muse 用户**——行动前想多听几个"第二意见"
- **开发者**——合并前想让多个模型评审 PR 代码
- **分析师**——需要注入实时数据、交叉验证的答案
- 任何被单个模型的"自信幻觉"坑过的人

```
你的问题 → [panel: N 个模型并行] → [judge ×2 交叉验证] → [synth 综合] → 结论
```

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/)
[![Zero dependencies](https://img.shields.io/badge/dependencies-zero-green.svg)]()
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

> **新手？**先看[用户使用说明](docs/USER-GUIDE_zh.md)——15 分钟跑起第一个智囊团。
> （New here? Start with the [User Guide](docs/USER-GUIDE.md).）

## 5 分钟快跑

### Muse 聊天窗口安装

复制下面这段到 Muse 聊天窗口：

```
请帮我安装这个开源项目：https://github.com/stoneskin/muse-thinktank
按它仓库里 AI_SETUP.md 的步骤操作。
需要 API key 的地方停下来，先告诉我去 https://openrouter.ai/keys 免费申请一个。
```

### 终端安装

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

入口就一个：`thinktank.py` + `tt/` 包（纯标准库，`urllib` + `json` + `argparse`）。

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

# 红队模式（v0.5）：critics 攻击初稿，adjudicator 按严重性分级
python3 thinktank.py ask --red-team \
  --models <...> --judge-model <...> \
  --critic-models <...> \  # 可选，默认用 panel 同批模型
  "这个架构合理吗？"
# 输出：RED TEAM REPORT，含 verdict（revise/accept）与分级 findings
#（critical/major/minor；nitpick 已过滤）
```

看 `examples/stock-analysis/` 了解"先备数据再跑 panel"的完整模式。

## 示例

- **[股票分析](examples/stock-analysis/)**——用 `--context-data` 注入实时行情数据；panel 基于新鲜数字推理，而不是陈旧的训练记忆。
- **[代码评审](examples/code-review/)**——`--pr-diff` 指向公开 GitHub PR，自动拉 diff，多模型 panel 评审真实代码。（本仓库的 PR #1 就是这么评审的。）

## 理念

[人与 AI 的关系](docs/human-ai-relationship_zh.md)——为什么做这个工具：AI 放大人的能力，但方向和品味永远是人的。([English](docs/human-ai-relationship.md))

## 贡献 & 路线图

- 提 Issue / PR 欢迎，`good first issue` 标签见 Issues 页
- PR 请附 `--estimate` 输出（证明没烧掉预算）
- 路线图：流式输出 → Web UI → 基准测试套件 → 多轮辩论收敛 → **多渠道支持**（OpenRouter 之外）

## 设计文档

见 [docs/design.md](docs/design.md)（工作模式、Judge 三项权力、评审框架）与
[docs/model-profiles.md](docs/model-profiles.md)（模型能力档案）。

## 状态

v0.5（2026-10-12）：红队模式（`--red-team`）——critics 攻击初稿，adjudicator 按严重性分级。
v0.4（2026-10-12）：修复 4 个代码评审 blocker——prompt 注入防护（`sanitize_context`）、judge/panel 全局超时、运行时费用熔断器、拆成 `tt/` 包。

## License

Apache-2.0
