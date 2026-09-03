# grok-statusline

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Custom status line for the [Grok Build](https://docs.x.ai/) TUI. It shows model, git branch, prompt-cache hit rate, session tokens, generation throughput, cost, and context usage.

[English](README.md) · [中文](README.zh.md)

```
● Grok 4.6 | 📁 .../Work/hysj-helper | 🔀 main | 平均命中 17.23% | 会话 tokens 34,836 | 吞吐速度 7.0 tps | 当前会话 3 轮 | 上下文 8%
```

Grok has no built-in tok/s field. This script estimates throughput from the session transcript and keeps the last value after a turn ends, instead of showing `-`.

## Requirements

- [Grok Build](https://docs.x.ai/) TUI
- Python 3.8+ (stdlib only, no pip packages)

## Install

Copy `statusline.py` to `~/.grok/statusline.py`, then add this to `~/.grok/config.toml`:

```toml
[ui.status_line]
type = "command"
command = "python ~/.grok/statusline.py"
padding = 1
refresh_interval = 1
```

Restart Grok once so it picks up `[ui.status_line]`. Later edits to the script apply on the next status-line refresh.

`~/` is expanded by Grok. `refresh_interval = 1` keeps the row updating while a turn is idle; during a turn Grok already re-runs the script on its own.

### Smoke test

```bash
echo '{"session_id":"t","workspace":{"current_dir":"/tmp/demo","branch":"main"},"model":{"display_name":"Grok 4.6"},"context_window":{"used_percentage":12}}' | python statusline.py
```

## Fields

| Label | Meaning |
| --- | --- |
| model | Display name, with a green dot |
| dir | Working directory, shortened |
| branch | Current git branch |
| 本次命中 | Cache hit rate for the turn in flight |
| 平均命中 | Cache hit rate for the whole session |
| 会话 tokens | Session `input_tokens + output_tokens` (uncached input + output) |
| 本次 tokens | Tokens billed this turn |
| 吞吐速度 | Estimated generation speed |
| 输出 | Estimated output tokens while a turn is running |
| 缓存 | Cache-read tokens this turn |
| 本次费用 | USD this turn (session total when idle) |
| 当前会话 | Turn count |
| 上下文 | Live context-window percent |

On a narrow terminal, fields drop in this order: cache, this-turn hit, output, cost, this-turn tokens, rounds, session hit, session tokens, directory.

## Cache hit rate

```text
hit% = cache_read_input_tokens / input_tokens × 100
```

Both numbers come from `context_window.session_usage`, cumulative for the session. In Grok's ledger those buckets are disjoint:

| Field | Meaning |
| --- | --- |
| `cache_read_input_tokens` | Prompt prefix served from cache (numerator) |
| `input_tokens` | Uncached input (denominator) |
| `cache_creation_input_tokens` | First-time cache writes (not used here) |

They sum to `session_input_tokens`. This is **not** `cache_read / session_input_tokens`. Green at ≥ 50%, otherwise yellow.

This-turn hit uses the same formula on the delta since the turn started.

## Throughput

Grok does not send a native tok/s. The script reads `agent_thought_chunk` and `agent_message_chunk` lines from `updates.jsonl` (the path Grok puts on stdin as `transcript_path`).

Token estimate from visible text:

```text
tokens ≈ CJK_chars / 1.7  +  other_chars / 4
tps    = tokens / (chunk_time − stream_start)
```

Priority:

1. Current model stream (first stream of a turn is counted)
2. Last completed stream this turn
3. Turn average across streams
4. `output_tokens / api_duration` after usage is billed
5. Last turn's value when idle — the row keeps a number instead of `-`

Rates below 0.5 tps are hidden. The figure is an approximation: jsonl coalesces chunks, elapsed time includes TTFT, and tool calls are not decode time.

## Colors

| Segment | Threshold |
| --- | --- |
| Hit rate | ≥ 50% green, otherwise yellow |
| Context | ≥ 90% red, ≥ 70% orange, otherwise purple |

## State

Per-session counters live in `$TEMP/grok-statusline/<session_id>.json` (Windows) or `/tmp/grok-statusline/` (Unix). They are progress snapshots, not credentials.

## License

[MIT](LICENSE)
