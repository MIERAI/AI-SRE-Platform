"""LLM-as-judge 的可靠性：噪声底与三种已知偏置。

**为什么这是 Phase 4 的第一步而不是直接跑 Ragas。**

Ragas / DeepEval 的绝大多数指标底层都是 LLM-as-judge。
如果裁判本身不稳、有系统性偏置，那么所有下游指标都继承它 ——
你拿到的漂亮数字只是把噪声换了个更权威的包装。

前三个阶段已经反复撞到这类问题：
  Phase 1  同配置重复三次，噪声 ±2/20，差点把噪声当信号
  Phase 2  模型加载状态改变输出（冷 3/3 vs 热 3/3 给出不同的确定性答案）
  Phase 3  分类型子集只有 3 条，一条查询 = 33 个百分点

所以这里先量四件事：
  ① 噪声底      同一输入重复 N 次，temperature=0，分数会变吗
  ② 位置偏置    A/B 对调顺序，胜者会变吗
  ③ 冗长偏置    同样的事实内容，写长一点分数会变吗
  ④ 自我偏好    模型会不会偏袒自己生成的答案

全程固定 keep_alive 并预热 —— 这是 Phase 2 那条结论的直接应用。

    uv run evaluation/judge_reliability.py --all
    uv run evaluation/judge_reliability.py --noise -n 12
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.request

OLLAMA = "http://localhost:11434/api/chat"
MODEL = "qwen3:14b"

SCORE_SCHEMA = {"type": "object",
                "properties": {"score": {"type": "integer"}},
                "required": ["score"], "additionalProperties": False}
CHOICE_SCHEMA = {"type": "object",
                 "properties": {"winner": {"type": "string", "enum": ["A", "B", "tie"]}},
                 "required": ["winner"], "additionalProperties": False}

# ── 取材于本仓库真实数据的固定夹具 ────────────────────────────────────────

CONTEXT = """# KubePodCrashLooping

## Meaning
Pod is in CrashLoop which means the app dies or is unresponsive and
kubernetes tries to restart it automatically.

