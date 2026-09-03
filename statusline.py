#!/usr/bin/env python3
import json
import os
import sys
import unicodedata

RST = "\033[0m"
DIM = "\033[38;2;108;112;134m"
C_MODEL = "\033[38;2;166;227;161m"
C_DIR = "\033[38;2;137;180;250m"
C_BR = "\033[38;2;243;139;168m"
C_HIT = "\033[38;2;166;227;161m"
C_HIT_LOW = "\033[38;2;249;226;175m"
C_NUM = "\033[38;2;205;214;244m"
C_TPS = "\033[38;2;245;194;231m"
C_COST = "\033[38;2;249;226;175m"
C_CTX = "\033[38;2;203;166;247m"
C_CTX_HOT = "\033[38;2;250;179;135m"
C_CTX_FULL = "\033[38;2;243;139;168m"
C_SEP = "\033[38;2;88;91;112m"
SEP = f"{C_SEP} | {RST}"
STATE_DIR = os.path.join(os.environ.get("TEMP") or os.environ.get("TMP") or "/tmp", "grok-statusline")
STATE_KEYS = (
    "pos", "ss", "tok", "cur_ss", "cur_ts", "cur_thought_tok", "cur_message_tok",
    "turn_gen", "turn_secs", "burst_tps", "burst_gen", "live_tps", "live_gen",
    "prompt_id", "snap", "last_tps", "turn_started_ms",
)


def nest(obj, *keys):
    cur = obj
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def vislen(s):
    n = 0
    i = 0
    while i < len(s):
        if s[i] == "\033":
            end = s.find("m", i)
            i = end + 1 if end != -1 else i + 1
            continue
        o = ord(s[i])
        if o >= 0x1F300:
            n += 2
        else:
            n += 2 if unicodedata.east_asian_width(s[i]) in ("W", "F") else 1
        i += 1
    return n


def fmt_int(n):
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return None


def fmt_pct(x, digits=2):
    if x is None:
        return None
    return f"{x:.{digits}f}%"


def fmt_tps(rate):
    if not rate or rate < 0.5:
        return None
    return f"{rate:.0f} tps" if rate >= 100 else f"{rate:.1f} tps"


def fmt_usd(x):
    if x is None:
        return None
    return f"${x:.4f}"


def hit_color(pct):
    return C_HIT if pct is None or pct >= 50 else C_HIT_LOW


def ctx_color(pct):
    if pct is None:
        return C_CTX
    if pct >= 90:
        return C_CTX_FULL
    if pct >= 70:
        return C_CTX_HOT
    return C_CTX


def short_dir(path):
    if not path:
        return "?"
    path = os.path.normpath(path).replace("\\", "/")
    home = os.path.expanduser("~").replace("\\", "/")
    if path.lower().startswith(home.lower()):
        path = "~" + path[len(home) :]
    parts = [p for p in path.split("/") if p]
    if len(parts) <= 2:
        return "/".join(parts) or path
    return ".../" + "/".join(parts[-2:])


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_state(sid):
    if not sid:
        return {}
    data = load_json(os.path.join(STATE_DIR, f"{sid}.json"))
    return data if isinstance(data, dict) else {}


def save_state(sid, state):
    if not sid:
        return
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        path = os.path.join(STATE_DIR, f"{sid}.json")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, separators=(",", ":"))
        os.replace(tmp, path)
    except Exception:
        pass


def num(v, default=None):
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def est_tokens(text):
    if not text:
        return 0.0
    cjk = 0
    other = 0
    for ch in text:
        if unicodedata.east_asian_width(ch) in ("W", "F"):
            cjk += 1
        else:
            other += 1
    return cjk / 1.7 + other / 4.0


def extract_event(line):
    key = '"sessionUpdate":"'
    u = line.find(key)
    typ = ""
    if u >= 0:
        u += len(key)
        e = line.find('"', u)
        if e > u:
            typ = line[u:e]
    i = line.rfind('"_meta":')
    if i < 0:
        return None
    raw = line[i + 8 :]
    depth = 0
    blob = None
    for j, ch in enumerate(raw):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                blob = raw[: j + 1]
                break
    if not blob:
        return None
    try:
        meta = json.loads(blob)
    except Exception:
        return None
    tok = meta.get("totalTokens")
    ss = meta.get("streamStartMs")
    ts = meta.get("agentTimestampMs")
    if tok is None or ss is None:
        return None
    text = ""
    if typ in ("agent_thought_chunk", "agent_message_chunk"):
        try:
            content = nest(json.loads(line), "params", "update", "content")
            if isinstance(content, dict):
                text = content.get("text") or ""
        except Exception:
            pass
    return typ, int(tok), int(ss), int(ts or 0), text


