"""检索评测：Recall@k，按索引配置 × 查询类型交叉对比。

三个配置各改一件事，便于归因（Phase 1/2 反复栽在「一次改两个变量」上）：
  whole          一个文件一个 chunk + nomic 任务前缀
  section        按 Meaning/Impact/Diagnosis/Mitigation 四段切 + 前缀
  whole_noprefix 一个文件一个 chunk，【不加】前缀

    uv run rag/eval_retrieval.py
    uv run rag/eval_retrieval.py --show-fail      # 打出失败项召回了什么
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from index import search  # noqa: E402

HERE = Path(__file__).parent
TAGS = ["whole", "section", "whole_noprefix", "bge_whole"]
TYPE_NAME = {"A": "A 直接告警名", "B": "B 英文症状", "C": "C 中文症状",
             "D": "D 日文症状", "E": "E 近义混淆"}


def evaluate(tag: str, queries: list[dict], k: int = 5):
    """返回 {qid: (命中的最小 rank 或 None, 召回的 doc 列表)}"""
    out = {}
    for item in queries:
        hits = search(item["q"], tag, k)
        docs = [c.doc for _, c in hits]
        rank = next((i + 1 for i, d in enumerate(docs) if d in item["gold"]), None)
        out[item["id"]] = (rank, docs)
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--show-fail", action="store_true")
    p.add_argument("-k", type=int, default=5)
    a = p.parse_args()

    data = json.loads((HERE / "testdata" / "queries.json").read_text())
    queries = data["queries"]
    by_type: dict[str, list[dict]] = {}
    for q in queries:
        by_type.setdefault(q["type"], []).append(q)

    results = {tag: evaluate(tag, queries, a.k) for tag in TAGS}

    def recall(tag, subset, at):
        rs = [results[tag][q["id"]][0] for q in subset]
        return sum(1 for r in rs if r is not None and r <= at) / len(rs)

    print(f"检索评测 · {len(queries)} 条查询 · nomic-embed-text · 精确最近邻（暴力点积）\n")
    print(f"{'配置':<18}{'R@1':>7}{'R@3':>7}{'R@5':>7}   " +
          "  ".join(f"{TYPE_NAME[t]:<12}" for t in sorted(by_type)))
    print("-" * 104)
    for tag in TAGS:
        row = f"{tag:<18}{recall(tag,queries,1):>7.0%}{recall(tag,queries,3):>7.0%}{recall(tag,queries,5):>7.0%}   "
        row += "  ".join(f"{recall(tag,by_type[t],3):<12.0%}" for t in sorted(by_type))
        print(row)
    print(f"\n（分类型那几列是 R@3；共 {len(by_type)} 类：" +
          "，".join(f"{TYPE_NAME[t]} {len(by_type[t])} 条" for t in sorted(by_type)) + "）")

    # 逐条明细：哪些查询在哪个配置下失败
    print("\n" + "=" * 104)
    print("逐条明细（数字 = 正确答案的排名，✗ = Top-5 内没召回）")
    print("=" * 104)
    print(f"{'id':<5}{'类型':<6}{'查询':<44}" + "".join(f"{t:<17}" for t in TAGS))
    for q in queries:
        cells = ""
        for tag in TAGS:
            r = results[tag][q["id"]][0]
            cells += f"{('#' + str(r)) if r else '✗':<17}"
        print(f"{q['id']:<5}{q['type']:<6}{q['q'][:42]:<44}{cells}")

    if a.show_fail:
        print("\n" + "=" * 104)
        print("失败项召回了什么（以 whole 配置为准）")
        print("=" * 104)
        for q in queries:
            rank, docs = results["whole"][q["id"]]
            if rank is None or rank > 1:
                print(f"\n{q['id']} {q['q']}")
                print(f"   期望: {q['gold']}")
                print(f"   召回: {docs}")


if __name__ == "__main__":
    main()
