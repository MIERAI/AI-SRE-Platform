"""Checkpointer 的另外三个用途：崩溃恢复 / time-travel / 多轮会话。

重点是用 time-travel 结掉 Phase 1 留下的悬案：
  「temperature=0 下 Agent 行为不可复现，同一输入工具调用数在 3 和 6 之间跳」

以前查不了，因为没法把状态精确还原到分叉点。有了 checkpoint 就能：
从【完全相同的 checkpoint】重放 N 次，只跑一个 agent 节点，看模型的决策是否稳定。

  若决策变化  -> 模型服务本身在 temperature=0 下不确定（GPU 归约顺序等）
  若决策恒定  -> Phase 1 观察到的差异来自更早的路径分叉，不是单点随机

    uv run agent/timetravel.py --mode history      # 看 checkpoint 历史
    uv run agent/timetravel.py --mode replay -n 5  # 同一 checkpoint 重放 N 次
    uv run agent/timetravel.py --mode crash        # 崩溃恢复
    uv run agent/timetravel.py --mode multiturn    # 多轮会话
"""

import argparse
import json
import sys
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

sys.path.insert(0, str(Path(__file__).parent))
from graph_agent import SCENARIOS, build  # noqa: E402
from loop import SYSTEM  # noqa: E402
from tools.cluster import CALL_LOG, reset  # noqa: E402

DB = Path(__file__).parent / "out_checkpoints.sqlite"


def initial(question: str) -> dict:
    return {"messages": [{"role": "system", "content": SYSTEM},
                          {"role": "user", "content": question}], "decisions": {}}


def describe(msg: dict) -> str:
    if calls := msg.get("tool_calls"):
        return "调用 " + ", ".join(
            f"{c['function']['name']}({json.dumps(c['function'].get('arguments') or {}, ensure_ascii=False)})"
            for c in calls)
    if msg.get("role") == "tool":
        return f"[工具返回 {msg.get('tool_name')}] {(msg.get('content') or '')[:50]}…"
    return f"[{msg.get('role')}] {(msg.get('content') or '')[:60]}…"


# ── 模式 1：checkpoint 历史 ────────────────────────────────────────────────

def mode_history(app, cfg, question):
    reset()
    app.invoke(initial(question), cfg)
    hist = list(app.get_state_history(cfg))
    print(f"共 {len(hist)} 个 checkpoint（逆序，最新在前）\n")
    print(f"{'step':>5}  {'即将执行':<14}{'消息数':>6}  最后一条消息")
    print("-" * 100)
    for h in hist:
        msgs = h.values.get("messages") or []
        last = describe(msgs[-1]) if msgs else "—"
        nxt = ",".join(h.next) if h.next else "(结束)"
        print(f"{h.metadata['step']:>5}  {nxt:<14}{len(msgs):>6}  {last[:64]}")
    return hist


# ── 模式 2：从同一 checkpoint 重放 N 次 ───────────────────────────────────

def mode_replay(app, cfg, question, n):
    reset()
    app.invoke(initial(question), cfg)
    hist = list(app.get_state_history(cfg))

    # 找决策点：即将执行 agent，且上文里已经有工具返回（也就是模型要决定「还查不查」）
    cands = [h for h in reversed(hist)
             if h.next == ("agent",)
             and any(m.get("role") == "tool" for m in (h.values.get("messages") or []))]
    if not cands:
        print("没找到合适的决策点")
        return
    target = cands[0]
    msgs = target.values["messages"]
    print(f"决策点：step={target.metadata['step']}，上文 {len(msgs)} 条消息")
    print(f"最后一条：{describe(msgs[-1])[:90]}")
    print(f"\n从这个【完全相同】的 checkpoint 重放 {n} 次，每次只跑一个 agent 节点：\n")

    outcomes = []
    for i in range(1, n + 1):
        got = None
        for chunk in app.stream(None, target.config, stream_mode="updates"):
            if "agent" in chunk:
                got = chunk["agent"]["messages"][0]
                break
        outcomes.append(describe(got) if got else "(无输出)")
        print(f"  第 {i} 次  {outcomes[-1][:88]}")

    uniq = set(outcomes)
    print(f"\n不同结果数：{len(uniq)}")
    if len(uniq) == 1:
        print("→ 同一 checkpoint 下模型决策【恒定】。Phase 1 观察到的 3 vs 6 次差异"
              "\n  不是单点随机，而是更早的路径就分叉了。")
    else:
        print("→ 同一 checkpoint 下模型决策【会变】。temperature=0 也不保证确定性"
              "\n  （GPU 浮点归约顺序、batching 等），Agent 行为天然不可复现。")


