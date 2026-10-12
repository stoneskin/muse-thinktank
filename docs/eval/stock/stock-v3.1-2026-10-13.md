# Stock Quantitative Reliability Eval v3.1 · 2026-10-13

Tasks: S4 K=102 off-quote interpolation / S5 corrected answers / S6 script task with embedded data / S7 cleaned data.
Scoring: 5 points per task, human-graded with independent verification and actual script execution.
Total cost: ~$0.91.

## Scores (max 20)

| Model | Tier | S4 | S5 | S6 | S7 | Total/20 |
|---|---|---|---|---|---|---|
| anthropic/claude-sonnet-5.5 | mid | 5.0 | 5.0 | 5.0 | 5.0 | **20.0** |
| minimax/minimax-m3 | cheap | 5.0 | 4.0 | 5.0 | 5.0 | **18.0** |
| openai/gpt-5-mini | cheap | 5.0 | 4.5 | 5.0 | 3.5 | **18.0** |
| anthropic/claude-opus-4.6 | premium | 5.0 | 4.5 | 3.0 | 5.0 | **17.5** |
| google/gemini-3-flash-preview | cheap | 5.0 | 4.0 | 3.0 | 5.0 | **17.0** |
| deepseek/deepseek-v3.2 | cheap | 5.0 | 4.0 | 2.5 | 5.0 | **16.5** |
| meta-llama/llama-4-maverick | cheap | 5.0 | 5.0 | 3.0 | 3.5 | **16.5** |
| dots-studio/dots-3-note-preview:free | free | 5.0 | 4.0 | 3.0 | 3.5 | **15.5** |
| nvidia/nemotron-3-ultra-550b-a55b:free | free | 5.0 | 4.0 | 3.5 | 2.5 | **15.0** |
| cohere/north-mini-code:free | free | 5.0 | 4.0 | 3.0 | 2.5 | **14.5** |
| nvidia/nemotron-3-super-120b-a12b:free | free | 5.0 | 4.5 | 0 | 0 | **9.5** |
| deepseek/deepseek-v4-pro | cheap | 1.5 | 0.5 | 3.5 | 3.5 | **9.0** |

## Key findings

1. **sonnet-5.5 perfect 20.0**: refused to fabricate numbers, cross-checked by hand. Most honest + most accurate.
2. **"Code correct, output fabricated" is epidemic**: 9 of 12 models' pasted outputs didn't match real runs. Rubric must require "pasted output matches actual execution".
3. **S5 trap still works**: 5 models' conclusions contradicted their own scripts even after explicit "don't recite textbooks".
4. **S4 difficulty increase failed**: 11/12 perfect at K=102. Needs steeper vol smile or extrapolation test.
5. **max_tokens lesson**: long prompts need 4000-7000 tokens depending on model. Harness should set limits per task type.
