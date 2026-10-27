# AI 智囊团调度台（muse-thinktank）— 设计文档 v0.1

- 状态：**开工**（2026-10-11；前身是同日凌晨的 IDEA 记录）
- 一句话：不做手机 App，做一个**Muse能用的软件**——Stone 在聊天里提问，Muse用他的 OpenRouter key 并行问 N 个模型（可多轮辩论），judge + synth 后把结论交回来。Muse帮他管理、总结这些 AI 智囊团。

## 1. 背景：为什么做、为什么可行

1. **客户端已经存在**：就是现在跟Muse聊天的界面（App / WhatsApp）。手机 App 最难的 UI、推送、上架全都不需要——手机上直接就能测。
2. **调度者已经存在**：Muse有 subagent 并行、shell、定时任务。fan-out / fan-in 是现成的能力。
3. **缺的只是薄薄一层**：`thinktank.py`（fan-out → 可选对抗轮 → judge → synth → 成本小结）+ skill（触发词、路由规则、预算）+ OpenRouter key（已配好，走 Secure Vault，不进 git、不打印）。

## 2. 工作模式

### 2.1 两档模式（Stone 2026-10-11 提议，待拍板）

- **标准模式（正常）**：并行 + judge（+synth），单轮。默认模式，免费模型。
- **深度模式（高级）**：red-team 对抗评审。实现为"标准模式 + 对抗轮"——拿标准模式的 winner 当初稿，派异构 critics 挑刺（逻辑/合规、成本/数学、策略分工），judge 终审（带严重性分级）。不是两套 pipeline，是一套 pipeline 的可选第二轮。

### 2.2 触发规则（Stone 2026-10-11 补充）

- Stone 说"上智囊团/议一议"就用 think-tank 模式。
- Muse觉得某问题值得多模型会诊时，**主动问一句**再跑——不擅自跑（一次几分钟 + 注意力成本）。

### 2.3 Judge 的三项权力（Stone 2026-10-11 补充）

1. **拒绝权**：judge 可以直接拒掉坏答案（空答、答非所问、幻觉），被拒的不进 synth；全拒则 fail-closed 报"无可用答案"，不硬合成垃圾。
2. **噪音过滤**：critics 的挑刺按严重性分级（critical/major/minor/nitpick），nitpick 在终审前过滤，只把真问题摆出来。
3. **人终审**：重要事项 judge 只做分析和噪音过滤，把干净候选 + 分歧点摆出来，**Stone 亲自裁**（对应 opencode-fuse §6.3 的 `--show-all` 用户选择模式）。

**v0.6（2026-10-13，Stone 批准）**：judge 容错两层——① 宽容层：枚举大小写不敏感、数字字符串转 int、confidence 缺失默认 medium（不碰语义）；② repair-retry：contract violation 后把具体报错喂回去让模型自修格式，最多 1 次，还不行就 escalate。fail-closed 还在，只是从"一次不过就判死"变成"给一次改错机会"。budget 按 2x judge 成本估算。

**v0.6.1（2026-10-13）**：judge 输入截断——panel 答案太长（9k+ tokens）时 judge 会丢"JSON only"指令（sonnet-5.5 和 minimax 双双零 JSON 输出）。喂给 judge 的每答案截断到 4000 字符。另：repair 加语义漂移检测（winner/verdict 被改则弃用）。panel 侧加软约束：PANEL_SYSTEM 要求 300-600 词（源头控制，judge 截断为兜底）。

**v0.7（2026-10-13）**：judge 黑名单——`tt/members.py` 跟踪 `judge_fail`（contract violation/空输出），连续 2 次失败进黑名单，下次指定时 WARNING 提示换 judge。成功则清零。minimax-m3 已三次掉链，触发黑名单。**v0.7.1**：黑名单 24 小时冷却自动解禁（熔断器模式）；backup 健康检查最多 3 轮，防止超长 backup 列表烧预算。

## 3. 运行规则

### 3.1 升级规则：免费 → 付费（Stone 2026-10-11 立）

