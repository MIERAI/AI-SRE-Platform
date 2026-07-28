"""手写 GPT —— 不使用任何现成的 Transformer 组件。

每个非显然的设计决策都标了 [追问 N]，答案写进 docs/phase0-why.md。
"""

from dataclasses import dataclass

import mlx.core as mx
import mlx.nn as nn


@dataclass
class GPTConfig:
    vocab_size: int = 65
    block_size: int = 128   # 上下文窗口（token 数）
    n_layer: int = 4
    n_head: int = 4
    n_embd: int = 128
    dropout: float = 0.1


class KVCache:
    """单层的 K/V 缓存。

    这里用 concatenate 每步重新分配一块更大的显存 —— 简单但低效，
    而且长度不可预知时会造成严重碎片。真实推理引擎（vLLM）的做法是
    预分配 + 分页管理，那就是 PagedAttention。[追问 ④ → Phase 6]
    """

    def __init__(self):
        self.k = None
        self.v = None

    @property
    def offset(self) -> int:
        return 0 if self.k is None else self.k.shape[2]

    def update(self, k, v):
        if self.k is None:
            self.k, self.v = k, v
        else:
            self.k = mx.concatenate([self.k, k], axis=2)
            self.v = mx.concatenate([self.v, v], axis=2)
        return self.k, self.v


class CausalSelfAttention(nn.Module):
    """多头因果自注意力。手写而不是调 mx.fast.scaled_dot_product_attention，
    因为 mask 那一步是 Phase 0 的核心，必须自己写一遍。"""

    def __init__(self, cfg: GPTConfig):
        super().__init__()
        assert cfg.n_embd % cfg.n_head == 0
        self.n_head = cfg.n_head
        self.head_dim = cfg.n_embd // cfg.n_head
        self.scale = self.head_dim ** -0.5

        # Q/K/V 三个投影合成一个矩阵一次算完 —— 数学上等价于三个独立 Linear，
        # 但只有一次 matmul，GPU 利用率高得多。[追问 ②]
        self.c_attn = nn.Linear(cfg.n_embd, 3 * cfg.n_embd, bias=False)
        self.c_proj = nn.Linear(cfg.n_embd, cfg.n_embd, bias=False)
        self.attn_dropout = nn.Dropout(cfg.dropout)
        self.resid_dropout = nn.Dropout(cfg.dropout)

    def __call__(self, x, mask, cache: "KVCache | None" = None):
        B, T, C = x.shape

        qkv = self.c_attn(x)                       # (B, T, 3C)
        q, k, v = mx.split(qkv, 3, axis=-1)

        # 拆成多头：(B, T, C) -> (B, n_head, T, head_dim)
        # 每个头在 head_dim 维度上独立做注意力，互不干扰。[追问 ③]
        def heads(t):
            return t.reshape(B, T, self.n_head, self.head_dim).transpose(0, 2, 1, 3)

        q, k, v = heads(q), heads(k), heads(v)

        # 只有 K/V 进缓存，Q 不进 —— 判据是"以后还用不用"，不是"变不变"。
        # 解码时 T=1：q 只有一行，k/v 是全部历史。[追问 ④-c]
        if cache is not None:
            k, v = cache.update(k, v)

        # 注意力打分：(B, nh, T, hd) @ (B, nh, hd, T_total) -> (B, nh, T, T_total)
        # 这就是那个 O(n²) 项，T 翻倍它翻四倍。
        att = (q @ k.transpose(0, 1, 3, 2)) * self.scale

        # 因果掩码：位置 i 只能看到 j <= i。把未来位置设成 -inf，
        # softmax 后它们的权重恰好为 0。[追问 ④ —— KV cache 的全部根据在这一行]
        # mask 由调用方按 (新 token 的绝对位置, 全部历史长度) 切好传进来。
        att = att + mask

        att = mx.softmax(att, axis=-1)
        att = self.attn_dropout(att)

        y = att @ v                                # (B, nh, T, hd)
        y = y.transpose(0, 2, 1, 3).reshape(B, T, C)   # 合并多头
        return self.resid_dropout(self.c_proj(y))


class MLP(nn.Module):
    """逐位置前馈网络。中间层放大 4 倍是 Transformer 原论文定下的比例。[追问 ⑤]"""

    def __init__(self, cfg: GPTConfig):
        super().__init__()
        self.c_fc = nn.Linear(cfg.n_embd, 4 * cfg.n_embd, bias=False)
        self.c_proj = nn.Linear(4 * cfg.n_embd, cfg.n_embd, bias=False)
        self.dropout = nn.Dropout(cfg.dropout)

    def __call__(self, x):
        return self.dropout(self.c_proj(nn.gelu(self.c_fc(x))))


class Block(nn.Module):
    """Pre-LN 结构：x + f(LN(x))，而不是原论文的 LN(x + f(x))。[追问 ⑥]

    残差是一条从输入直达输出、不经过任何变换的通路，
    梯度可以原样流回去 —— 这是能堆深的前提。
    """

    def __init__(self, cfg: GPTConfig):
        super().__init__()
        self.ln_1 = nn.LayerNorm(cfg.n_embd)
        self.attn = CausalSelfAttention(cfg)
        self.ln_2 = nn.LayerNorm(cfg.n_embd)
        self.mlp = MLP(cfg)

    def __call__(self, x, mask, cache=None):
        x = x + self.attn(self.ln_1(x), mask, cache)
        x = x + self.mlp(self.ln_2(x))
        return x


