"""HNSW vs 暴力搜索：多大规模才值得上近似索引？

追问（Phase 3 遗留）：**HNSW 的多层图结构为什么比暴力快？M 与 ef_construction
怎么权衡召回率和速度？这是精确近邻还是近似近邻，代价是什么？**

Phase 3 里没法答，因为我们的语料只有 108 个向量 —— 那个规模上 HNSW 毫无意义，
**暴力搜索是精确的而且更快**。要研究它的权衡必须人为放大规模。

本实验不调任何模型（纯 numpy + hnswlib），几分钟出结果。

测什么：
  · 建索引耗时       —— HNSW 的一次性成本
  · 单查询延迟       —— 暴力 vs HNSW
  · Recall@10        —— HNSW 是【近似】的，代价就在这里（以暴力结果为 ground truth）
  · 内存             —— 向量本身 + 图结构

    uv run rag/bench_hnsw.py
    uv run rag/bench_hnsw.py --max-n 500000 --ef-sweep
"""

from __future__ import annotations

import argparse
import time

import hnswlib
import numpy as np

DIM = 768          # 与 nomic-embed-text 一致
K = 10
N_QUERY = 200


# ── 合成向量：两种分布 ────────────────────────────────────────────────────
#
# ⚑ 第一版只用随机单位向量，测出 Recall@10 只有 0.02~0.29 —— 那个数字是【夹具的锅】。
#   768 维随机单位向量是维度灾难的极端：所有向量对余弦都挤在 0 附近、方差极小，
#   「第 10 近」和「第 1000 近」几乎无差别，没有结构可供图导航利用。
#
# 用真实 embedding（本仓库 108 篇 runbook，nomic-embed-text）量出来的分布是：
#     典型对余弦 +0.691 ± 0.072    最近邻 0.903    第 10 近 0.778    可分辨间隙 0.219
# 注意典型对余弦是 **+0.69 而不是 0** —— 同领域文本共享词汇，向量全挤在一个窄锥里
# （embedding 空间的各向异性）。随机向量的典型对余弦是 0.000，完全不像。
#
# 另一个高维陷阱：第一版试图「在簇心附近加一点噪声」，用了 σ=0.35 ——
# 但噪声范数按 σ√d 增长，0.35×√768 ≈ 9.7，完全压倒了单位长度的簇心，
# 结果和纯随机没区别（实测间隙 0.105 vs 0.107）。**高维下必须直接控制范数。**