- 免费模型结果不满意（空返回、低质量、分歧无解）→ Muse**主动提醒**并**跟他确认**是否上更好更可靠的付费模型，**绝不自动转付费**。
- 建议时带上预估费用和当前余额（2026-10-11：总额 $31，已用 $22.72，剩约 $8.3——余额不多，优先单次 premium 调用而非整 panel 付费）。
- 语义与 opencode-fuse 的 `/better` 升档一致：免费搞不定 → 问一句 → 花钱买更好的。

### 3.2 进展汇报（Stone 2026-10-11 立）

- **延迟可接受，静默不可接受**：每完成一步（panel 收齐 → judge → synth）或每过一段时间，给 Stone 反馈当前进展 + 预计剩余时间。
- **立即汇报**（不等步骤结束）：可能卡住、死循环风险、需要他介入（拍板、确认付费、judge 升级成人终审）——第一时间说。
- 落到实现：每步超时上限（如单成员 120s）、rebuttal 轮数上限（默认最多 2 轮，再多先问）、预算熔断；超时/全员失败/预算触顶都算"立即汇报"事件。

### 3.3 token 策略（Stone 2026-10-11 补充）

- 智囊团 panel 默认免费模型；免费池每天 08:00（美东）自动扫描保鲜（cron: `openrouter-free-models-daily-scan`），名单有实质变化才打扰。
- **Muse可用免费模型省 token**：机械性/草稿性工作（摘要、提取、格式化、初稿、批量分类）Muse可以用免费模型先干；涉及判断、决策、终审和直接给 Stone 的结论，仍由Muse自己来。免费模型的输出Muse负责验——省 token 不省质量责任。
- `:free` 后缀 fail-closed：缺失后缀视为失败，绝不静默走付费版（FreeToken-Bots 的教训）；池空就报空池。
- **token 下限（v0.18，2026-10-27）**：按模型族设 completion 下限，`--max-tokens` 只往上加不往下压——gpt-5 8000、gpt-5-mini 4000、claude 2500、gemini 8000；synth 另有 4000 下限。推理模型先烧 hidden reasoning 再出正文，统一下限 800 会饿死（2026-10-23 实测）。

## 4. 模型能力档案（Stone 2026-10-11 要求）

- 每个模型维护能力档案：擅长什么、能不能干活（可靠性：空返回率、429 频率、tools 支持）。
- 档案：`docs/model-profiles.md`（living doc），从真实 probe 和使用中更新；新模型进池先 probe（chat + tool-call 各一次）再建档，**不凭名字猜能力**；"未实测"的不进重要任务阵容。
- 这套 = opencode-fuse §7.12 能力分的人工版，两边互通。

## 5. 诚实的问题（风险）

1. **延迟是分钟级**：3 模型 + judge + synth，快不了。适合深问题，不适合随手问。
2. **成本按轮数放大**：每加一轮辩论，token 翻倍。预算熔断必须有。
3. **模型同质化**：都问同一类模型，盲点是重叠的。异构阵容 + 对抗角色（D10 Red Team）才有意义；否则不如单问一个最好的。
4. **免费模型不稳定**：429、空返回、无公告下架（如 space-bunny-alpha，2026-10-11 前已从 OpenRouter 下架）都是常态——免费池雷达和 fail-closed 是刚需，不是点缀。
5. **别过度建设**：80% 是Muse本来就能做的事，"软件"只是把多轮辩论和成本账做规整。先别写大系统。

## 6. 与现有项目的关系

- opencode-fuse = opencode 内嵌版 panel；这个 = Muse托管版。judge/synth 设计互通，dogfood。
- Gemini 调研的 Multi / Suprmind = "别人替你管智囊团"；这个思路 = "让Muse替你管"——少了 App 那层，多了一个知根知底的人。

## 7. 里程碑

- **M0** ✅（2026-10-11）：repo + 设计文档 v0.1 + 免费池扫描（cron 已设）。
- **M1**（进行中）：`thinktank.py` v0.1——panel → judge → synth，进展汇报、预算熔断、fail-closed；手机可测（Stone 直接在聊天里说"上智囊团"）。
- **M2**：red-team 对抗轮（标准模式 + 对抗轮，§2.1）。
- **M3**：能力档案自动化（probe → 建档 → 阵容推荐）。