def rate_if(gen, secs):
    if gen >= 8 and secs >= 0.15:
        return gen / secs
    return None


def commit_stream(turn_gen, turn_secs, burst_tps, burst_gen, thought_tok, message_tok, ss, ts):
    gen = (thought_tok or 0) + (message_tok or 0)
    elapsed = (ts - ss) / 1000.0 if ts and ss else 0
    instant = rate_if(gen, elapsed)
    if instant:
        turn_gen += gen
        turn_secs += elapsed
        if gen >= 48 or not burst_tps:
            burst_tps = instant
            burst_gen = gen
    return turn_gen, turn_secs, burst_tps, burst_gen


def ingest_transcript(path, state, started_ms=None):
    if not path or not os.path.isfile(path):
        return state
    try:
        size = os.path.getsize(path)
    except OSError:
        return state
    pos = int(state.get("pos") or 0)
    if pos > size:
        pos = 0
    try:
        with open(path, "rb") as f:
            if pos == 0:
                f.seek(max(0, size - 2_000_000))
                if f.tell() > 0:
                    f.readline()
            else:
                f.seek(pos)
            data = f.read()
            state["pos"] = f.tell()
    except OSError:
        return state
    last_ss = state.get("ss")
    last_tok = state.get("tok")
    cur_ss = state.get("cur_ss")
    cur_ts = state.get("cur_ts")
    cur_thought_tok = num(state.get("cur_thought_tok"), 0) or 0
    cur_message_tok = num(state.get("cur_message_tok"), 0) or 0
    turn_gen = num(state.get("turn_gen"), 0) or 0
    turn_secs = num(state.get("turn_secs"), 0) or 0
    burst_tps = num(state.get("burst_tps"))
    burst_gen = num(state.get("burst_gen"))
    for line in data.decode("utf-8", "replace").splitlines():
        ev = extract_event(line)
        if not ev:
            continue
        typ, tok, ss, ts, text = ev
        last_ss = ss
        last_tok = tok
        if typ not in ("agent_thought_chunk", "agent_message_chunk"):
            continue
        if started_ms is not None and ss < started_ms:
            continue
        if cur_ss is not None and ss != cur_ss:
            turn_gen, turn_secs, burst_tps, burst_gen = commit_stream(
                turn_gen, turn_secs, burst_tps, burst_gen,
                cur_thought_tok, cur_message_tok, cur_ss, cur_ts,
            )
            cur_thought_tok = 0
            cur_message_tok = 0
        cur_ss = ss
        if ts:
            cur_ts = ts
        n = est_tokens(text)
        if n > 0:
            if typ == "agent_thought_chunk":
                cur_thought_tok = n
            else:
                cur_message_tok = n
    live_gen = cur_thought_tok + cur_message_tok
    live_elapsed = (cur_ts - cur_ss) / 1000.0 if cur_ss and cur_ts else 0
    live_tps = rate_if(live_gen, live_elapsed)
    if live_tps and (live_gen >= 48 or not burst_tps):
        burst_tps = live_tps
        burst_gen = live_gen
    state["ss"] = last_ss
    state["tok"] = last_tok
    state["cur_ss"] = cur_ss
    state["cur_ts"] = cur_ts
    state["cur_thought_tok"] = cur_thought_tok
    state["cur_message_tok"] = cur_message_tok
    state["turn_gen"] = turn_gen
    state["turn_secs"] = turn_secs
    state["live_gen"] = live_gen
    if live_tps:
        state["live_tps"] = live_tps
    else:
        state.pop("live_tps", None)
    if burst_tps:
        state["burst_tps"] = burst_tps
        state["burst_gen"] = burst_gen
    return state


