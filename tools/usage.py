#!/usr/bin/env python3
"""
opencode-usage — 查看每次对话的 token 使用统计。

数据来源：~/.local/share/opencode/opencode.db (opencode 自动记录的 usage)

用法:
  python3 tools/usage.py                 # 当前最新 session
  python3 tools/usage.py --list          # 列出最近 N 个 session
  python3 tools/usage.py --session <id>  # 指定 session (前缀即可)
  python3 tools/usage.py --msg           # 显示当前 session 每条消息明细
  python3 tools/usage.py --json          # JSON 输出 (可被脚本消费)
  python3 tools/usage.py --day           # 今天所有 session 消耗汇总
  python3 tools/usage.py --day 2026-09-07  # 指定日期汇总
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime

DB = os.path.expanduser("~/.local/share/opencode/opencode.db")

SESS_COLS = [
    "tokens_input", "tokens_output", "tokens_reasoning",
    "tokens_cache_read", "tokens_cache_write", "cost",
]


def conn():
    if not os.path.exists(DB):
        sys.exit(f"DB not found: {DB}")
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def fmt_time(ms):
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")


def list_sessions(c, n):
    rows = c.execute(
        """SELECT id, title, directory, model, agent,
                  tokens_input, tokens_output, tokens_reasoning,
                  tokens_cache_read, tokens_cache_write, cost,
                  time_created
           FROM session
           WHERE project_id IS NOT NULL
           ORDER BY time_created DESC LIMIT ?""", (n,)
    ).fetchall()
    return rows


def get_session(c, sid):
    return c.execute(
        """SELECT * FROM session WHERE id LIKE ? ORDER BY time_created DESC LIMIT 1""",
        (sid + "%",)
    ).fetchone()


def get_messages(c, sid):
    return c.execute(
        """SELECT data FROM message
           WHERE session_id = ?
           ORDER BY time_created ASC""", (sid,)
    ).fetchall()


def parse_msg_tokens(data):
    try:
        d = json.loads(data)
    except Exception:
        return None
    t = d.get("tokens") or {}
    if not any(t.get(k) for k in ("input", "output", "total")):
        return None
    return {
        "role": d.get("role"),
        "input": t.get("input", 0),
        "output": t.get("output", 0),
        "total": t.get("total", 0),
        "cache_read": (t.get("cache") or {}).get("read", 0),
        "cache_write": (t.get("cache") or {}).get("write", 0),
        "reasoning": t.get("reasoning", 0),
    }


def print_session(s, verbose_messages=False, c=None):
    title = s["title"] or "(untitled)"
    print("=" * 60)
    print(f"Session : {s['id']}")
    print(f"Title   : {title}")
    print(f"Created : {fmt_time(s['time_created'])}")
    print(f"Model   : {s['model']}  Agent: {s['agent']}")
    print(f"Dir     : {s['directory']}")
    print("-" * 60)
    print(f"Input      : {s['tokens_input']:>10,} tokens")
    print(f"Output     : {s['tokens_output']:>10,} tokens")
    print(f"Reasoning  : {s['tokens_reasoning']:>10,} tokens")
    print(f"Cache read : {s['tokens_cache_read']:>10,} tokens")
    print(f"Cache write: {s['tokens_cache_write']:>10,} tokens")
    tot = (s["tokens_input"] or 0) + (s["tokens_output"] or 0)
    print(f"Total      : {tot:>10,} tokens")
    print(f"Cost       : ${s['cost'] or 0:.4f}")

    if verbose_messages and c:
        print("-" * 60)
        print(f"{'Role':<10}{'Input':>10}{'Output':>10}{'Reason':>9}{'CacheR':>10}")
        print("-" * 60)
        for m in get_messages(c, s["id"]):
            t = parse_msg_tokens(m["data"])
            if not t:
                continue
            print(f"{t['role']:<10}{t['input']:>10,}{t['output']:>10,}"
                  f"{t['reasoning']:>9,}{t['cache_read']:>10,}")
    return {
        "session_id": s["id"],
        "title": title,
        "input": s["tokens_input"],
        "output": s["tokens_output"],
        "reasoning": s["tokens_reasoning"],
        "cache_read": s["tokens_cache_read"],
        "cache_write": s["tokens_cache_write"],
        "cost": s["cost"],
    }


def caveman_estimate(output_tokens):
    """Estimate tokens saved by caveman mode.

    Honest caveat: caveman savings cannot be measured exactly — there is no
    control run of "what the model WOULD have said without caveman". The
    caveman skill claims a typical 65% output reduction (full mode). We use
    that as a heuristic to produce an estimated range.

    Returns (saved_low, saved_high, original_est) tokens.
    """
    # claim: output_with_caveman = output_without * (1 - reduction)
    # reduction claimed ~0.65 -> without ~ output / 0.35
    original = output_tokens / 0.35
    return int(original * 0.55), int(original * 0.70), int(original)


def day_usage(c, daystr):
    """Aggregate token usage for a given date (YYYY-MM-DD, default today)."""
    day = datetime.strptime(daystr, "%Y-%m-%d")
    start = int(day.timestamp() * 1000)
    end = start + 86400000
    rows = c.execute(
        """SELECT tokens_input, tokens_output, tokens_reasoning,
                  tokens_cache_read, tokens_cache_write, cost
           FROM session
           WHERE project_id IS NOT NULL
             AND time_created >= ? AND time_created < ?""",
        (start, end),
    ).fetchall()
    agg = {"input": 0, "output": 0, "reasoning": 0,
           "cache_read": 0, "cache_write": 0, "cost": 0.0, "sessions": len(rows)}
    for r in rows:
        agg["input"] += r["tokens_input"] or 0
        agg["output"] += r["tokens_output"] or 0
        agg["reasoning"] += r["tokens_reasoning"] or 0
        agg["cache_read"] += r["tokens_cache_read"] or 0
        agg["cache_write"] += r["tokens_cache_write"] or 0
        agg["cost"] += r["cost"] or 0
    return agg


def main():
    ap = argparse.ArgumentParser(description="opencode token usage")
    ap.add_argument("--list", action="store_true", help="list recent sessions")
    ap.add_argument("-n", type=int, default=10, help="sessions to list")
    ap.add_argument("--session", "-s", type=str, help="session id (prefix ok)")
    ap.add_argument("--msg", action="store_true", help="show per-message detail")
    ap.add_argument("--json", action="store_true", help="JSON output")
    ap.add_argument("--caveman", action="store_true",
                    help="estimate caveman-mode token savings (ESTIMATE)")
    ap.add_argument("--day", nargs="?", const="today", default=None,
                    help="aggregate usage for a date (YYYY-MM-DD), default today")
    args = ap.parse_args()

    c = conn()

    if args.day:
        day = args.day
        if day == "today":
            day = datetime.now().strftime("%Y-%m-%d")
        a = day_usage(c, day)
        print("=" * 60)
        print(f"Date    : {day}")
        print(f"Sessions: {a['sessions']}")
        print("-" * 60)
        print(f"Input      : {a['input']:>10,} tokens")
        print(f"Output     : {a['output']:>10,} tokens")
        print(f"Reasoning  : {a['reasoning']:>10,} tokens")
        print(f"Cache read : {a['cache_read']:>10,} tokens")
        print(f"Cache write: {a['cache_write']:>10,} tokens")
        print(f"Total      : {a['input'] + a['output']:>10,} tokens")
        print(f"Cost       : ${a['cost']:.4f}")
        if args.json:
            print(json.dumps({**a, "date": day}, ensure_ascii=False, indent=2))
        return

    if args.list:
        rows = list_sessions(c, args.n)
        print(f"{'session_id':<30}{'created':<18}{'input':>10}{'output':>10}{'title':<25}")
        print("-" * 100)
        for r in rows:
            print(f"{r['id']:<30}{fmt_time(r['time_created']):<18}"
                  f"{r['tokens_input'] or 0:>10,}{r['tokens_output'] or 0:>10,}"
                  f"{(r['title'] or '')[:24]:<25}")
        return

    if args.session:
        s = get_session(c, args.session)
        if not s:
            sys.exit(f"session not found: {args.session}")
    else:
        s = c.execute(
            """SELECT * FROM session WHERE project_id IS NOT NULL
               ORDER BY time_created DESC LIMIT 1"""
        ).fetchone()

    # cache read/write may be null for older sessions
    s = dict(s)
    for k in SESS_COLS:
        if k not in s or s[k] is None:
            s[k] = 0

    result = print_session(s, verbose_messages=args.msg, c=c)
    if args.caveman:
        lo, hi, orig = caveman_estimate(s["tokens_output"] or 0)
        print("-" * 60)
        print("Caveman 节省 (估算 — 无对照组无法精确测量)")
        print(f"  若无 caveman 估算输出 : {orig:>10,} tokens")
        print(f"  节省区间 (55%-70%)   : {lo:>10,} ~ {hi:>10,} tokens")
        result["caveman"] = {
            "note": "estimate, no control group",
            "original_output_est": orig,
            "saved_low": lo,
            "saved_high": hi,
        }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