## 8. 验证记录

- 2026-10-11：3 个免费模型（NVIDIA Nemotron-120B、Dots-3、Cohere North）panel + judge，问 D10（先做 M2 还是直接上 red-team），三家一致：先做 M2 独立并行+judge；Cohere 的独特见解：red-team 只值得用在安全关键/高价值代码。pipeline 跑通，成本 $0。

## 9. 模型评测计划（Stone 2026-10-11 布置，待排期）

- **目标**：把档案里"未实测"的模型全部实测一遍，外加 2–3 个不同价位的付费模型，补全"适合干什么、能不能干活"。
- **时机**：有空时做，等额度 reset 后再跑；分批跑，避开 429，不要一次硬刚。
- **两个黄金 probe**（固定题目，保证可比；Stone 只关心这两方面能力）：
  1. **股票实操分析**：用历史案例（如某次 TSLA 关键位），问进出场、仓位、止损。只评"是否给了具体可执行的数字和风控"，不评预测对错。
  2. **程序与设计**：一道小程序题（Python，能直接跑，客观判对错）+ 一道设计评审小问。
- **付费模型选型**：cheap / standard / premium 各 1 个（如 deepseek-v3.2 / claude-sonnet 级 / opus 级），选型时看 OpenRouter 实时价。
- **预算**：每周最多 **$5**（Stone 定的硬上限；余额不足他再充）。probe 脚本自带 ledger，超了自动停付费 probe 并汇报。
- **D12 预算护栏（2026-10-11，qwen 第三批烧了 $1.30 之后加的）**：① 单模型周上限 $0.50（按最坏费用估计触发，`--per-model-cap` 可调），超限只停该模型、不殃及其他；② 同一模型连续 2 题失败即停该模型剩余题目（"两次失败就停"，不再拿钱续命）；③ 失败/空返回的调用按 `usage.cost` 如实记账——修复第三批 ledger $3.86 对不上服务端实际扣费 $5.65 的已知 bug。
- **产出**：结果写回 `docs/model-profiles.md`（擅长项 + 可靠性备注）。
- **评测题目迭代（2026-10-11，Stone 点评第三批后立）**：付费大模型的股票分数全是 15/15，没拉开差距——S1–S3 只能测"会不会"，测不出"好不好"。下一版题目要加难（比如：给互相矛盾的信号看它怎么取舍、埋陷阱数据看它会不会被带偏、让它在"等"和"动"之间做艰难选择），重新拉开区分度再测一遍。P1 隐藏测试同理（多数 10/10，无区分度）。**当前阵容结论不受影响——先用便宜的。**

## 10. 智囊团自评审（2026-10-11，2 家免费模型评审设计文档，待 Stone 拍板）

共识最强的三条（两家都点名）：
1. **每日扫描不够 → 要实时健康检测**：免费池波动频繁（429/下架/改名），cron 保鲜不够。改进：每次跑 panel 前对候选模型轻量 ping，坏的当场踢出本轮；维持热备列表。fail-closed 不能变成"池子一空就全失败"。
2. **Judge 标准模糊 → 写死**：拒绝权的 checklist（空答/答非所问/幻觉信号）+"重要事项"的定义（建议：涉及花钱、对外、不可逆决策才升级人终审）。
3. **预算控制粗糙 → per-call 上限 + 触发确认**：熔断不能只看累计；跑之前先报"预计耗时 X 分钟、费用约 $Y，是否启动"（落实"不擅自跑"）。

其他有价值的单条：
- 对抗轮并行化（critics 同时跑，judge 等最慢的，别串行）。
- 能力档案自动化（已在 §9 评测计划里覆盖）。
- 里程碑拆分：先保核心 pipeline，再叠汇报/熔断/红队（v0.1 核心已通，这条半对半错）。
- 忽略：多用户并发配额（单用户场景不适用——已当噪音过滤掉）。

