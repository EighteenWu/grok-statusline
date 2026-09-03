# grok-statusline

Grok Build TUI 底部状态栏脚本。显示模型、目录、分支、prompt cache 命中率、会话 token、吞吐速度和上下文占用。

## 安装

1. 把 `statusline.py` 拷到 `~/.grok/statusline.py`
2. 在 `~/.grok/config.toml` 里加上：

```toml
[ui.status_line]
type = "command"
command = "python ~/.grok/statusline.py"
padding = 1
refresh_interval = 1
```

3. 重启 Grok。之后改脚本会在下一次状态栏刷新生效，不必再重启。

## 吞吐速度

Grok 不提供官方 tok/s。脚本从 `updates.jsonl` 里的思考/回复文本估算 token，再除以该次模型流的墙钟时间。

优先级：

1. 当前这段生成的实时速度
2. 本轮已完成流的速度
3. 本轮平均
4. `output_tokens / api_duration`（账单回写后的兜底）
5. 回合结束后保留上一轮数字，不再显示 `-`

这是近似值：jsonl 会合并 chunk，时间里包含 TTFT，工具调用期间没有解码。

## 命中率

```text
平均命中 = cache_read_input_tokens / input_tokens × 100%
```

数据来自 `context_window.session_usage`，整场会话累计。`input_tokens` 是未走缓存的输入。≥50% 绿色，否则黄色。
