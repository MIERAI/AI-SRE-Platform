"""BM25 / 向量 / 混合检索的对比，并验证「BM25 跨语言无用」这个预测。

融合用 RRF（Reciprocal Rank Fusion）：score = Σ 1/(rrf_k + rank_i)
选它而不是加权分数相加，因为 BM25 分数和余弦相似度**量纲完全不同**
（BM25 无上界、余弦在 [-1,1]），直接加权需要标定，RRF 只用排名，免标定。

    uv run rag/eval_hybrid.py
    uv run rag/eval_hybrid.py --saturation   # 单独演示词频饱和项的作用
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from bm25 import BM25  # noqa: E402
from index import load_index, search  # noqa: E402

HERE = Path(__file__).parent
TYPE_NAME = {"A": "A 告警名", "B": "B 英文", "C": "C 中文", "D": "D 日文", "E": "E 近义"}


def rrf(rank_lists: list[list[int]], k: int = 60) -> list[int]:
    """输入若干个「文档下标按相关性排序」的列表，输出融合后的排序。"""
    scores: dict[int, float] = {}
    for ranks in rank_lists:
        for pos, idx in enumerate(ranks):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + pos + 1)
    return [i for i, _ in sorted(scores.items(), key=lambda x: -x[1])]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--saturation", action="store_true")
    p.add_argument("--tag", default="whole")
    a = p.parse_args()

    vecs, chunks, meta = load_index(a.tag)
    texts = [c.text for c in chunks]
    docs = [c.doc for c in chunks]

    if a.saturation:
        demo_saturation(texts, docs)
        return

    bm = BM25(texts)
    data = json.loads((HERE / "testdata" / "queries.json").read_text())
    queries = data["queries"]

    rows = {}
    for q in queries:
        # 向量：直接复用精确检索，取前 20 作为排名列表
        vec_rank = [chunks.index(c) for _, c in search(q["q"], a.tag, 20)]
        bm_rank = [i for _, i in bm.topk(q["q"], 20)]
        fused = rrf([vec_rank, bm_rank])

        def rank_of(order):
            return next((i + 1 for i, idx in enumerate(order[:5]) if docs[idx] in q["gold"]), None)

        rows[q["id"]] = {"vec": rank_of(vec_rank), "bm25": rank_of(bm_rank),
                         "hybrid": rank_of(fused), "type": q["type"]}

    by_type: dict[str, list] = {}
    for q in queries:
        by_type.setdefault(q["type"], []).append(q["id"])

    def recall(method, ids, at):
        rs = [rows[i][method] for i in ids]
        return sum(1 for r in rs if r and r <= at) / len(rs)

    allids = [q["id"] for q in queries]
    print(f"检索方式对比 · {len(queries)} 条查询 · 索引 {a.tag}\n")
    print(f"{'方式':<12}{'R@1':>7}{'R@3':>7}{'R@5':>7}   " +
          "  ".join(f"{TYPE_NAME[t]:<10}" for t in sorted(by_type)))
    print("-" * 88)
    for m, name in (("vec", "向量"), ("bm25", "BM25"), ("hybrid", "混合(RRF)")):
        line = f"{name:<12}{recall(m,allids,1):>7.0%}{recall(m,allids,3):>7.0%}{recall(m,allids,5):>7.0%}   "
        line += "  ".join(f"{recall(m,by_type[t],3):<10.0%}" for t in sorted(by_type))
        print(line)
    print("\n（分类型是 R@3）")

    print("\n" + "=" * 88)
    print("逐条（正确答案排名，✗ = Top-5 没召回）")
    print("=" * 88)
    print(f"{'id':<5}{'类型':<6}{'查询':<40}{'向量':<8}{'BM25':<8}{'混合':<8}")
    for q in queries:
        r = rows[q["id"]]
        f = lambda v: (f"#{v}" if v else "✗")
        print(f"{q['id']:<5}{q['type']:<6}{q['q'][:38]:<40}"
              f"{f(r['vec']):<8}{f(r['bm25']):<8}{f(r['hybrid']):<8}")


def demo_saturation(texts, docs):
    """把 k1 拉到极端，看词频饱和项到底在防什么。"""
    q = "pod pod pod pod restart"          # 故意重复词，模拟关键词堆砌
    print("演示：词频饱和项在防什么\n")
    print(f'查询: {q!r}   （"pod" 重复 4 次，模拟关键词堆砌）\n')
    print(f"{'k1':<8}{'含义':<34}{'Top-3 文档'}")
    print("-" * 92)
    for k1, note in [(0.0, "完全饱和：出现过就算，不看次数"),
                     (1.5, "BM25 默认"),
                     (100.0, "近似线性 = 退化成朴素 TF-IDF")]:
        bm = BM25(texts, k1=k1)
        top = [docs[i] for _, i in bm.topk(q, 3)]
        print(f"{k1:<8}{note:<34}{top}")
    print("\nk1 越大越接近线性 tf。朴素 TF-IDF 的问题是：一篇把 'pod' 刷 50 次的文档"
          "\n会压过真正相关但只提 3 次的文档。饱和项给 tf 加了上界 (k1+1)，堵住这个。")


if __name__ == "__main__":
    main()