注：评审来自 2 家免费模型，样本小；共识度高的三条建议采纳。

## 10b. 第二轮自评审（2026-10-11，ultra-550b 单家交卷，待 Stone 拍板）

本轮 3 家新模型 2 家空返回（ling-3.1-flash、lfm-2.5 长 prompt 不可靠，已记档案）；唯一交卷的 ultra-550b 质量极高，且反驳了第一轮的部分建议：

1. **"主动问一句"在手机异步场景是伪命题**：Stone 发完消息即离开，回问确认时已无上下文。建议：预估成本/时长附在首条回复，Stone 回"去/改"即确认，零额外轮次。
2. **启动前 ping 防不住分钟级波动**：免费模型 429/下架是分钟级的，ping 只能测"当下通"。建议：输出校验（空/截断检测）+ 异常即时熔断切备用；流式心跳实现成本高，先做输出校验。
3. **Judge 不能全凭 prompt**：拒绝权/分级无 Schema 约束，synth 易把 nitpick 当 major。建议：Judge 结构化输出 Schema（verdict: accept|reject|escalate + severity + evidence），代码层强校验。
4. **预算熔断忽略"并行放大×重试风暴"**：3 模型×2 轮×judge+synth = 单次 8-10 次调用，429 重试指数爆费用。建议：启动前按"最坏并行路径"算封顶价，超线熔断上报。
5. **进展汇报推模式易刷屏**：建议默认静默，仅超时/全拒/预算触顶/需人终审四类事件推；Stone 回"进度"再拉详情。注：这条与 Stone"运行时每步反馈"规则有张力——折中：他在等结果的智囊团运行时保持进度，后台任务用拉模式。
6. **多轮辩论缺上下文压缩**：3 模型×2 轮轻松超免费模型 8k/16k 窗口，synth 前必须摘要压缩。
7. 与第一轮共识：red-team 并行 fan-out；能力档案纯人工注定过期（§9 已覆盖）。

两轮综合、只改三件：① 触发确认零轮次化；② Judge 结构化契约；③ 最坏路径封顶价 + 健康检测（启动前 ping + 输出校验）。

## 10c. 第三轮（2026-10-11，结论：共识已收敛，无需第四轮）

本轮 gemma-4-26b、laguna-s-2.1 均 429；lightning 两次只吐思考过程、写不完结论（已记档案，不适合要干净结论的任务），judge 第一轮拒掉其截断版是正确的。
有价值的残篇信号：lightning 在被截断前已在做"评审的评审"——综合 §10/§10b，方向与 §10b 的 top3 完全一致。
三轮统计：8 个模型次调用，4 次成功交卷，4 次 429/空返回——免费模型可用率约 50%，这本身就是"健康检测"建议的最佳论据。
结论：三轮共识 top3 已稳定（①触发零轮次 ②Judge 结构化契约 ③最坏路径封顶价+健康检测），可拍板开工。

## 11. v0.2 实现（Stone 2026-10-11 拍板，当天实现+验证）

三件全部落地（`thinktank.py`，纯标准库）：

1. **触发零轮次**：`--estimate` 不调 API 直接打印运行预估（调用次数、completion token 上限、费用上限、耗时），Muse贴出预估、Stone 回"去/改"即确认。聊天侧规则同步更新：不再是"先问一句"，而是"预估附首条"。
2. **Judge 结构化契约**：judge 必须返回 per-answer `decisions`（`verdict: accept|reject|escalate` + `severity: critical|major|minor|nitpick` + `evidence`）；代码层 `validate_judge` 严格校验，不合规 = judge 失败 → 降级人终审（fail-open）；`escalate` 自动转人终审；synth 前过滤 `nitpick`；旧格式兼容转换。2026-10-11 实测 cohere 一次输出合规 JSON 并正确拒掉答非所问。
3. **最坏路径封顶价 + 健康检测**：启动前算最坏路径费用——付费模型缺价格表（`--prices`）或超 `--budget` 直接拒绝启动（exit 2/3），免费模式费用恒 $0；panel 前对每模型轻量 ping（max_tokens=50，太小会误杀），死的本轮剔除，全死则 fail-closed。

