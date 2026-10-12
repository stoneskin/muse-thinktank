# 模型能力档案（living doc）

从真实调用更新；"未实测" = 只有目录信息，不采信。种子日期：2026-10-11。

## 免费模型

| 模型 | 股票/15 | 代码/15 | 量化/20¹ | 备注 |
|---|---|---|---|---|
| nvidia/nemotron-3-ultra-550b-a55b:free | 15 | 13.75 | 15.0 | 评审质量极高，中文结构化强；股票三层止损/GTC挂单清单/三笔减仓教科书级；代码 P2 有 timeout 事实性误报 −0.5，P3 给 Yjs 落地清单；**v3.1 量化 15.0：S6/S7 有编造，呈现层不可信** |
| nvidia/nemotron-3-super-120b-a12b:free | 14 | 13.5 | 9.5 | 中文回答结构好；长 prompt 偶发空返回；股票 ATR 止损专业（S2 缺明确止损价扣 1）；代码 P2 只找到 2/4；**v3.1 S6 空返回×8 熔断** |
| cohere/north-mini-code:free | 7 | 14.25 | 14.5 | 代码专长，demo A3 质量最高；**股票 S3 直接拒答（合规过滤）——不进股票阵容**；长 prompt 偶发空返回；health ping 必须 ≥50 tokens；v3.1 量化 14.5 |
| dots-studio/dots-3-note-preview:free | 14 | 14.25 | 15.5 | 话痨，800 token 被截断；P2 找到 CACHE 无过期（全场仅 3 家）——免费阵容里代码最稳；股票有"卖出一半=零风险"心理会计小瑕疵；**v3.1 免费档量化最高 15.5** |
| poolside/laguna-xs-2.1:free | 10 | 10 | 5.0 | S2/P2 撞 429；能跑通时是好的免费代码备选，作轮换；v3 S4 后连续 429 出局 |
| nvidia/nemotron-3.5-lightning:free | 3 | — | 只输出思考过程、2000 token 写不完结论；不适合要干净结论的任务 |
| nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free | — | — | 推理模型；judge 任务时吐英文思考过程、指令跟随弱 |
| google/gemma-4-31b-it:free | — | — | 共享池 429 限流两次，可靠性存疑 |
| google/gemma-4-26b-a4b-it:free | — | — | 429 限流（同系列 31b 一样），可靠性差 |
| apodex/apodex-1.1-mini:free | — | — | 9 连空返回，判死刑 |
| thinkingmachines/inkling:free | — | — | 403，仅限 agentic harness——panel 阵容除名 |
| thinkingmachines/inkling-small:free | — | — | 403：仅限 agentic harness，纯 API 调不了——除名 |
| inclusionai/ling-3.1-flash | — | — | 长中文 prompt 空返回，可靠性存疑 |
| liquid/lfm-2.5-2.6b:free | — | — | 长中文 prompt 空返回；2.6B 小模型 |
| poolside/laguna-s-2.1:free | — | — | 429 限流，质量未知 |
| openrouter/free | — | — | 官方自动路由，未实测；可当"随便问"兜底 |
| nvidia/nemotron-3.5-content-safety:free | — | — | 安全分类器，非通用模型，不用 |
| google/lyria-3-clip-preview / pro-preview | — | — | 音乐模型，不用 |

## 付费模型（2026-10-11，两批评测）

