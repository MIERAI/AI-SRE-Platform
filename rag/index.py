"""Runbook 知识库的索引与检索。

设计决策全部有实测依据（见 docs/phase3-why.md），不照抄教程默认值：

  · **一个文件一个 chunk**（默认）—— 语料中位 145 token / 最大 1154 token，
    远小于 embedding 输入上限。而教程默认的「512 token 固定切片」在这个语料上
    平均每个 chunk 跨 3.3 个 runbook，只有 4/50 的 chunk 只含单篇 —— 检索精度直接崩。
    另提供 section 模式（按 Meaning/Impact/Diagnosis/Mitigation 四段切）用于对照。

  · **不用向量数据库，numpy 暴力点积** —— 117 个向量上 HNSW 毫无意义，
    暴力搜索是【精确】的而且更快。HNSW 的权衡要靠人为放大规模单独实验。
    embedding 已 L2 归一化，所以余弦相似度 = 点积。

  · **每个 chunk 带 source / trust** —— 接 Phase 2 的来源分级结论：
    检索出来的内容同样是不可信输入，provenance 必须从索引阶段就带上，
    不能等到生成答案时才想起来。

  · **nomic 的任务前缀** —— nomic-embed-text 是带 `search_document:` /
    `search_query:` 前缀训练的，漏掉会掉召回。做成开关以便量化影响。

    uv run rag/index.py build                 # 建索引（整篇模式）
    uv run rag/index.py build --mode section  # 按四段切
    uv run rag/index.py search "pod 一直重启怎么查"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
OUT = HERE / "store"
OLLAMA_EMBED = "http://localhost:11434/api/embed"
EMBED_MODEL = "nomic-embed-text"

# 各 embedding 模型的任务前缀约定不同 —— nomic 系列带前缀训练，bge-m3 不带。
# 实测（docs/phase3-why.md）：nomic 的前缀在这个语料上几乎没影响，
# 我原本以为「漏掉会掉召回」，被实验否证了。
PREFIXES = {
    "nomic-embed-text": ("search_document: ", "search_query: "),
    "bge-m3": ("", ""),
}

# 语料源登记表。多来源增量加载：加一行就能接新语料，不用改索引逻辑。
# trust 直接决定后续答案里该给多少权重 —— 公开文档和公司内部 Runbook 不同级。
SOURCES = [
    {
        "id": "public:prometheus-runbooks",
        "root": HERE / "corpus" / "runbooks" / "content" / "runbooks",
        "trust": "public",
        "note": "prometheus-operator/runbooks，按告警名组织",
    },
    # 后续接公司内部 Runbook 时在这里加一条即可：
    # {"id": "internal:sre-runbooks", "root": ..., "trust": "internal", "note": "..."},
]


@dataclass
class Chunk:
    id: str
    text: str
    source: str        # 哪个语料源
    trust: str         # public / internal
    doc: str           # 文档标识（对 runbook 来说就是告警名）
    section: str | None
    n_chars: int


def strip_frontmatter(text: str) -> str:
    return re.sub(r"^---\n.*?\n---\n", "", text, flags=re.S)


def load_chunks(mode: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    for src in SOURCES:
        root: Path = src["root"]
        if not root.exists():
            print(f"  ⚠️ 跳过不存在的语料源: {src['id']} ({root})")
            continue
        for f in sorted(root.rglob("*.md")):
            raw = strip_frontmatter(f.read_text(encoding="utf-8", errors="ignore")).strip()
            if len(raw) < 60:                      # 过滤 _index.md 之类的空壳
                continue
            doc = f.stem
            if mode == "whole":
                chunks.append(Chunk(f"{src['id']}#{doc}", raw, src["id"], src["trust"],
                                    doc, None, len(raw)))
            else:                                   # section 模式
                parts = re.split(r"^## +", raw, flags=re.M)
                head = parts[0].strip()
                for part in parts[1:]:
                    title, _, body = part.partition("\n")
                    body = body.strip()
                    if len(body) < 30:
                        continue
                    # 每段都带上文档标题 —— 否则「## Mitigation」这一段脱离告警名后
                    # 语义几乎为零，检索时根本对不上
                    text = f"{head}\n\n## {title.strip()}\n{body}"
                    chunks.append(Chunk(f"{src['id']}#{doc}#{title.strip()}", text,
                                        src["id"], src["trust"], doc, title.strip(), len(text)))
    return chunks


def embed(texts: list[str], *, prefix: str | None, batch: int = 32,
          model: str = EMBED_MODEL) -> np.ndarray:
    """prefix: 任务前缀。传 None 则不加（用于对照实验）。"""
    vecs = []
    for i in range(0, len(texts), batch):
        payload = {"model": model,
                   "input": [(prefix + t) if prefix else t for t in texts[i:i + batch]]}
        req = urllib.request.Request(OLLAMA_EMBED, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=600) as r:
            vecs.extend(json.load(r)["embeddings"])
    a = np.asarray(vecs, dtype=np.float32)
    # 保险：即使模型已归一化也再归一化一次，让点积严格等于余弦
    return a / np.linalg.norm(a, axis=1, keepdims=True)


def build(mode: str, use_prefix: bool, model: str = EMBED_MODEL, tag: str | None = None):
    OUT.mkdir(exist_ok=True)
    t0 = time.perf_counter()
    chunks = load_chunks(mode)
    print(f"  切片模式 {mode} · 模型 {model}：{len(chunks)} 个 chunk"
          f"（中位 {int(np.median([c.n_chars for c in chunks]))} 字符，"
          f"最大 {max(c.n_chars for c in chunks)}）")
    doc_pfx = PREFIXES.get(model, ("", ""))[0] if use_prefix else None
    vecs = embed([c.text for c in chunks], prefix=doc_pfx or None, model=model)
    tag = tag or f"{mode}{'' if use_prefix else '_noprefix'}"
    np.save(OUT / f"vecs_{tag}.npy", vecs)
    (OUT / f"meta_{tag}.json").write_text(json.dumps(
        {"mode": mode, "use_prefix": use_prefix, "model": model,
         "dim": int(vecs.shape[1]), "chunks": [asdict(c) for c in chunks]},
        ensure_ascii=False))
    print(f"  向量 {vecs.shape}  耗时 {time.perf_counter()-t0:.1f}s  -> store/vecs_{tag}.npy")


def load_index(tag: str):
    meta = json.loads((OUT / f"meta_{tag}.json").read_text())
    return np.load(OUT / f"vecs_{tag}.npy"), [Chunk(**c) for c in meta["chunks"]], meta


def search(query: str, tag: str = "whole", k: int = 5):
    vecs, chunks, meta = load_index(tag)
    model = meta.get("model", EMBED_MODEL)
    q_pfx = PREFIXES.get(model, ("", ""))[1] if meta["use_prefix"] else None
    q = embed([query], prefix=q_pfx or None, model=model)[0]
    scores = vecs @ q                      # 已归一化 -> 点积就是余弦，且是【精确】最近邻
    order = np.argsort(-scores)[:k]
    return [(float(scores[i]), chunks[i]) for i in order]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["build", "search"])
    p.add_argument("query", nargs="?", default="")
    p.add_argument("--mode", default="whole", choices=["whole", "section"])
    p.add_argument("--no-prefix", action="store_true")
    p.add_argument("--model", default=EMBED_MODEL)
    p.add_argument("--tag", default=None)
    p.add_argument("-k", type=int, default=5)
    a = p.parse_args()

    if a.cmd == "build":
        build(a.mode, use_prefix=not a.no_prefix, model=a.model, tag=a.tag)
    else:
        tag = a.tag or f"{a.mode}{'_noprefix' if a.no_prefix else ''}"
        print(f"查询：{a.query}\n索引：{tag}\n" + "-" * 90)
        for score, c in search(a.query, tag, a.k):
            head = c.text.replace("\n", " ")[:78]
            print(f"  {score:.4f}  [{c.trust}] {c.doc}"
                  + (f" · {c.section}" if c.section else "") + f"\n          {head}")


if __name__ == "__main__":
    main()