实现中学到的 quirk：cohere 在 `max_tokens≤20` 时直接 `finish_reason=length` 返回空——health ping 必须 ≥50（已记入模型档案）。

## 12. v0.3 实现（Stone 2026-10-11 拍板，当天实现+验证）

1. **双 judge 交叉验证**（`--judge-model2`）：两个异构 judge 并行打分，winner 一致才自动通过，否则转人终审。
2. **动态成员选择**（`--member-state`/`--capability-scores`）：schedule_score = capability × availability；availability 基于滑动窗口成功率 × 温和延迟惩罚（`1/(1+lat/120)`）。
3. **实时数据注入**（`--context-data`）：Muse 先搜实时数据生成 JSON，panel 用注入数字而非训练记忆。system prompt 声明知识截止、禁编造数字。
4. **分歧熵脚手架**：每轮计算 disagreement entropy，为未来多轮收敛铺路。

## 13. 智囊团评审框架（Stone 2026-10-12 定）

面向用户的改动（README、示例、公开 API、宣传文案）在合并/发布前走一轮智囊团评审：

1. **触发条件**：改动影响外部读者理解或项目形象时触发；纯内部重构不触发。
2. **评审维度**（prompt 模板）：
   - 小白友好：5 分钟能跑起来吗？哪句话会劝退新手？
   - 老鸟钩子：技术亮点讲清楚了吗？有什么值得 star/PR 的点被埋没了？
   - 准确性：有没有夸大、过时或与代码不符的描述？
   - 推广性：有没有一句能拿去发 Twitter/HN 的 slogan？
3. **执行**：2-3 家模型并行评审 → 双 judge 挑出最有价值的 3-5 条 → 人（Stone/Muse）拍板采纳。
4. **记录**：评审结论记入本节附录，标注日期与版本。
5. **豁免**：紧急修复可先合并后补评审，但必须在 24h 内补。

### 附录：评审记录
- 2026-10-12：README 写作评审（ultra-550b + super-120b）。结论：6 节结构（Hero/快跑/架构/对比表/进阶/贡献）；小白三手法（一键 demo、对比表、init 向导）；老鸟三钩子（双 judge、--context-data、fail-open）；slogan："One prompt, a council of models, zero hallucinations."

## 14. Validator 层与评测 Harness 排查清单（Stone 2026-10-13 定，design 先行）

背景：v3.1 评测实跑验证确认，12 家里 9 家出现"代码对、粘贴输出与实跑不符"（ultra-550b 惯犯×2）。"Benchmark 测的是模型+Harness"——harness 必须自己验证数字，不能信模型贴的。

### 14.1 Validator 层（待实现，先定设计）

**智囊团评审（2026-10-13 快问，ultra-550b + dots-3，judge gemini-3-flash）**：设计意图通过，但挑出三个真 hole → 本节已按评审意见改 v2。

1. **触发条件**：panel/judge 回答同时含代码块 **且** 含"运行输出"/数字结论声明时触发。
2. **分两期**（评审建议的简化方案）：
   - **Phase 1（先做）**：格式校验 + 定向抽检。不建全量沙箱——先查输出格式是否合规（JSON/表格/数字结构），不合规标可疑；只对可疑样本 + 已知惯犯（fabrication 黑旗模型）做沙箱实跑或人工抽检。省 infra 成本，误报少。
   - **Phase 2（后做）**：全量沙箱 diff，解决下面三个 hole 后再上。
3. **三个 hole 的解法（Phase 2 前提）**：
   - **映射歧义**：约定配对格式（代码块后紧跟 output 块，或显式编号）；配对不上 → 记 `unverifiable`（待人工），**不记** fabrication。
   - **环境一致性**：沙箱 pin 死 Python + numpy/pandas/scipy 版本；diff 前归一化非确定字段（时间戳、内存地址）；数字比对用容差（1e-6）不用文本精确匹配；随机性代码要求 seed 或跑 3 次取众数。
   - **标签三档**：`verified`（一致）/ `needs-review`（环境/映射问题，待人工）/ `fabrication`（明确编造，如数字与代码逻辑不可能得出）。二元标签太武断，三档防噪声污染档案。
