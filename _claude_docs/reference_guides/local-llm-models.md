# Local LLM models for this PC

Research date: 2026-09-27. The model landscape moves fast, so re-check before relying on this.

**This PC:** Ryzen 5 7600 (6 cores / 12 threads, Zen 4, AVX-512), **no discrete GPU**, 32GB DDR5 **at 4800 MT/s**, 230GB free disk. Usual load: about 50% of RAM for VS Code + browser.

---

## 1. What limits speed on a CPU-only machine

- **The iGPU doesn't help.** The 7600's Radeon graphics has only 2 compute units, so inference runs on the CPU.
- **Generation speed ≈ memory bandwidth ÷ bytes read per token.** Dual-channel DDR5-4800 is about 77 GB/s in theory and about 55–60 GB/s in practice.
  - A **dense** 9B model at 5-bit reads about 6.6GB per token, giving about **8 tok/s**.
  - A **Mixture-of-Experts (MoE)** model only reads its *active* experts (about 3–4B parameters), so a 26–35B MoE runs at roughly **12–20 tok/s** while being much smarter.
- **Prompt processing (prefill) is slow on a CPU**: roughly 50–150 tok/s. A 70K-token prompt would take ten minutes or more, which is why elastalert2-llm keeps prompts under about 8K tokens and uses small tool results.
- **Free speed:** check whether your RAM kit is rated above 4800 (look at the sticker, or CPU-Z → SPD). If it is, enable **EXPO** in the BIOS. DDR5-6000 gives about 25% more tokens per second for free.

The tok/s figures here are estimates from bandwidth maths, not measurements on this PC. Measure your own with `ollama run <model> --verbose`, which prints `eval rate`.

---

## 2. Recommended models

| # | Model | Quant / file size | RAM needed | Est. speed | Best for |
|---|---|---|---|---|---|
| 1 | **Qwen3.6-35B-A3B** (MoE, 3B active, Apr 2026) | UD-IQ3_XXS 13.2GB (or UD-Q2_K_XL 12.3GB) | ~14–15GB | ~12–18 tok/s | Strongest that fits; agentic / tool calling. **Only when the ES stack is stopped** |
| 2 | **Gemma 4 26B-A4B** (MoE, 3.8B active) | UD-IQ4_XS 13.6GB / UD-Q3_K_M 12.7GB | ~14–15GB | ~10–15 tok/s | Best quality-for-size (4-bit). **Only when the ES stack is stopped** |
| 3 | **Qwen3.5-9B** (dense, Mar 2026) | Q5_K_M 6.6GB | ~8GB | ~7–9 tok/s | **Daily driver while ES + Kibana run.** Direct upgrade from Qwen2.5-7B |
| 4 | **gpt-oss-20b** (MoE, 3.6B active) | MXFP4 ~13GB (native format) | ~14GB | ~12–18 tok/s | Reliable JSON/instruction following; `reasoning_effort` low/medium/high |
| 5 | **Qwen3.5-4B** / **Gemma 4 E4B** | Q4_K_M ~3GB | ~4GB | ~18–22 tok/s | Fast drafts and quick iterations |

Benchmarks (Artificial Analysis Intelligence Index, April 2026 version):
- Qwen3.5-35B-A3B scores 37, and Qwen3.6-35B-A3B improves on it per Qwen.
- Gemma 4 26B-A4B scores 31, and Qwen3.5-9B about 32.
- gpt-oss-20b scores about 24, as does Nemotron 3 Nano.

For comparison, your current Qwen2.5-7B predates all of these and scores far lower.

**Not recommended here:**
- Dense 27B models (Qwen3.6-27B / Qwen3.8-27B) run at only 3–4 tok/s on this CPU.
- Nemotron 3.5 Lightning scores lower, and even Q3 is 14.7GB.
- Ollama's default `gemma4:26b` (19GB) and `qwen3.6:35b` (23GB) tags are too big with VS Code and a browser open.

---

## 3. Install and switch (Ollama 0.34 is already installed)

```bash
# daily driver (fits alongside the ES stack)
ollama pull hf.co/unsloth/Qwen3.5-9B-GGUF:Q5_K_M

# big models (stop the ES stack first: docker compose stop)
ollama pull hf.co/unsloth/gemma-4-26B-A4B-it-GGUF:UD-IQ4_XS
ollama pull hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:UD-IQ3_XXS
ollama pull gpt-oss:20b

ollama list                 # what's installed
ollama ps                   # what's loaded in RAM right now
ollama stop <model>         # unload immediately
ollama rm <old-model>       # e.g. remove your Qwen2.5-7B
```

All five take about 50GB of disk. Keep **one model loaded at a time**: set the user environment variable `OLLAMA_MAX_LOADED_MODELS=1` (Windows Settings → Environment Variables), then restart Ollama.

The `hf.co/<user>/<repo>:<quant>` syntax pulls a GGUF straight from Hugging Face. If a tag name doesn't resolve, open the repo page and copy the exact quant file name.

---

## 4. RAM budget

| Setup | VS Code + browser | ES + Kibana | Model | Total |
|---|---|---|---|---|
| Developing against local ES | ~16GB | ~4GB (see [.wslconfig](../setup/elasticsearch-kibana-local.md#1-give-docker-wsl2-a-memory-budget-first)) | Qwen3.5-9B ~8GB | **~28GB, OK** |
| Model quality testing | ~16GB | stopped | Gemma 4 26B / Qwen3.6-35B ~14–15GB | **~31GB, tight: close tabs** |
| Both big model + ES | ~16GB | ~4GB | ~15GB | **~35GB, won't fit (swapping)** |

---

## 5. Settings that matter for elastalert2-llm

- **Context (`num_ctx`)**: 16K is plenty. Each extra 1K of context costs KV-cache RAM and prefill time.
- **Thinking**: Qwen3.x thinks by default. Turn it off for quick edits and on for debugging sessions.
- **Tool calling**: Qwen3.5/3.6, Gemma 4 and gpt-oss all support Ollama's `tools`. The 9B model manages short tool loops; multi-step debugging works noticeably better on the MoE models.
- **Structured output**: Ollama's `format` parameter (a JSON schema) forces valid JSON, which is critical for smaller models.

## Sources

- [Artificial Analysis – Sub-32B open weights](https://artificialanalysis.ai/articles/sub-32b-open-weights)
- [Artificial Analysis – Qwen3.5 small models](https://artificialanalysis.ai/articles/qwen3-5-small-models)
- [Artificial Analysis – Nemotron 3.5 Lightning](https://artificialanalysis.ai/articles/nemotron-3-5-lightning-launch)
- [Qwen3.6-35B-A3B announcement](https://qwen.ai/blog?id=qwen3.6-35b-a3b)
- Unsloth GGUF pages: [Qwen3.6-35B-A3B](https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF), [Gemma 4 26B-A4B](https://huggingface.co/unsloth/gemma-4-26B-A4B-it-GGUF), [Qwen3.5-9B](https://huggingface.co/unsloth/Qwen3.5-9B-GGUF)
- Ollama library: [qwen3.6](https://ollama.com/library/qwen3.6), [gemma4](https://ollama.com/library/gemma4)
- [Gemma 4 CPU inference benchmark](https://www.kunalganglani.com/blog/gemma-4-cpu-inference-benchmark)
- [Nemotron 3.5 Lightning sizes](https://localmodel.run/model/nemotron-3.5-lightning-30b-a3b)
