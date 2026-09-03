# grok-statusline

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[Grok Build](https://docs.x.ai/) TUI 的自定义底部状态栏。显示模型、Git 分支、prompt cache 命中率、会话 token、生成吞吐、费用和上下文占用。

[English](README.md) · [中文](README.zh.md)

```
● Grok 4.6 | 📁 .../Work/hysj-helper | 🔀 main | 平均命中 17.23% | 会话 tokens 34,836 | 吞吐速度 7.0 tps | 当前会话 3 轮 | 上下文 8%
```

Grok 没有官方 tok/s 字段。脚本从会话 transcript 估算吞吐，回合结束后仍保留上一轮数字，而不是显示 `-`。

## 依赖

- [Grok Build](https://docs.x.ai/) TUI
- Python 3.8+（只用标准库，不用 pip 装包）

## 安装

把 `statusline.py` 拷到 `~/.grok/statusline.py`，再在 `~/.grok/config.toml` 里加上：

```toml
[ui.status_line]
type = "command"
command = "python ~/.grok/statusline.py"
padding = 1
refresh_interval = 1
```

改 `[ui.status_line]` 后需要重启一次 Grok。之后改脚本会在下一次状态栏刷新生效。

Grok 会展开 `~/`。`refresh_interval = 1` 让空闲时也会刷新；生成过程中 Grok 本来就会反复跑脚本。

### 冒烟测试

```bash
echo '{"session_id":"t","workspace":{"current_dir":"/tmp/demo","branch":"main"},"model":{"display_name":"Grok 4.6"},"context_window":{"used_percentage":12}}' | python statusline.py
```

## 字段

| 标签 | 含义 |
| --- | --- |
| 模型 | 显示名，带绿色圆点 |
| 目录 | 工作目录（缩短后） |
| 分支 | 当前 Git 分支 |
| 本次命中 | 本轮 prompt cache 命中率 |
| 平均命中 | 整场会话命中率 |
| 会话 tokens | 会话 `input_tokens + output_tokens`（未缓存输入 + 输出） |
| 本次 tokens | 本轮账单 token |
| 吞吐速度 | 估算的生成速度 |
| 输出 | 本轮生成中的估算输出 token |
| 缓存 | 本轮读到的 cache token |
| 本次费用 | 本轮美元（空闲时为会话累计） |
| 当前会话 | 轮次 |
| 上下文 | 当前上下文窗口占用 |

终端变窄时按这个顺序丢字段：缓存、本次命中、输出、费用、本次 tokens、轮次、平均命中、会话 tokens、目录。

## 命中率

```text
命中率 = cache_read_input_tokens / input_tokens × 100%
```

两个数都来自 `context_window.session_usage`，整场会话累计。Grok 账本里这三个桶互不重叠：

| 字段 | 含义 |
| --- | --- |
| `cache_read_input_tokens` | 命中服务端 prompt cache 的前缀（分子） |
| `input_tokens` | 未走缓存的输入（分母） |
| `cache_creation_input_tokens` | 第一次写入 cache（本公式不算） |

三者加起来等于 `session_input_tokens`。这不是 `cache_read / session_input_tokens`。≥ 50% 绿色，否则黄色。

「本次命中」用同一公式，分子分母改为本轮开始后的增量。

## 吞吐速度

Grok 不提供原生 tok/s。脚本读 stdin 里 `transcript_path` 指向的 `updates.jsonl`，只统计 `agent_thought_chunk` 和 `agent_message_chunk`。

可见文本估算 token：

```text
tokens ≈ 汉字 / 1.7  +  其他字符 / 4
tps    = tokens / (chunk 时间 − 本段 stream 开始时间)
```

取值顺序：

1. 当前这段模型流（本轮第一段也算，不跳过）
2. 本轮刚结束的那段流
3. 本轮各段平均
4. 账单回写后的 `output_tokens / api_duration`
5. 空闲时沿用上一轮，不再显示 `-`

低于 0.5 tps 不显示。这是近似值：jsonl 会合并 chunk，时长含 TTFT，工具调用不是解码时间。

## 颜色

| 段 | 阈值 |
| --- | --- |
| 命中率 | ≥ 50% 绿，否则黄 |
| 上下文 | ≥ 90% 红，≥ 70% 橙，否则紫 |

## 状态文件

每个会话的计数写在 `$TEMP/grok-statusline/<session_id>.json`（Windows）或 `/tmp/grok-statusline/`（Unix）。只是进度快照，不含凭证。

## 许可证

[MIT](LICENSE)