4. **记分**：fabrication 接入模型档案可靠性维度（v3.1 已有黑旗记录：ultra-550b×2、v4-pro、opus-4.6、gemini、cohere、minimax、v3.2、llama、dots-3 各×1；干净：sonnet-5.5、gpt-5-mini）。
5. **Harness 设计原则**：一次写好、永久生效——validator 是机制不是 prompt，不随模型换而失效。

**实现状态（2026-10-13）**：Phase 1 已实现 → `tt/validator.py`（CLI：`python3 -m tt.validator --file <md> --model <id> [--force]`）。
v3.1 S6 实测：ultra-550b/v4-pro 的 fabrication 正确检出；sonnet（表格格式）→ format-ok；gpt-5-mini（散文格式）→ unverifiable。
thinktank.py 运行时接入为 Phase 2，本期不做。

### 14.2 评测 Harness 排查清单（跑分前必过）

模型分数异常时，**先查外壳再下模型结论**：

1. **token 上限**：按模型家族×题型设（GPT-5-mini 长任务 7000、Claude 4000–6000、默认 4500）；截断= harness 问题，重跑再判分（sonnet-5.5 v3 11.0→v3.1 20.0 就是注脚）。
2. **prompt 格式**：题目 ID 与 batch 文件一致（launcher 启动时 assert，禁用 sed 链改脚本）。
3. **解析逻辑**：输出解析、文件命名、CSV 列名等有无 bug（如 v3 S6 文件名存错导致 0 分类问题）。

本节为设计先行：实现（validator 代码 + eval 流程接入）待 Stone 看过 design 后再动工。

**v0.9（2026-10-13）**：四步流水线（骨架常驻）——解决切块丢上下文：
1. 骨架提取：tt/skeleton.py 确定性提取函数/类/import 变更（无模型调用）
2. 依赖分组：（TODO）AST 找签名变更及其调用者
3. 局部审查：每块输入 = 全局骨架 + 当前 diff
4. 全局一致性校验：只查接口，不看实现

## 15. 大 diff 评审的四步流水线（v0.9，2026-10-13）

**问题**：25KB diff 一次性给模型，judge 要处理 19k tokens，弱模型频繁失败。切块后任务变小但丢跨文件上下文。

**解法**：模仿人类 reviewer——"骨架常驻，细节按需加载"。

### 步骤 1：骨架提取（tt/skeleton.py）
- 确定性提取（正则，无模型调用）：每文件的函数/类增删、import 增删
- 输出：结构化骨架，通常几千 tokens
- 代价：零 API 调用

### 步骤 2：依赖分组（TODO）
- 用 AST 找出"签名变了的定义"及其直接调用者，放同一组
- 局限：核心 API 大改时退化，需 fallback 到步骤 1+3+4

### 步骤 3：局部审查
- 输入：**全局骨架 + 当前文件的完整 diff**
- 输出：局部 bug + 标 `needs_cross_check` 的疑似跨文件问题
- 每块 ~3k tokens，模型稳定完成
- 实现状态：串行（每块用 `models[0]`），并行为 TODO（v0.9.1）

### 步骤 4：全局一致性校验
- 输入：所有骨架 + 所有 `needs_cross_check`
- 只查：接口不匹配、调用链断裂、类型不一致
- 不看实现细节

### 实现状态（2026-10-13）
- ✅ 步骤 1（骨架提取）：已实现，`tt/skeleton.py`
- ⏳ 步骤 2（依赖分组）：TODO，需 AST
- ✅ 步骤 3（局部审查）：已实现，串行；并行 TODO
- ✅ 步骤 4（全局一致性校验）：已实现，`synth` 汇总时执行

### 触发条件
`--pr-diff` 且 diff > `--chunk-tokens` × 2（默认 6k tokens）时自动启用。
`--chunk-tokens 0` 可禁用。

