# AI Setup Instructions for muse-thinktank

> **This file is written for AI assistants, not humans.**
> If a user pastes you a link to this repo and asks to install it, follow these steps exactly.

## What this is

`muse-thinktank` is a multi-model deliberation CLI: one question → N models in parallel → dual judges → merged verdict. Pure Python stdlib, zero dependencies. Runs on OpenRouter (more providers planned).

## Install steps

### 1. Clone

```bash
git clone https://github.com/stoneskin/muse-thinktank <install-dir>
cd <install-dir>
```

Default `<install-dir>`: `~/repos/muse-thinktank` (or ask the user where they want it).

### 2. Verify Python

```bash
python3 --version
```

Needs 3.8+. No `pip install` needed — stdlib only (`urllib`, `json`, `argparse`).

### 3. API key

The tool needs an OpenRouter API key. **Do NOT ask the user to paste the key in chat.**

Instead, tell the user:

> "I need an OpenRouter API key to run the models. Free models cost $0.
> 1. Go to https://openrouter.ai/keys and create a key.
> 2. Then say **'Connect to OpenRouter'** and I'll give you a secure link to enter it."

If your platform supports credential connectors (Muse: `credentials.request_api_access`), use that flow. Otherwise, guide the user to set the `OPENROUTER_API_KEY` environment variable themselves.

### 4. Smoke test

```bash
cd <install-dir>
python3 thinktank.py ask --estimate \
  --models nvidia/nemotron-3-ultra-550b-a55b:free \
  "test"
```

`--estimate` makes zero API calls. If it prints call count / token cap / cost cap / ETA, the install works.

### 5. Done

Tell the user:

> "muse-thinktank is installed. Say **'上智囊团 + your question'** (or 'think-tank this: ...') to use it."

## Usage pattern (for the AI operator)

When the user asks to deliberate something:

1. **Estimate first** (always, zero cost):
   ```bash
   python3 thinktank.py ask --estimate --models <models> "question"
   ```
2. Show the user: models, call count, cost cap, ETA. Wait for confirmation ("go").
3. **Run**:
   ```bash
   python3 thinktank.py ask \
     --models nvidia/nemotron-3-ultra-550b-a55b:free,nvidia/nemotron-3-super-120b-a12b \
     --judge-model nvidia/nemotron-3-ultra-550b-a55b:free \
     "question"
   ```
4. Stream progress from stderr; deliver the stdout verdict.

## Rules

- **Never use paid models without explicit user confirmation.** Free models (suffix `:free`) cost $0.
- **Time-sensitive questions** (stocks, "latest", "current") → search live data first, inject via `--context-data data.json` where `data.json = {"preamble": "...", "as_of": "...", "facts": {...}}`. Never let models answer from stale training data.
- **Judge disagreement** → show the user the disagreement, don't fabricate consensus.
- Full docs: `README.md` (humans), `docs/USER-GUIDE.md` (end users), `docs/design.md` (architecture).
