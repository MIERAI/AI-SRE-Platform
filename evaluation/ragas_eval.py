"""用 Ragas 评测我们自己的 RAG 管线（全本地：Ollama 驱动裁判与 embedding）。

数据来自本仓库真实资产，不用 Ragas 的演示数据：
  user_input         rag/testdata/queries.json 里的 29 条查询
  retrieved_contexts 我们自己的索引检索出的 Top-K chunk
  response           qwen3 基于这些 context 生成的回答
  reference          gold runbook 的 Diagnosis + Mitigation 段（人工可核对的参考答案）

⚠️ 依赖脆弱性（实测记录）
ragas 0.4.3 的 `llms/base.py:12-13` 从 `langchain_community.chat_models.vertexai`
导入 ChatVertexAI / VertexAI，而 langchain-community 0.4.2 已把它移除（该包正在 sunset）。
**整个 ragas 因此无法导入。**
读源码确认这两个类【只出现在一个 isinstance 检查的列表】里
（MULTIPLE_COMPLETION_SUPPORTED），我们用 Ollama 永远不会命中，
所以打桩是安全的 —— isinstance 返回 False 正是本来就该有的答案。

    uv run evaluation/ragas_eval.py --n 8 --top-k 3
    uv run evaluation/ragas_eval.py --n 8 --top-k 1     # A/B：改检索深度看指标怎么动
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import types
import urllib.request
from pathlib import Path

# ── 依赖桩（必须在 import ragas 之前）─────────────────────────────────────
_m = types.ModuleType("langchain_community.chat_models.vertexai")


class _StubVertex:  # 仅用于 isinstance 检查，永不命中
    ...


_m.ChatVertexAI = _StubVertex
sys.modules["langchain_community.chat_models.vertexai"] = _m
import langchain_community.llms as _L  # noqa: E402

if not hasattr(_L, "VertexAI"):
    _L.VertexAI = _StubVertex

from langchain_ollama import ChatOllama, OllamaEmbeddings  # noqa: E402
from ragas import EvaluationDataset, SingleTurnSample, evaluate  # noqa: E402
from ragas.embeddings import LangchainEmbeddingsWrapper  # noqa: E402
from ragas.llms import LangchainLLMWrapper  # noqa: E402
from ragas.metrics import (  # noqa: E402
    AnswerRelevancy, Faithfulness, LLMContextPrecisionWithoutReference, LLMContextRecall,
)
from ragas.run_config import RunConfig  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "rag"))
from index import load_index, search  # noqa: E402

MODEL = "qwen3:14b"
OLLAMA = "http://localhost:11434/api/chat"
CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿]")


def gen(messages, num_predict=500, timeout=900) -> str:
    payload = {"model": MODEL, "stream": False, "think": False, "keep_alive": "30m",
               "options": {"temperature": 0, "num_predict": num_predict},
               "messages": messages}
    req = urllib.request.Request(OLLAMA, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return (json.load(r)["message"].get("content") or "").strip()


def to_english(q: str) -> str:
    return gen([{"role": "system", "content":
                 "把用户的运维故障描述翻译成简洁的英文技术查询。只输出英文，不要解释。"},
                {"role": "user", "content": q}], num_predict=60)


def reference_answer(doc: str, chunks) -> str:
    """gold runbook 的 Diagnosis + Mitigation 段 —— 人工可核对的参考答案。"""
    text = next((c.text for c in chunks if c.doc == doc), "")
    parts = re.split(r"^## +", text, flags=re.M)
    keep = [p for p in parts[1:]
            if p.split("\n", 1)[0].strip().lower() in ("diagnosis", "mitigation")]
    return "\n".join("## " + p.strip() for p in keep) or text[:800]


def build_dataset(n: int, top_k: int, translate: bool):
    data = json.loads((ROOT / "rag" / "testdata" / "queries.json").read_text())
    queries = data["queries"][:n]
    _, chunks, _ = load_index("whole")
    samples, meta = [], []
    for i, q in enumerate(queries, 1):
        used = to_english(q["q"]) if (translate and CJK.search(q["q"])) else q["q"]
        hits = search(used, "whole", top_k)
        ctxs = [c.text for _, c in hits]
        resp = gen([{"role": "system", "content":
                     "你是 Kubernetes SRE。只依据给出的 Runbook 上下文回答，"
                     "不要引入上下文以外的知识。简洁作答。"},
                    {"role": "user", "content":
                     "Runbook 上下文：\n" + "\n\n---\n\n".join(ctxs)
                     + f"\n\n问题：{q['q']}"}])
        samples.append(SingleTurnSample(
            user_input=q["q"], retrieved_contexts=ctxs, response=resp,
            reference=reference_answer(q["gold"][0], chunks)))
        meta.append({"id": q["id"], "type": q["type"],
                     "hit": any(c.doc in q["gold"] for _, c in hits)})
        print(f"  [{i}/{len(queries)}] {q['id']} {q['q'][:28]:<30} "
              f"召回{'✓' if meta[-1]['hit'] else '✗'}  答案 {len(resp)} 字")
    return EvaluationDataset(samples=samples), meta


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=8)
    p.add_argument("--top-k", type=int, default=3)
    p.add_argument("--no-translate", action="store_true")
    a = p.parse_args()

    judge = LangchainLLMWrapper(ChatOllama(model=MODEL, temperature=0, num_predict=800,
                                           keep_alive="30m", reasoning=False))
    emb = LangchainEmbeddingsWrapper(OllamaEmbeddings(model="nomic-embed-text"))

    print(f"构造数据集：{a.n} 条查询 · Top-{a.top_k} · "
          f"查询翻译={'关' if a.no_translate else '开'}\n")
    ds, meta = build_dataset(a.n, a.top_k, not a.no_translate)

    # ⚠️ Ragas 默认 max_workers=16 / timeout=180 —— 那是按【云 API 有真并发】设计的。
    # Phase 3 实测：Ollama 单实例串行处理请求，并发只是在客户端排队
    #（并发 3 次比串行还慢 0.89x，延迟等差叠加）。
    # 用默认值跑本地模型，24 个 job 全部排队 -> 几乎全部 TimeoutError（实测过）。
    run_cfg = RunConfig(max_workers=1, timeout=900, max_retries=2)
    print(f"\n跑 Ragas 四项指标（裁判 = {MODEL}，全本地，"
          f"max_workers={run_cfg.max_workers} 串行）…")
    result = evaluate(
        dataset=ds,
        metrics=[Faithfulness(), AnswerRelevancy(),
                 LLMContextPrecisionWithoutReference(), LLMContextRecall()],
        llm=judge, embeddings=emb, run_config=run_cfg)

    print("\n" + "=" * 78)
    print(f"配置：Top-{a.top_k} · 翻译={'关' if a.no_translate else '开'} · n={a.n}")
    print("=" * 78)
    print(result)
    df = result.to_pandas()
    cols = [c for c in df.columns if c not in
            ("user_input", "retrieved_contexts", "response", "reference")]
    df.insert(0, "id", [m["id"] for m in meta])
    df.insert(1, "召回", ["✓" if m["hit"] else "✗" for m in meta])
    print("\n逐条：")
    print(df[["id", "召回"] + cols].to_string(index=False, float_format=lambda x: f"{x:.3f}"))


if __name__ == "__main__":
    main()