### 与 v0.8 的区别
v0.8 是裸切块（无全局视野）。v0.9 每块都带全局骨架，跨文件问题可见。

## 16. Roadmap（Stone 2026-10-14 批准排序）

改进清单 13 项 + auto-skill，按此顺序：

**Phase 0 — 先行（auto-skill 之前）**
- [x] **Run Record（1）**（2026-10-14 merged）：每次运行生成版本化 JSON（输入、模型、输出、费用、错误），`--record`/`--replay`。纯加法，1-2 天。理由：auto-skill 的 skill 匹配/依赖解析是黑盒决策，没有轨迹可查，debug 靠猜。

**Phase 1 — auto-skill**
- [x] **Auto-skill Layer 0 + 3 seed skill（0）**（2026-10-14 merged）：manifest 标准 + 股票/code review/写作。Domain pack（6）并入此处，不单独排期。

**Phase 2 — 可测量**
- [x] **Golden cases（3）**（2026-10-14 merged，三轮评审 12 个问题全修）：股票/code review/文档各一组硬案例，离线回归，指标退化非零退出。
- [ ] **Decision Object（12）**：机器可读 JSON 输出（verdict/confidence/disagreements/evidence/actions），复用 Run Record schema。

**Phase 3 — 正确性**
- [x] **外壳稳定性 v0.16**（2026-10-21，红队评审事故驱动：critics 仅 1/3 可用、截断草案带 high confidence 胜出、降级只埋在日志里）：① 结构化角色（judge/critic/adjudicator）契约失败一次修复重试（第二次调用 token 翻倍，空回复走普通重试）；② critic 补位（备选池未给时按 capability-scores 自动生成）；③ 截断门（胜出答案截断 → 置信度封顶 + 报告明示）；④ completeness 报告头（降级宣告进交付物）；⑤ `scripts/test_stability.py` 故障注入回归。实测：同日 cheap 档实跑，judge 空回复重试恢复、critic 修复恢复、adjudicator 两次不过 → 明示降级原始输出。
- [ ] **角色适配矩阵**（2026-10-21 立项）：选人按角色过滤而非只看总分——用 member-state 按角色（panel/judge/critic/adjudicator）统计契约失败率，多次在某角色掉链的模型自动退出该角色候选（minimax 不进 judge、gpt-5-mini 结构化角色不稳均属此类）。依赖 member-state 数据积累。
- [ ] **Evidence bundle（8）**：context-data 升级为带 source_id/抓取时间/哈希的证据包。
- [ ] **Verification Floor（2）**：工具验证下限（测试/lint/计算/时效），证不出标 unverified。依赖 8。
- [ ] **分歧地图（5）**：已共识/仍分歧/缺证据/需人拍板四块输出。
- [ ] **Router 视角**（2026-10-16，@kafkaup 路由文章启发）：选人即路由——"路由错了，大模型救不回来"，panel 选错 judge 再强也是在错误答案里挑。两项：① judge 低置信/选不出 winner 时的追问或降级机制；② 选人准确率追踪（事后看选的 panel 是否真合适）。
- [ ] **Evaluation harness**（2026-10-16，Spec-Driven 论文启发）："Tests catch deterministic regressions; evaluation catches behavioural drift." 给 agent 任务加正式 eval 层——LLM-as-judge 打 0-5 分，设容忍带，低于阈值告警。区别于 Golden cases（3）的离线回归：Golden 测"答案对不对"，eval 测"行为有没有漂"。依赖 3（golden cases 做基线）。

**Phase 4 — 效率**
- [ ] **阶段缓存（10）**：panel 落盘，judge/synth 失败只重跑缺失阶段。
- [ ] **上下文压缩（9）**：可测量可关闭，实测为准（Delibera 公开实测 ~12%，非 30-70%）。依赖 3。
- [ ] **Peer critique（4）**：高分歧时才触发互评轮，不做默认。
- [ ] **事件流（13）**：CLI/JSON Lines 事件（run_started/panel_completed/human_input_required…），UI 以后再说。

