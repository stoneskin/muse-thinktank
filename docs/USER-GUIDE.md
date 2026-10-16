# muse-thinktank User Guide

> For regular Muse users: no coding needed, just follow along.

[中文版](USER-GUIDE_zh.md)

---

## What is this?

You ask Muse a question. Muse sends it to several AIs at once, they each answer, judges pick the best, and Muse merges it into one verdict. More reliable than asking a single AI.

**Example**: you ask "How's Tesla stock looking?" — 3 AIs analyze independently, judges pick the most solid one, Muse delivers a merged report.

## Three steps to start

### Step 1: Get an API key (2 min)

The think tank calls multiple AI models, which needs a key.

1. Go to https://openrouter.ai/keys
2. Sign up / log in (Google one-click works)
3. Click **Create Key**, copy the `sk-or-v1-...` string
4. **Free models cost $0** — plenty for daily use

> OpenRouter only for now; more providers coming.

### Step 2: Tell Muse to connect

Say one sentence in Muse:

> **"Connect to OpenRouter"**

Muse gives you a secure link. Tap it, paste the key, confirm. The key is stored securely — Muse never sees the plaintext.

### Step 3: Copy-paste this to your Muse

Copy the block below and paste it into Muse (or another AI like Grok):

```
Please install this open-source project for me: https://github.com/stoneskin/muse-thinktank

Follow the steps in AI_SETUP.md in its repo.
When you need an API key, stop and tell me to get a free one at https://openrouter.ai/keys first.
```

The AI will automatically: download → check environment → run a test → tell you "ready".

> No terminal, no programming needed.

## Start using it

After install, just talk to Muse:

- **"上智囊团，分析下特斯拉股票"** (or in English: "think-tank this: Tesla stock outlook")
- **"议一议，PostgreSQL vs MongoDB?"**
- **"Have a few models debate the risks of this plan"**

Want it torn apart instead of discussed? Ask Muse to **挑刺 / 找茬** (red-team mode):

- **"挑挑刺，这篇文章写得站得住吗？"**
- **"找找茬，这个方案有什么漏洞？"**

Red-team runs the normal deliberation first, then critics attack the draft and grade every finding (critical/major/minor). You get a report, not just a verdict.

Muse shows you the cost and ETA first (free models = $0). Say "go" and it runs.

## Specialist modes

For certain topics, Muse loads specialist background data *before* the panel starts debating, so the AIs argue from real context instead of thin air:

- **Stock analysis** — when you ask about a stock, Muse pulls live technical indicators first (RSI, MACD, moving averages, volume, 52-week range). The panel debates real numbers, not stale training data.
- **Code review** — when you ask for a PR review, Muse fetches the actual diff and file stats first.
- **Writing help** — when you ask for an article or doc, Muse sets up audience, language, and style context first.

You don't need to do anything — Muse picks the right mode from your question. To force one, say e.g. "use stock-analysis mode for this".

## Save and replay a run

Every deliberation can be saved as a **run record**: one file holding the question, which models ran, what each stage produced, the cost, and the final verdict.

- **Save it**: after a run, say "save this run". You get a file you can keep, share, or revisit later.
- **Replay it**: say "replay that run". Muse prints the summary from the saved file — zero AI calls, costs $0.

Handy when you want to audit an old decision, or compare how the same question performs weeks apart.

## Built-in quality checks

The project ships with offline regression tests ("golden cases") covering stock analysis, code review, and docs. They run with zero API cost and fail loudly if anything breaks — mostly useful for developers. Curious? Ask Muse to "run the golden cases".

## FAQ

**Q: Does it cost money?**
A: Free models cost $0. Muse always shows the cost before running — nothing happens without your OK.

**Q: Do I need to know programming?**
A: No. You just talk to Muse; it handles install and runs.

**Q: Reliable for stocks?**
A: Yes, with one condition — AI training data is stale. Muse searches live prices and earnings first, then lets the panel analyze real numbers.

**Q: It's taking long?**
A: Free models sometimes queue. Muse shows live progress: which model is running, how much longer.

**Q: New phone?**
A: The key lives in your Muse account. Just say "install muse-thinktank" again.

## Go deeper

- Technical details → [README](README.md)
- 中文版说明 → [中文版](USER-GUIDE_zh.md)