# ── 模式 3：崩溃恢复 ──────────────────────────────────────────────────────

def mode_crash(app, cfg, question):
    reset()
    print("第一阶段：跑到第 3 个 superstep 就【模拟崩溃】（直接 break 出循环，不再往下跑）\n")
    steps = 0
    for chunk in app.stream(initial(question), cfg, stream_mode="updates"):
        node = next(iter(chunk))
        steps += 1
        print(f"  superstep {steps}: {node}")
        if steps >= 3:
            print("  💥 进程在这里挂掉")
            break
    snap = app.get_state(cfg)
    pending = [(c["function"]["name"], c["function"].get("arguments") or {})
               for c in (snap.values["messages"][-1].get("tool_calls") or [])]
    before = list(CALL_LOG)
    print(f"\n崩溃时的持久化状态：消息 {len(snap.values['messages'])} 条，"
          f"下一步该执行 {snap.next}")
    print(f"  崩溃前【已执行】的工具 : {[ (n, kw) for n, kw in before ]}")
    print(f"  崩溃时【待执行】的工具 : {pending}   ← 这批还没跑，恢复后应当由 execute 执行")

    print("\n第二阶段：新建一个 app 对象（模拟进程重启），只给 thread_id，从断点继续\n")
    with SqliteSaver.from_conn_string(str(DB)) as saver2:
        app2 = build(saver2)
        r = app2.invoke(None, cfg)          # 注意输入是 None —— 状态全从 checkpoint 来
    after = CALL_LOG[len(before):]
    print(f"  恢复后跑完，消息共 {len(r['messages'])} 条")
    print(f"  恢复后执行的工具 : {[(n, kw) for n, kw in after]}")

    # 正确的判定：恢复后【第一批】执行的，应当恰好等于崩溃时待执行的那批，
    # 且不得重复执行崩溃前已完成的调用。
    replayed = after[:len(pending)]
    ok_pending = [(n, kw) for n, kw in replayed] == pending
    dup = [x for x in replayed if x in before]
    print()
    print(f"  恢复后第一批 == 崩溃时待执行的那批 ? {'✅ 是' if ok_pending else '❌ 否'}")
    print(f"  是否重复执行了崩溃前已完成的调用 ? "
          f"{'✅ 没有' if not dup else f'❌ 重复了 {dup}'}")
    later = after[len(pending):]
    if later:
        print(f"  之后模型又自主调用了 {len(later)} 次：{[n for n, _ in later]}"
              f"\n    （若其中出现与崩溃前相同的调用，那是模型自己又要了一遍，"
              f"不是 checkpoint 重放）")
    print(f"\n【最终答案】\n{(r['messages'][-1].get('content') or '')[:400]}")


# ── 模式 4：多轮会话 ──────────────────────────────────────────────────────

def mode_multiturn(app, cfg, question):
    reset()
    print("第 1 轮：" + question)
    r1 = app.invoke(initial(question), cfg)
    print(f"→ {(r1['messages'][-1].get('content') or '')[:200]}…\n")

    follow = "你刚才排查的是哪个 namespace 的什么问题？一句话回答，不要再调用工具。"
    print("第 2 轮（同一 thread_id，不重发 system/历史）：" + follow)
    r2 = app.invoke({"messages": [{"role": "user", "content": follow}], "decisions": {}}, cfg)
    print(f"→ {(r2['messages'][-1].get('content') or '')[:200]}")
    print(f"\n消息数 {len(r1['messages'])} → {len(r2['messages'])}，"
          f"历史由 checkpointer 承载，调用方只发了一句话。")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", default="replay",
                   choices=["history", "replay", "crash", "multiturn"])
    p.add_argument("--scenario", default="w2", choices=list(SCENARIOS))
    p.add_argument("-n", type=int, default=5)
    args = p.parse_args()

    DB.unlink(missing_ok=True)
    question = SCENARIOS[args.scenario]
    with SqliteSaver.from_conn_string(str(DB)) as saver:
        app = build(saver)
        cfg = {"configurable": {"thread_id": f"tt-{args.mode}"}}
        print("=" * 100)
        print(f"模式 {args.mode} · 场景 {args.scenario}")
        print("=" * 100)
        if args.mode == "history":
            mode_history(app, cfg, question)
        elif args.mode == "replay":
            mode_replay(app, cfg, question, args.n)
        elif args.mode == "crash":
            mode_crash(app, cfg, question)
        else:
            mode_multiturn(app, cfg, question)


if __name__ == "__main__":
    main()