**暂缓**
- **Provider adapter（11）**：OpenRouter 够用，加第二 provider 时再做。

**Phase 5 — pstack 借鉴**（2026-10-18，Lauren Tan pstack 启发，来源：https://github.com/cursor/plugins/tree/main/pstack）
- [ ] **Interrogate 加权规则**：多模型独立提出同一 finding = 最高信号。合进 judge 逻辑——两个以上 judge/panel 成员独立指出同一问题时，置信度加权上调；单个模型的孤立 finding 降权。来源：pstack `interrogate` skill Step 4。
- [ ] **四档 verdict**：Act on / Consider / Noted / Dismissed，替代现在的 accept/reject/escalate 三档。更细的粒度减少"非黑即白"误判。
- [ ] **Mistake class 机制**（`correct` skill）：同一错误出现两次即记为一类，按"架构 > 类型 > lint/CI > 文档"顺序修，每类修完用真实历史错误验证。升级现有 incident-to-eval——不只"变成考题"，要"让这道题出不出来"。
- **Competing implementation（7）**：独立 skill/adapter，不碰核心 pipeline。

**排序逻辑**：先可测量（1、3），再更对（8、2），最后更省（10、9）。

**Phase 6 — Harness² 借鉴**（2026-10-18，Google Harness² 启发，来源：https://github.com/google-research/harness2）
核心思想：模型是常量，harness 是变量——优化外围系统（prompt/工具/编排）不碰模型权重也能涨分。
- [ ] **8 组件审计**：对照 Harness² 的 8 个可编辑组件（System Prompt、Guardrails、Memory、Tool Guidance、Subagents、Skills、Scripts、Plugins）给 thinktank 做一次覆盖检查。已知缺口：Plugins（无插件机制）、Memory（member-state 只记模型分数）、Scripts（tt/*.py 散装）。
- [ ] **PPC 优化 judge prompt**（Propose-Probe-Compose）：在 golden cases 上提议 judge prompt 变体 → 探测行为差异（不需标准答案）→ 合成最优版。替代手调 prompt。
- [ ] **member-state 升级**：从"记模型分数"扩展到"记 harness 改动效果"——每次调 prompt/阈值/路由，记录效果涨跌，经验沉淀。

## 15. v0.18 Harness hardening（2026-10-27）

背景：10/23 一轮评审 panel 塌方记的三项账（panel 空回复重试、按模型族设 token 下限、estimate 计入 context）一直没落地；10/27 早一轮实跑又复现三病，还添了两个新病（付费版进 free 档后价格表缺口、synth 截断）。五项同批修，单点真相都在 `tt/budget.py`（价格+下限+预算公式）与 `tt/transport.py`（重试），estimate 与执行同口径，改一处两边一起变：

1. **health check 重试**：瞬时失败（空返回、网络错、429/5xx）最多 3 次、1s/2s 退避；401/403/404 永久错不重试。重试次数记进 runlog（`attempts`）。
2. **默认价格表**（`KNOWN_PRICES`）：preset 自带的付费模型自带价，`--prices` 显式项优先；`worst_case_cost` 自己合并，不再依赖调用方先过 `load_prices`。
3. **token 下限**（见 §3.3）：`effective_max_tokens`，judge/critic/adjudicator/panel/备选全走同一函数。
4. **panel 重试**（`panel_call`）：judge/critic 早有的一次修复重试，panel 补上——空/错/截断（`finish_reason=length`）时 token 翻倍重跑一次；两次都败且首轮有残文时留残文（自由文本残文优于空位，judge 的结构化角色仍按两败出局）。
5. **estimate 计入 context + synth 下限**：`prompt_chars`（问题 + context 文件）进预算公式；panel 最坏按首轮 + 翻倍重试计（3 倍 cap，与 judge 的 x2 对齐）；synth 上限 `max(4000, 下限)`，与 estimate 的 `completion_cap` 同一函数。

验证：91 单测 + stability 全过；实跑 free 档一轮——health check 当场重试救回一个 panel 模型，panel 2/2、judge、synth 全通，花费 $0.0001，runlog 落盘。
