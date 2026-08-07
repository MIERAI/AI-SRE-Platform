"""BM25 —— 自己实现，不用库。

追问：**为什么 BM25 有词频饱和项？为什么不用朴素 TF-IDF？**

朴素 TF-IDF 的词频项是线性的：一个词出现 20 次，权重就是出现 1 次的 20 倍。
但直觉上「出现 20 次」并不比「出现 5 次」相关 4 倍 —— 收益是递减的。

BM25 用这一项替代线性 tf：

        tf * (k1 + 1)
    ---------------------      k1 控制饱和速度
     tf + k1 * (1 - b + b*|D|/avgdl)

    tf -> ∞ 时整项 -> (k1 + 1)，**有上界**。这就是「饱和」。
    b 控制文档长度归一化：长文档天然词频高，要打折。b=0 不归一化，b=1 完全归一化。

分词的坑：BM25 是**词汇匹配**，所以强依赖分词。
中日文没有空格，这里用字符 bigram（给 BM25 在 CJK 上最好的机会）——
如果这样它在跨语言上仍然是 0，就说明失败是【词汇不重叠】这个根本原因，
不是分词实现的锅。
"""

from __future__ import annotations

import math
import re
from collections import Counter

CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿]")
LATIN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """拉丁词按空白/标点切；CJK 用字符 bigram（无空格语言的常用折中）。"""
    text = text.lower()
    toks = LATIN.findall(text)
    # 驼峰拆分：KubePodCrashLooping -> kube pod crash looping
    # 不拆的话告警名是一个整词，症状描述永远匹配不上
    extra = []
    for t in toks:
        parts = re.findall(r"[a-z]+|[0-9]+", t)
        if len(parts) > 1:
            extra.extend(parts)
    toks += extra
    for m in re.finditer(r"[぀-ヿ㐀-䶿一-鿿]+", text):
        s = m.group()
        toks.append(s) if len(s) == 1 else toks.extend(s[i:i + 2] for i in range(len(s) - 1))
    return toks


def split_camel(text: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)


class BM25:
    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs_tok = [tokenize(split_camel(d)) for d in docs]
        self.N = len(docs)
        self.doc_len = [len(d) for d in self.docs_tok]
        self.avgdl = sum(self.doc_len) / max(self.N, 1)
        self.tf = [Counter(d) for d in self.docs_tok]
        df = Counter()
        for d in self.docs_tok:
            df.update(set(d))
        # BM25 的 IDF（带 +0.5 平滑，避免高频词变负）
        self.idf = {t: math.log(1 + (self.N - n + 0.5) / (n + 0.5)) for t, n in df.items()}

    def score(self, query: str) -> list[float]:
        q = tokenize(split_camel(query))
        out = [0.0] * self.N
        for i in range(self.N):
            tf_i, dl = self.tf[i], self.doc_len[i]
            s = 0.0
            for t in q:
                f = tf_i.get(t, 0)
                if not f:
                    continue
                # ↓ 饱和项：分母里的 f 让整体在 f→∞ 时收敛到 idf*(k1+1)
                s += self.idf.get(t, 0.0) * (f * (self.k1 + 1)) / (
                    f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
            out[i] = s
        return out

    def topk(self, query: str, k: int = 5) -> list[tuple[float, int]]:
        sc = self.score(query)
        return sorted(((s, i) for i, s in enumerate(sc)), reverse=True)[:k]
