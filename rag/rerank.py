"""Reranker：cross-encoder vs bi-encoder。

追问：**两者的本质区别是什么？为什么不能直接用 cross-encoder 检索全库？**

    bi-encoder    query 和 doc 【分别】编码成向量，再算余弦。
                  关键性质：doc 的向量【与 query 无关】-> 可以离线预计算。
                  检索时只做一次 query 编码 + 一次矩阵乘法。

    cross-encoder query 和 doc 【拼在一起】过一次前向，直接输出相关性分数。
                  两者在网络内部逐层交互（attention 能让 query 的 token 看到 doc 的 token）。
                  代价：**没有可预计算的 doc 表示** —— 换个 query 就得全部重算。

Ollama 没有 rerank 端点，这里用 qwen3 当 cross-encoder：
把 query 和候选文档一起塞进一次调用，用约束解码输出 0-10 的整数分。
这不是专用 reranker 模型，但**交互形态是一样的**，足以量化那个代价。

    uv run rag/rerank.py --cost       # 只测成本，几次调用
    uv run rag/rerank.py --eval       # 对 top-5 重排，看 R@1 提升
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from index import load_index, search  # noqa: E402

HERE = Path(__file__).parent
OLLAMA = "http://localhost:11434/api/chat"
MODEL = "qwen3:14b"
SCORE_SCHEMA = {"type": "object",
                "properties": {"score": {"type": "integer"}},
                "required": ["score"], "additionalProperties": False}


def cross_score(query: str, doc: str, timeout=600) -> tuple[int, float, int]:
    """一次前向里同时看 query 和 doc。返回 (分数, 耗时, prompt token 数)。"""
    payload = {"model": MODEL, "stream": False, "think": False, "keep_alive": "30m",
               "options": {"temperature": 0, "num_predict": 12},
               "format": SCORE_SCHEMA,
               "messages": [
                   {"role": "system",
                    "content": "你是检索相关性打分器。判断文档对查询的相关程度，"
                               "输出 0-10 的整数：10=完全对应该查询的故障，0=完全无关。"
                               "只输出 JSON。"},
                   {"role": "user", "content": f"查询：{query}\n\n文档：\n{doc[:2500]}"}]}
    req = urllib.request.Request(OLLAMA, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.load(r)
    dt = time.perf_counter() - t0
    try:
        s = int(json.loads(d["message"]["content"])["score"])
    except Exception:
        s = 0
    return max(0, min(10, s)), dt, d.get("prompt_eval_count", 0)


def mode_cost():
    vecs, chunks, _ = load_index("whole")
    q = "a pod keeps restarting over and over again"
    print("cross-encoder 单次打分的成本（qwen3:14b 代替专用 reranker）\n")
    print(f"{'#':<4}{'文档':<34}{'分':<5}{'prompt token':>14}{'耗时':>9}")
    print("-" * 70)
    times = []
    for i, (_, c) in enumerate(search(q, "whole", 5), 1):
        s, dt, n = cross_score(q, c.text)
        times.append(dt)
        print(f"{i:<4}{c.doc:<34}{s:<5}{n:>14,}{dt:>8.2f}s")

    per = sum(times) / len(times)
    n_docs = len(chunks)
    print(f"\n单次平均 {per:.2f}s")
    print(f"\n{'方式':<34}{'扫描全库 ' + str(n_docs) + ' 篇':>22}")
    print("-" * 58)
    print(f"{'bi-encoder（点积，向量已预计算）':<34}{'0.074 ms':>22}")
    print(f"{'cross-encoder（每篇一次前向）':<34}{f'{per*n_docs:.0f} s':>22}")
    print(f"\n差 {per*n_docs/0.000074:,.0f} 倍。")
    print("原因不是「模型更大」，是 **cross-encoder 没有可预计算的 doc 表示** ——")
    print("doc 的表示依赖 query，换个 query 全部重算。所以它只能用来【重排少量候选】，")
    print("不能用来【检索全库】。两者是流水线上的两级，不是二选一。")


def mode_eval(top_n: int):
    data = json.loads((HERE / "testdata" / "queries.json").read_text())
    queries = data["queries"]
    print(f"对 bi-encoder 的 Top-{top_n} 做 cross-encoder 重排 · {len(queries)} 条查询\n")
    print(f"{'id':<5}{'类型':<5}{'查询':<36}{'重排前':<8}{'重排后':<8}{'耗时':>8}")
    print("-" * 78)
    before = {1: 0, 3: 0}
    after = {1: 0, 3: 0}
    for q in queries:
        hits = search(q["q"], "whole", top_n)
        docs = [c.doc for _, c in hits]
        r_before = next((i + 1 for i, d in enumerate(docs) if d in q["gold"]), None)
        t0 = time.perf_counter()
        scored = [(cross_score(q["q"], c.text)[0], i, c) for i, (_, c) in enumerate(hits)]
        # 分数相同时保持原顺序（稳定），避免重排引入随机抖动
        scored.sort(key=lambda x: (-x[0], x[1]))
        dt = time.perf_counter() - t0
        docs2 = [c.doc for _, _, c in scored]
        r_after = next((i + 1 for i, d in enumerate(docs2) if d in q["gold"]), None)
        for k in (1, 3):
            before[k] += 1 if (r_before and r_before <= k) else 0
            after[k] += 1 if (r_after and r_after <= k) else 0
        f = lambda v: (f"#{v}" if v else "✗")
        mark = "  ↑" if (r_after and r_before and r_after < r_before) else (
            "  ↓" if (r_after and r_before and r_after > r_before) else "")
        print(f"{q['id']:<5}{q['type']:<5}{q['q'][:34]:<36}"
              f"{f(r_before):<8}{f(r_after):<8}{dt:>7.1f}s{mark}")
    n = len(queries)
    print(f"\n{'':<12}{'R@1':>8}{'R@3':>8}")
    print(f"{'重排前':<12}{before[1]/n:>8.0%}{before[3]/n:>8.0%}")
    print(f"{'重排后':<12}{after[1]/n:>8.0%}{after[3]/n:>8.0%}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--cost", action="store_true")
    p.add_argument("--eval", action="store_true")
    p.add_argument("--top-n", type=int, default=5)
    a = p.parse_args()
    if a.cost or not a.eval:
        mode_cost()
    if a.eval:
        mode_eval(a.top_n)