def hit_pct(cache, inp):
    if not inp or inp <= 0 or cache is None:
        return None
    return max(0.0, min(100.0, 100.0 * cache / inp))


def dash(v, color=C_NUM):
    if v is None or v == "":
        return f"{DIM}-{RST}"
    return f"{color}{v}{RST}"


def pair(label, value, color=C_NUM):
    return f"{DIM}{label}{RST} {dash(value, color)}"


def last_turn_from_events(transcript):
    if not transcript:
        return None
    path = os.path.join(os.path.dirname(transcript), "events.jsonl")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 65536))
            if f.tell() > 0:
                f.readline()
            data = f.read().decode("utf-8", "replace")
    except OSError:
        return None
    n = None
    for line in data.splitlines():
        if '"turn_started"' not in line:
            continue
        try:
            o = json.loads(line)
        except Exception:
            continue
        if o.get("type") == "turn_started" and o.get("turn_number") is not None:
            n = int(o["turn_number"]) + 1
    return n


def turn_count(usage, in_turn, transcript=None):
    n = 0
    if isinstance(usage, dict):
        n = int(num(nest(usage, "session", "turnCount"), 0) or 0)
        if n:
            return n + 1 if in_turn else n
    if transcript:
        summary = load_json(os.path.join(os.path.dirname(transcript), "summary.json"))
        nxt = num(nest(summary, "next_trace_turn") if summary else None)
        if nxt:
            return int(nxt)
    ev = last_turn_from_events(transcript)
    if ev:
        return ev
    return 1 if in_turn else None


def usage_snap(inp, out, cache, cost, api_ms):
    return {
        "inp": inp,
        "out": out,
        "cache": cache,
        "cost": cost if cost is not None else 0,
        "api_ms": api_ms,
    }


def reset_turn_stream(state):
    state.pop("burst_tps", None)
    state.pop("burst_gen", None)
    state.pop("live_tps", None)
    state.pop("live_gen", None)
    state.pop("cur_ss", None)
    state.pop("cur_ts", None)
    state["cur_thought_tok"] = 0
    state["cur_message_tok"] = 0
    state["turn_gen"] = 0
    state["turn_secs"] = 0