| 模型 | 价格/1M（in/out） | 股票/15 | 代码/15 | 量化/20¹ | 备注 |
|---|---|---|---|---|---|
| deepseek/deepseek-v3.2 | $0.26 / $0.80 | 15 | 10 | 16.5 | 股票性价比之王；**严重偏科：代码 P2 两个臆想误报**——代码任务别用（v4-pro 已治好偏科，见下）；v3.1 量化 16.5 |
| google/gemini-3-flash-preview | $0.50 / $3.00 | 15 | 13.25 | 17.0 | 股票备选首选；代码 P2 除 sonnet 外唯一找到可变默认参数；v3/v3.1 量化都是 17.0，稳定 |
| openai/gpt-5-mini | $0.25 / $2.00 | 15 | 13.75 | 18.0 | 话多，评测要给 4000+ tokens；代码 P2 零误报；**v3.1 量化 18.0，全场最诚实之一（不编造）** |
| anthropic/claude-sonnet-5.5 | $2 / $10 | 15 | **15** | **20.0** | **代码全场唯一满分**——代码/设计任务默认首选；评测要 ≥5000 tokens（P3 类 8000）；**v3.1 量化满分 20.0，双维度第一，judge 首选** |
| anthropic/claude-opus-4.6 | $5 / $25 | 15 | 14.25 | 17.5 | P2 全场独有 resp.json 解析问题；P1 仅 1184 tokens 最省；v3.1 量化 17.5 |
| openai/gpt-5 | $1.25 / $10 | 14 | 14.25 | — | 股票 S1 不给 committed 价位；代码 P3 逆大流选 Git 且论证充分；评测要 ≥8000 tokens |

## 第三批（2026-10-11）：中美大厂主流模型

| 模型 | 价格/1M（in/out） | 股票/15 | 代码/15 | 量化/20¹ | 备注 |
|---|---|---|---|---|---|
| x-ai/grok-4.7 | $2 / $6 | 15 | 13.75 | — | xAI 首次参测；"止损不分批等于把纪律做成拖延"；P3 选 Git 路线论证密。股票主力候选 |
| meta-llama/llama-4-maverick | $0.19 / $0.65 | 15 | 13.25 | 16.5 | 开源模型里最便宜的满分股票选手，性价比之王；v3.1 量化 16.5 |
| deepseek/deepseek-v4-pro | $0.21 / $0.42 | 15 | **15** | 9.0 | P2 四个全中，P3 无跑题——v3.2 的偏科治好了；中国公司代码最强，便宜；**v3.1 量化仅 9.0，S5 脚本语法错误** |
| moonshotai/kimi-k3 | $0.8 / $15 | 15 | 13.75 | — | P3 风险分析全场最深（seq 空洞、GC 水位线）；输出贵，质量对得起价格 |
| minimax/minimax-m3 | $0.3 / $1.2 | 15 | 14.5 | 18.0 | P2 四个全中；便宜，股票可用，代码超预期；**v3.1 量化 18.0，v3 有编造前科、v3.1 已改** |
| google/gemini-3.1-pro-preview | $2 / $12 | 15 | 13.75 | P1/P2 在 5000 token 下被截断，8000 才完整；pro 档比 flash 强一档 |
| openai/gpt-5.4 | $2.5 / $15 | 15 | 13.75 | 比 gpt-5 新，但没拉开差距 |
| anthropic/claude-fable-5.1 | $10 / $50 | 15 | 13.75 | P2 主动论证"可变默认参数不算 bug"（有主见）；P3 权衡表全场最密。贵但强 |
| stepfun/step-5-preview | $1 / $2.7 | 15 | 8.75 | P1 三次空返回按规矩停；P2 3.75，P3 5/5 |
| z-ai/glm-5.3-prime | $2.8 / $8.8 | 15 | 11.5 | 重度 reasoning，8000 token 才出完整答案；P2 5 分，P3 截断；触发单模型 $0.50 熔断 |
| qwen/qwen3.8-max-prime | $4 / $12 | 14 | 8.25 | 重度 reasoning，单题 $0.12；P1 四次全空不再追。token 太贵不实用 |

¹ 量化列以 v3.1 为主（2026-10-13），无 v3.1 分数时用 v3（2026-10-11）补充。

## 建档规则

- 新模型进免费池，先过 probe（chat + tool-call 各一次）再建档，**不凭名字猜能力**。
- "未实测"的不进重要任务阵容；可靠性差的（频繁 429/空返回）降级为杂活或除名。
- 这套档案 = opencode-fuse §7.12 能力分的人工版，两边互通。