## Diagnosis
- Check template via `kubectl -n $NAMESPACE get pod $POD`.
- Check pod events via `kubectl -n $NAMESPACE describe pod $POD`.
- Check pod logs via `kubectl -n $NAMESPACE logs $POD -c $CONTAINER`
"""

QUESTION = "Pod 一直 CrashLoopBackOff，应该怎么排查？"

# 忠实于上下文的回答
ANSWER_FAITHFUL = ("按 runbook：先 kubectl get pod 看模板，再 kubectl describe pod 看事件，"
                   "最后 kubectl logs 看容器日志。")
# 含幻觉的回答（上下文里没有 'kubectl top' 也没有 'OOM 一定是内存不足' 这个断言）
ANSWER_HALLUCINATED = ("先用 kubectl top pod 看内存曲线，CrashLoop 一定是内存不足导致的 OOM，"
                       "直接把 limits.memory 翻倍即可解决。")
# 与 FAITHFUL 事实等价，但写得冗长（用于冗长偏置）
ANSWER_VERBOSE = (
    "针对该问题，我们建议采用一套系统化的、分阶段推进的排查方法论。"
    "首先，第一阶段应当着眼于工作负载定义本身，通过执行 kubectl get pod 命令，"
    "全面获取该 Pod 的模板配置信息，以便确认其声明是否符合预期。"
    "其次，第二阶段需要转向事件层面的分析，借助 kubectl describe pod 命令，"
    "系统性地审阅 Kubernetes 控制平面记录的相关事件序列。"
    "最后，在第三阶段，应当深入到应用运行时层面，通过 kubectl logs 命令提取容器日志，"
    "从而定位应用自身抛出的具体异常信息。上述三个阶段构成一个完整的排查闭环。")


def call(messages, schema, timeout=600):
    payload = {"model": MODEL, "stream": False, "think": False, "keep_alive": "30m",
               "options": {"temperature": 0, "num_predict": 24},
               "format": schema, "messages": messages}
    req = urllib.request.Request(OLLAMA, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(json.load(r)["message"]["content"])


def judge_faithfulness(context: str, question: str, answer: str) -> int:
    return int(call([
        {"role": "system", "content":
         "你是回答质量评审。判断【回答】是否忠实于【上下文】—— "
         "只依据上下文里出现过的信息，不引入外部知识。"
         "输出 0-10 的整数：10=完全忠实，0=大量内容上下文里没有。只输出 JSON。"},
        {"role": "user", "content":
         f"上下文：\n{context}\n\n问题：{question}\n\n回答：{answer}"}],
        SCORE_SCHEMA)["score"])


def judge_pair(context: str, question: str, a: str, b: str) -> str:
    return call([
        {"role": "system", "content":
         "你是回答质量评审。比较 A、B 两个回答，选出更好的一个。"
         "评判依据：是否忠实于上下文、是否准确、是否可操作。"
         "只输出 JSON，winner 取值 A / B / tie。"},
        {"role": "user", "content":
         f"上下文：\n{context}\n\n问题：{question}\n\n"
         f"回答 A：\n{a}\n\n回答 B：\n{b}"}], CHOICE_SCHEMA)["winner"]


def warmup():
    call([{"role": "user", "content": "ok"}], SCORE_SCHEMA)


# ── 实验 ──────────────────────────────────────────────────────────────────

def exp_noise(n: int):
    print(f"① 噪声底：同一输入重复 {n} 次，temperature=0\n")
    print(f"{'夹具':<16}{'各次分数':<44}{'不同取值':>10}{'极差':>7}{'标准差':>9}")
    print("-" * 90)
    results: list[int] = []
    for name, ans in (("忠实回答", ANSWER_FAITHFUL), ("含幻觉回答", ANSWER_HALLUCINATED)):
        scores = [judge_faithfulness(CONTEXT, QUESTION, ans) for _ in range(n)]
        uniq = sorted(set(scores))
        print(f"{name:<16}{str(scores):<44}{len(uniq):>10}{max(scores)-min(scores):>7}"
              f"{statistics.pstdev(scores):>9.2f}")
        results.append(len(uniq))
    if all(u == 1 for u in results):
        print("\n同一会话内、固定加载状态下，裁判是【确定性】的（σ=0）。")
        print("但这不等于「评测可复现」—— Phase 2 实测过：**模型重新加载会改变输出**")
        print("（冷启动 3/3 与热缓存 3/3 给出不同的确定性答案）。")
        print("可操作的规矩：**评测必须一口气跑完，中途不要重启 ollama / 不要让模型被换出。**")
    else:
        print("\n⚠️ temperature=0 下同一输入仍得到不同分数 —— 这是所有下游指标的噪声下限。")


def exp_position(n: int):
    print(f"\n② 位置偏置：同一对回答，交换 A/B 顺序各跑 {n} 次\n")
    good, bad = ANSWER_FAITHFUL, ANSWER_HALLUCINATED
    fwd = [judge_pair(CONTEXT, QUESTION, good, bad) for _ in range(n)]   # 好的在 A
    rev = [judge_pair(CONTEXT, QUESTION, bad, good) for _ in range(n)]   # 好的在 B
    fwd_ok = sum(1 for w in fwd if w == "A")
    rev_ok = sum(1 for w in rev if w == "B")
    print(f"  好回答放 A 位：判它赢 {fwd_ok}/{n}   逐次 {fwd}")
    print(f"  好回答放 B 位：判它赢 {rev_ok}/{n}   逐次 {rev}")
    print(f"\n  一致率（两种摆法都选中同一个回答）：{min(fwd_ok, rev_ok)}/{n}")
    if fwd_ok != rev_ok:
        print("  ⚠️ 换个位置结论就变 —— 存在位置偏置，成对比较必须双向跑再取交集。")
    else:
        print("  本夹具上未观察到位置偏置（不代表不存在，换更接近的一对可能出现）。")


def exp_verbosity(n: int):
    print(f"\n③ 冗长偏置：事实内容等价，一简一繁，各判 {n} 次\n")
    s_short = [judge_faithfulness(CONTEXT, QUESTION, ANSWER_FAITHFUL) for _ in range(n)]
    s_long = [judge_faithfulness(CONTEXT, QUESTION, ANSWER_VERBOSE) for _ in range(n)]
    print(f"  简洁版（{len(ANSWER_FAITHFUL)} 字）  分数 {s_short}  均值 {statistics.mean(s_short):.2f}")
    print(f"  冗长版（{len(ANSWER_VERBOSE)} 字）  分数 {s_long}  均值 {statistics.mean(s_long):.2f}")
    d = statistics.mean(s_long) - statistics.mean(s_short)
    print(f"\n  绝对打分差值 {d:+.2f} —— 两者的事实内容完全一样"
          f"（都是 get pod / describe / logs 三步）。")

    n_pair = min(n, 6)
    pair = [judge_pair(CONTEXT, QUESTION, ANSWER_FAITHFUL, ANSWER_VERBOSE) for _ in range(n_pair)]
    n_long = sum(1 for w in pair if w == "B")
    print(f"  成对比较（A=简洁 B=冗长）：{pair}   选冗长版 {n_long}/{n_pair}")

    saturated = len(set(s_short) | set(s_long)) == 1
    print()
    if saturated:
        print("  ⚠️ **绝对打分出现天花板效应** —— 两者都拿满分，该指标在这个区间分辨力为零，")
        print("     偏置被【藏住】了。")
    if n_long >= n_pair * 0.8:
        print("  ⚠️ **成对比较里存在明显的冗长偏置** —— 事实内容相同，仅长度不同，"
              f"却 {n_long}/{n_pair} 判冗长版更好。")
    elif n_long <= n_pair * 0.2:
        print("  ⚠️ 成对比较偏向简洁版（反向偏置）。")
    else:
        print("  成对比较未显示明显方向性偏好。")
    print("\n  结论：**绝对打分与成对比较暴露的偏置不同**。前者易饱和从而掩盖偏置，"
          "\n  后者强制选择从而显形。选哪种评测协议本身就是一个会改变结论的决定。")


# ── 质量接近的一对（用于位置偏置的严肃版本）──────────────────────────────
# 两个回答【都忠实、都完整】，三个步骤一样，只是【顺序不同】。
# 上一版位置偏置实验用的是「忠实 vs 含幻觉」，差距太大，任何裁判都不会摇摆 ——
# 那个 6/6 一致只说明夹具太容易，不能得出「没有位置偏置」的结论。
ANSWER_ORDER_A = ("按 runbook 三步：先 kubectl get pod 看模板，"
                  "再 kubectl describe pod 看事件，最后 kubectl logs 看容器日志。")
ANSWER_ORDER_B = ("按 runbook 三步：先 kubectl logs 看容器日志，"
                  "再 kubectl describe pod 看事件，最后 kubectl get pod 看模板。")


def exp_position_close(n: int):
    print(f"\n④ 位置偏置【严肃版】：两个质量接近的回答，交换 A/B 各跑 {n} 次\n")
    print("  两个回答都忠实、都覆盖同样三个命令，只是顺序不同 —— 裁判本应近乎无差别。\n")
    fwd = [judge_pair(CONTEXT, QUESTION, ANSWER_ORDER_A, ANSWER_ORDER_B) for _ in range(n)]
    rev = [judge_pair(CONTEXT, QUESTION, ANSWER_ORDER_B, ANSWER_ORDER_A) for _ in range(n)]
    print(f"  A位=顺序A B位=顺序B ：{fwd}")
    print(f"  A位=顺序B B位=顺序A ：{rev}")

    # 一致 = 两种摆法都选中【同一个回答内容】
    consistent = sum(1 for f, r in zip(fwd, rev)
                     if (f == "A" and r == "B") or (f == "B" and r == "A")
                     or (f == "tie" and r == "tie"))
    pick_a_pos = sum(1 for w in fwd + rev if w == "A")
    total = 2 * n
    print(f"\n  内容一致率：{consistent}/{n}")
    print(f"  选 A【位置】的比例：{pick_a_pos}/{total} = {pick_a_pos/total:.0%}"
          f"（无位置偏置时应接近 50%）")
    if pick_a_pos >= total * 0.8 or pick_a_pos <= total * 0.2:
        side = "A" if pick_a_pos > total / 2 else "B"
        print(f"  ⚠️ **存在位置偏置** —— 裁判显著偏向 {side} 位，与内容无关。")
        print("     推论：成对比较必须【双向各跑一次并取交集】，单向结果不可用。")
    elif consistent >= n * 0.8:
        print("  未观察到明显位置偏置，且内容判断稳定。")
    else:
        print("  ⚠️ 内容判断本身就不稳定（换个摆法结论就变），"
              "说明这一对对裁判来说确实难分 —— 此时任何单次结论都不可用。")


# ── 自我偏好偏置 ──────────────────────────────────────────────────────────

def gen_answer(model: str, timeout=900, think: bool = False) -> str:
    """think 参数是必要的：推理模型在 think=False 下会产出【空回答】——
    第一版实验就栽在这，deepseek-r1 给了 0 字，于是 qwen3「判自己赢 6/6」
    其实是在跟空字符串比较，测不出任何自我偏好。（Phase 1 已记录该现象。）"""
    payload = {"model": model, "stream": False, "think": think, "keep_alive": "30m",
               "options": {"temperature": 0, "num_predict": 1200 if think else 300},
               "messages": [{"role": "system", "content":
                             "你是 Kubernetes SRE。只依据给出的 Runbook 上下文回答，简洁作答。"},
                            {"role": "user", "content":
                             f"上下文：\n{CONTEXT}\n\n问题：{QUESTION}"}]}
    req = urllib.request.Request(OLLAMA, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return (json.load(r)["message"].get("content") or "").strip()


def judge_pair_with(model: str, a: str, b: str, timeout=900) -> str:
    payload = {"model": model, "stream": False, "think": False, "keep_alive": "30m",
               "options": {"temperature": 0, "num_predict": 24},
               "format": CHOICE_SCHEMA,
               "messages": [
                   {"role": "system", "content":
                    "你是回答质量评审。比较 A、B 两个回答，选出更好的一个。"
                    "只输出 JSON，winner 取值 A / B / tie。"},
                   {"role": "user", "content":
                    f"上下文：\n{CONTEXT}\n\n问题：{QUESTION}\n\n"
                    f"回答 A：\n{a}\n\n回答 B：\n{b}"}]}
    req = urllib.request.Request(OLLAMA, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        try:
            return json.loads(json.load(r)["message"]["content"])["winner"]
        except Exception:
            return "?"


def exp_self_preference(n: int):
    """裁判会不会偏袒自己生成的答案。用 qwen3 与 deepseek-r1 互评。"""
    M1, M2 = "qwen3:14b", "deepseek-r1:14b"
    print(f"\n⑤ 自我偏好偏置：{M1} 与 {M2} 的回答互评，各方向 {n} 次\n")
    ans1 = gen_answer(M1)
    ans2 = gen_answer(M2, think=True)      # 推理模型必须开 thinking，否则回答为空
    print(f"  {M1} 的回答（{len(ans1)} 字）：{ans1[:66].replace(chr(10), ' ')}…")
    print(f"  {M2} 的回答（{len(ans2)} 字）：{ans2[:66].replace(chr(10), ' ')}…\n")
    if not ans2.strip():
        print("  ❌ 对照方回答为空，实验无效（不能拿真回答跟空字符串比）。")
        return

    print(f"{'裁判':<18}{'自己的答案放A位':<20}{'自己的答案放B位':<20}判自己赢")
    print("-" * 80)
    for judge, own, other in ((M1, ans1, ans2), (M2, ans2, ans1)):
        fwd = [judge_pair_with(judge, own, other) for _ in range(n)]     # 自己在 A
        rev = [judge_pair_with(judge, other, own) for _ in range(n)]     # 自己在 B
        bad = sum(1 for w in fwd + rev if w == "?")
        win = sum(1 for w in fwd if w == "A") + sum(1 for w in rev if w == "B")
        note = f"  ⚠️ {bad}/{2*n} 次解析失败，该行不可用" if bad else ""
        print(f"{judge:<18}{str(fwd):<20}{str(rev):<20}"
              f"{win}/{2*n} = {win/(2*n):.0%}{note}")
    print("\n  判读规则：")
    print("    两个裁判都显著偏向自己  -> 自我偏好偏置")
    print("    只有一个偏向自己       -> **无法与真实质量差异区分**，这一格不能下结论")
    print("  ⚠️ deepseek-r1 作为裁判在本仓库 Phase 1 已实测不可靠"
          "（约束解码下自由字符串字段被污染）。")
    print("     真正的双向自我偏好实验需要【两个都可靠的裁判】—— 本机没有第二个，"
          "这一项标为未完成。")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("-n", type=int, default=10)
    p.add_argument("--noise", action="store_true")
    p.add_argument("--position", action="store_true")
    p.add_argument("--verbosity", action="store_true")
    p.add_argument("--position-close", action="store_true")
    p.add_argument("--self-pref", action="store_true")
    p.add_argument("--all", action="store_true")
    a = p.parse_args()
    if not any((a.noise, a.position, a.verbosity, a.position_close, a.self_pref, a.all)):
        a.all = True

    print("预热并固定 keep_alive（Phase 2 结论：模型加载状态会改变输出）…\n")
    t0 = time.perf_counter()
    warmup()

    if a.noise or a.all:
        exp_noise(a.n)
    if a.position or a.all:
        exp_position(min(a.n, 6))
    if a.verbosity or a.all:
        exp_verbosity(min(a.n, 6))
    if a.position_close or a.all:
        exp_position_close(min(a.n, 6))
    if a.self_pref or a.all:
        exp_self_preference(min(a.n, 3))
    print(f"\n总耗时 {time.perf_counter()-t0:.0f}s")


if __name__ == "__main__":
    main()