def main():
    raw = sys.stdin.read()
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        data = {}

    sid = data.get("session_id")
    prompt_id = data.get("prompt_id")
    started_ms = num(nest(data, "turn", "started_at_ms"))
    in_turn = bool(prompt_id or started_ms)
    cwd = nest(data, "workspace", "current_dir") or data.get("cwd") or os.getcwd()
    branch = nest(data, "workspace", "branch")
    model = nest(data, "model", "display_name") or nest(data, "model", "id") or "grok"
    pct = nest(data, "context_window", "used_percentage")
    usage_blk = nest(data, "context_window", "session_usage") or {}
    inp = num(usage_blk.get("input_tokens"), num(nest(data, "context_window", "session_input_tokens"), 0)) or 0
    out = num(usage_blk.get("output_tokens"), num(nest(data, "context_window", "session_output_tokens"), 0)) or 0
    cache = num(usage_blk.get("cache_read_input_tokens"), 0) or 0
    cost = num(nest(data, "cost", "total_cost_usd"))
    api_ms = num(nest(data, "cost", "total_api_duration_ms"), 0) or 0
    transcript = data.get("transcript_path")

    state = load_state(sid)
    if state.get("prompt_id") != prompt_id:
        if in_turn:
            reset_turn_stream(state)
            state["snap"] = usage_snap(inp, out, cache, cost, api_ms)
            if started_ms:
                state["turn_started_ms"] = started_ms
        state["prompt_id"] = prompt_id

    bound_ms = started_ms or num(state.get("turn_started_ms"))
    if transcript:
        state = ingest_transcript(transcript, state, bound_ms)

    snap = state.get("snap") if isinstance(state.get("snap"), dict) else None
    if in_turn and snap is None:
        snap = usage_snap(inp, out, cache, cost, api_ms)
        state["snap"] = snap

    d_in = max(0.0, inp - (snap.get("inp") or 0)) if snap else 0
    d_out = max(0.0, out - (snap.get("out") or 0)) if snap else 0
    d_cache = max(0.0, cache - (snap.get("cache") or 0)) if snap else 0
    d_cost = None
    if snap is not None and cost is not None:
        d_cost = max(0.0, cost - (snap.get("cost") or 0))
    d_api = max(0.0, api_ms - (snap.get("api_ms") or 0)) if snap else 0

    sess_hit = hit_pct(cache, inp)
    turn_hit = hit_pct(d_cache, d_in) if in_turn and d_in > 0 else None
    sess_tok = inp + out if (inp or out) else None
    turn_tok = (d_in + d_out) if in_turn and (d_in > 0 or d_out > 0) else None

    live_tps = num(state.get("live_tps"))
    burst_tps = num(state.get("burst_tps"))
    live_gen = num(state.get("live_gen"), 0) or 0
    tg = num(state.get("turn_gen"), 0) or 0
    tsec = num(state.get("turn_secs"), 0) or 0
    live_elapsed = 0.0
    cur_ss = num(state.get("cur_ss"))
    cur_ts = num(state.get("cur_ts"))
    if cur_ss and cur_ts:
        live_elapsed = max(0.0, (cur_ts - cur_ss) / 1000.0)
    avg_stream = rate_if(tg + live_gen, tsec + live_elapsed)
    usage_tps = rate_if(d_out, d_api / 1000.0) if d_api >= 200 else None
    tps = live_tps or burst_tps or avg_stream or usage_tps
    if tps:
        state["last_tps"] = tps
    else:
        tps = num(state.get("last_tps"))

    live_out = None
    stream_out = tg + live_gen
    if in_turn:
        live_out = stream_out if stream_out > 0 else (d_out if d_out > 0 else None)
    live_cache = d_cache if in_turn and d_cache > 0 else None
    if in_turn and not turn_tok and stream_out > 0:
        turn_tok = stream_out

    usage_file = None
    if transcript:
        usage_file = load_json(os.path.join(os.path.dirname(transcript), "usage.json"))
    if cost is None and usage_file:
        ticks = num(nest(usage_file, "session", "costUsdTicks"))
        if ticks is not None:
            cost = ticks / 1e9
            if snap and snap.get("cost") is None:
                d_cost = None
            elif snap and snap.get("cost") is not None:
                d_cost = max(0.0, cost - (snap.get("cost") or 0))
    rounds = turn_count(usage_file, in_turn, transcript)

    save_state(sid, {k: state[k] for k in STATE_KEYS if k in state})

    items = [
        ("model", f"{C_MODEL}● {model}{RST}"),
        ("dir", f"{C_DIR}📁 {short_dir(cwd)}{RST}"),
    ]
    if branch:
        items.append(("br", f"{C_BR}🔀 {branch}{RST}"))
    items.extend([
        ("hit", pair("本次命中", fmt_pct(turn_hit), hit_color(turn_hit))),
        ("avg_hit", pair("平均命中", fmt_pct(sess_hit), hit_color(sess_hit))),
        ("sess_tok", pair("会话 tokens", fmt_int(sess_tok))),
        ("turn_tok", pair("本次 tokens", fmt_int(turn_tok) if in_turn else None)),
        ("tps", pair("吞吐速度", fmt_tps(tps), C_TPS)),
        ("out", pair("输出", fmt_int(live_out) if in_turn else None)),
        ("cache", pair("缓存", fmt_int(live_cache) if in_turn else None)),
        ("cost", pair("本次费用", fmt_usd(d_cost if in_turn else cost), C_COST)),
        ("rounds", pair("当前会话", f"{int(rounds)} 轮" if rounds else None)),
        ("ctx", pair("上下文", f"{int(pct)}%" if pct is not None else None, ctx_color(pct))),
    ])
    drop = ["cache", "hit", "out", "cost", "turn_tok", "rounds", "avg_hit", "sess_tok", "dir"]
    cols = int(os.environ.get("COLUMNS") or 240)
    bits = [t for _, t in items]
    line = SEP.join(bits)
    while vislen(line) > max(cols, 40) and drop:
        key = drop.pop(0)
        items = [x for x in items if x[0] != key]
        bits = [t for _, t in items]
        line = SEP.join(bits)
    sys.stdout.write(line + "\n")


if __name__ == "__main__":
    main()