class GPT(nn.Module):
    def __init__(self, cfg: GPTConfig):
        super().__init__()
        self.cfg = cfg
        self.wte = nn.Embedding(cfg.vocab_size, cfg.n_embd)   # token 嵌入
        self.wpe = nn.Embedding(cfg.block_size, cfg.n_embd)   # 位置嵌入（可学习绝对位置）[追问 ⑦]
        self.drop = nn.Dropout(cfg.dropout)
        self.blocks = [Block(cfg) for _ in range(cfg.n_layer)]
        self.ln_f = nn.LayerNorm(cfg.n_embd)
        self.lm_head = nn.Linear(cfg.n_embd, cfg.vocab_size, bias=False)

        # 因果掩码只依赖形状，建一次复用。上三角（不含对角线）设为 -inf。
        m = mx.triu(mx.full((cfg.block_size, cfg.block_size), -mx.inf), k=1)
        self._mask = m

    def new_caches(self) -> list[KVCache]:
        return [KVCache() for _ in self.blocks]

    def __call__(self, idx, caches: list[KVCache] | None = None):
        B, T = idx.shape
        past = caches[0].offset if caches else 0
        assert past + T <= self.cfg.block_size, \
            f"总长度 {past + T} 超出上下文窗口 {self.cfg.block_size}"

        # 位置嵌入要用绝对位置：解码第 9 个 token 时它的位置是 8，不是 0。
        # 这一行忘了偏移是 KV cache 最经典的 bug —— 模型不报错，只是胡说八道。
        pos = mx.arange(past, past + T)

        # 掩码切片：新 token 的绝对位置 [past, past+T) 对全部历史 [0, past+T)。
        # 解码时 T=1，切出来是一行全 0（能看到所有历史，包括自己）。
        mask = self._mask[past : past + T, : past + T]

        x = self.drop(self.wte(idx) + self.wpe(pos))   # 广播相加：(B,T,C) + (T,C)
        for i, block in enumerate(self.blocks):
            x = block(x, mask, caches[i] if caches else None)
        return self.lm_head(self.ln_f(x))              # (B, T, vocab_size)

    def loss(self, idx, targets):
        logits = self(idx)
        return nn.losses.cross_entropy(
            logits.reshape(-1, self.cfg.vocab_size), targets.reshape(-1), reduction="mean"
        )

    def n_params(self) -> int:
        from mlx.utils import tree_flatten
        return sum(p.size for _, p in tree_flatten(self.parameters()))

    @staticmethod
    def _sample(logits, temperature: float, top_k: int | None, top_p: float | None):
        if temperature == 0:
            return mx.argmax(logits, axis=-1, keepdims=True)
        logits = logits / temperature
        if top_k is not None:
            # 第 k 大的值作为阈值，比它小的全部压成 -inf
            kth = mx.sort(logits, axis=-1)[:, -top_k : -top_k + 1]
            logits = mx.where(logits < kth, -mx.inf, logits)
        if top_p is not None:
            # 核采样：按概率降序累加，保留累计概率刚超过 p 的最小集合。
            # 和 top-k 的区别是候选集大小随分布的尖锐程度自适应。
            order = mx.argsort(-logits, axis=-1)
            sorted_logits = mx.take_along_axis(logits, order, axis=-1)
            cum = mx.cumsum(mx.softmax(sorted_logits, axis=-1), axis=-1)
            # 右移一位：累计概率首次超过 p 的那个 token 本身要保留
            keep = mx.concatenate([mx.zeros_like(cum[:, :1]), cum[:, :-1]], axis=-1) < top_p
            sorted_logits = mx.where(keep, sorted_logits, -mx.inf)
            inv = mx.argsort(order, axis=-1)                        # 还原原始顺序
            logits = mx.take_along_axis(sorted_logits, inv, axis=-1)
        return mx.random.categorical(logits, axis=-1)[:, None]

    def generate(self, idx, max_new_tokens: int, temperature: float = 1.0,
                 top_k: int | None = None, top_p: float | None = None,
                 use_cache: bool = True):
        """自回归采样。

        use_cache=False 时每一步把整个序列重算一遍 —— O(N²)，留着做对照。
        use_cache=True  时 prefill 一次，之后每步只算 1 个新位置 —— O(N)。[追问 ④-b]
        """
        if not use_cache:
            for _ in range(max_new_tokens):
                logits = self(idx[:, -self.cfg.block_size :])[:, -1, :]
                idx = mx.concatenate([idx, self._sample(logits, temperature, top_k, top_p)], axis=1)
            return idx

        caches = self.new_caches()
        logits = self(idx, caches)[:, -1, :]          # prefill：一次吃下整个 prompt
        for _ in range(max_new_tokens):
            nxt = self._sample(logits, temperature, top_k, top_p)
            idx = mx.concatenate([idx, nxt], axis=1)
            logits = self(nxt, caches)[:, -1, :]      # decode：每步只喂 1 个 token
        return idx