def make_vectors(n: int, dim: int = DIM, seed: int = 0,
                 kind: str = "realistic") -> np.ndarray:
    rng = np.random.default_rng(seed)
    if kind == "random":
        a = rng.standard_normal((n, dim), dtype=np.float32)
        return a / np.linalg.norm(a, axis=1, keepdims=True)

    # realistic：全局共同分量（窄锥）+ 局部簇结构 + 噪声，权重按【范数】标定，
    # 已对齐真实 embedding 的分布（典型 +0.700±0.042，间隙 0.248）
    n_clusters = max(8, n // 250)
    g = rng.standard_normal(dim).astype(np.float32)
    g /= np.linalg.norm(g)
    cen = rng.standard_normal((n_clusters, dim)).astype(np.float32)
    cen /= np.linalg.norm(cen, axis=1, keepdims=True)
    ci = rng.integers(0, n_clusters, n)
    nz = rng.standard_normal((n, dim)).astype(np.float32)
    nz /= np.linalg.norm(nz, axis=1, keepdims=True)
    v = 1.0 * g + 0.60 * cen[ci] + 0.30 * nz
    return (v / np.linalg.norm(v, axis=1, keepdims=True)).astype(np.float32)


def make_index_and_queries(n: int, n_query: int, kind: str) -> tuple[np.ndarray, np.ndarray]:
    """索引向量与查询向量必须共享【隐变量】（全局方向 + 簇心），不能只换 seed。

    ⚑ 这是本基准踩的第三个夹具坑，也是同一类错误的第三次：
      我原本写 `make_vectors(n, seed=0)` 建索引、`make_vectors(n, seed=99)` 做查询，
      并在注释里写了「查询必须来自同一分布」—— 但**换 seed 换掉的不是样本，
      而是隐变量本身**（全局方向 g 和全部簇心都变了）。
      结果查询点落在另一个锥里，对索引来说是分布外的点，召回率自然极低
      （200k 上只有 0.179，而真实场景 M=16/ef=50 应有 0.9+）。

    正确做法：一次生成 n + n_query 个向量再切分。
    """
    all_v = make_vectors(n + n_query, kind=kind)
    return all_v[:n], all_v[n:]


def brute_topk(vecs: np.ndarray, queries: np.ndarray, k: int) -> np.ndarray:
    """精确最近邻。已归一化 -> 点积就是余弦。"""
    sims = queries @ vecs.T
    return np.argpartition(-sims, k, axis=1)[:, :k]


def recall_at_k(approx: np.ndarray, exact: np.ndarray) -> float:
    hits = sum(len(set(a) & set(e)) for a, e in zip(approx, exact))
    return hits / (approx.shape[0] * approx.shape[1])


def bench_scale(sizes: list[int], M: int, efc: int, ef: int, kind: str = "realistic"):
    print(f"向量分布={kind}   HNSW 参数：M={M}  ef_construction={efc}  ef(查询)={ef}   "
          f"维度={DIM}  k={K}  查询数={N_QUERY}\n")
    print(f"{'向量数':>10}{'暴力延迟':>12}{'HNSW延迟':>12}{'加速比':>9}"
          f"{'Recall@10':>12}{'建索引':>10}{'向量内存':>11}{'图内存':>10}")
    print("-" * 88)
    for n in sizes:
        vecs, queries = make_index_and_queries(n, N_QUERY, kind)

        # 精确：作为 ground truth，同时测延迟
        t = time.perf_counter()
        exact = brute_topk(vecs, queries, K)
        t_brute = (time.perf_counter() - t) / N_QUERY

        idx = hnswlib.Index(space="cosine", dim=DIM)
        idx.init_index(max_elements=n, ef_construction=efc, M=M)
        t = time.perf_counter()
        idx.add_items(vecs, np.arange(n))
        t_build = time.perf_counter() - t
        idx.set_ef(ef)

        t = time.perf_counter()
        labels, _ = idx.knn_query(queries, k=K)
        t_hnsw = (time.perf_counter() - t) / N_QUERY

        vec_mb = n * DIM * 4 / 1e6
        # index_file_size 是方法不是属性。图结构的开销 ≈ 每个点 M*2 条邻接边（第 0 层）
        # 加上上层的 M 条，每条 4 字节 id —— 用实测文件大小减去向量部分更准。
        graph_mb = idx.index_file_size() / 1e6 - vec_mb
        print(f"{n:>10,}{t_brute*1000:>11.3f}ms{t_hnsw*1000:>11.3f}ms"
              f"{t_brute/max(t_hnsw,1e-9):>8.1f}x{recall_at_k(labels, exact):>12.3f}"
              f"{t_build:>9.1f}s{vec_mb:>10.0f}MB{max(graph_mb,0):>9.0f}MB")
        del vecs, idx


def bench_ef(n: int, M: int, efc: int, efs: list[int]):
    """固定规模，扫查询期的 ef —— 这是 HNSW 唯一能【在线】调的旋钮。"""
    print(f"\n固定 {n:,} 个向量（M={M}, ef_construction={efc}），扫查询期 ef\n")
    vecs, queries = make_index_and_queries(n, N_QUERY, "realistic")
    exact = brute_topk(vecs, queries, K)
    t = time.perf_counter()
    _ = brute_topk(vecs, queries, K)
    t_brute = (time.perf_counter() - t) / N_QUERY

    idx = hnswlib.Index(space="cosine", dim=DIM)
    idx.init_index(max_elements=n, ef_construction=efc, M=M)
    idx.add_items(vecs, np.arange(n))

    print(f"{'ef':>6}{'延迟':>12}{'Recall@10':>12}{'相对暴力':>10}")
    print("-" * 42)
    for ef in efs:
        idx.set_ef(max(ef, K))
        t = time.perf_counter()
        labels, _ = idx.knn_query(queries, k=K)
        dt = (time.perf_counter() - t) / N_QUERY
        print(f"{ef:>6}{dt*1000:>11.3f}ms{recall_at_k(labels, exact):>12.3f}"
              f"{t_brute/max(dt,1e-9):>9.1f}x")
    print("\nef 是【查询期】参数：调大 -> 搜索更多候选 -> 召回率升、延迟增。")
    print("M / ef_construction 是【建索引期】参数，改了必须重建整个索引。")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--max-n", type=int, default=200_000)
    p.add_argument("-M", type=int, default=16)
    p.add_argument("--efc", type=int, default=200)
    p.add_argument("--ef", type=int, default=50)
    p.add_argument("--ef-sweep", action="store_true")
    a = p.parse_args()

    sizes = [n for n in (108, 1_000, 10_000, 50_000, 200_000, 500_000) if n <= a.max_n]
    print("=" * 88)
    print("HNSW vs 暴力搜索 · 规模扫描（纯 numpy + hnswlib，不调模型）")
    print("=" * 88)
    print("向量分布已对齐真实 embedding（本仓库 108 篇 runbook 实测：")
    print("典型对余弦 +0.691±0.072 / 最近邻 0.903 / 可分辨间隙 0.219）。\n")
    bench_scale(sizes, a.M, a.efc, a.ef, kind="realistic")
    print("\n" + "=" * 88)
    print("对照：改用【随机单位向量】—— 同样的代码、同样的参数，只换分布")
    print("=" * 88)
    bench_scale(sizes, a.M, a.efc, a.ef, kind="random")
    print(f"\n（108 那一行就是本仓库 runbook 语料的真实规模）")
    if a.ef_sweep:
        bench_ef(min(50_000, a.max_n), a.M, a.efc, [10, 20, 50, 100, 200, 400])


if __name__ == "__main__":
    main()
