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

    def __call__(self, x, mask):
        B, T, C = x.shape

        qkv = self.c_attn(x)                       # (B, T, 3C)
        q, k, v = mx.split(qkv, 3, axis=-1)

        # 拆成多头：(B, T, C) -> (B, n_head, T, head_dim)
        # 每个头在 head_dim 维度上独立做注意力，互不干扰。[追问 ③]
        def heads(t):
            return t.reshape(B, T, self.n_head, self.head_dim).transpose(0, 2, 1, 3)

        q, k, v = heads(q), heads(k), heads(v)

        # 注意力打分：(B, nh, T, hd) @ (B, nh, hd, T) -> (B, nh, T, T)
        # 这就是那个 O(n²) 项，T 翻倍它翻四倍。
        att = (q @ k.transpose(0, 1, 3, 2)) * self.scale

        # 因果掩码：位置 i 只能看到 j <= i。把未来位置设成 -inf，
        # softmax 后它们的权重恰好为 0。[追问 ④ —— KV cache 的全部根据在这一行]
        att = att + mask[:T, :T]

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

    def __call__(self, x, mask):
        x = x + self.attn(self.ln_1(x), mask)
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

    def __call__(self, idx):
        B, T = idx.shape
        assert T <= self.cfg.block_size, f"序列长度 {T} 超出上下文窗口 {self.cfg.block_size}"

        pos = mx.arange(T)
        x = self.drop(self.wte(idx) + self.wpe(pos))   # 广播相加：(B,T,C) + (T,C)
        for block in self.blocks:
            x = block(x, self._mask)
        return self.lm_head(self.ln_f(x))              # (B, T, vocab_size)

    def loss(self, idx, targets):
        logits = self(idx)
        return nn.losses.cross_entropy(
            logits.reshape(-1, self.cfg.vocab_size), targets.reshape(-1), reduction="mean"
        )

    def n_params(self) -> int:
        from mlx.utils import tree_flatten
        return sum(p.size for _, p in tree_flatten(self.parameters()))

    def generate(self, idx, max_new_tokens: int, temperature: float = 1.0, top_k: int | None = None):
        """自回归采样。注意这里每一步都把整个序列重算了一遍 —— 极度浪费。
        跑通之后加 KV cache，就是要消掉这个浪费。[追问 ④]"""
        for _ in range(max_new_tokens):
            idx_cond = idx[:, -self.cfg.block_size:]      # 超窗就截断
            logits = self(idx_cond)[:, -1, :]             # 只要最后一个位置的预测
            if temperature == 0:
                nxt = mx.argmax(logits, axis=-1, keepdims=True)
            else:
                logits = logits / temperature
                if top_k is not None:
                    kth = mx.sort(logits, axis=-1)[:, -top_k:-top_k + 1]
                    logits = mx.where(logits < kth, -mx.inf, logits)
                nxt = mx.random.categorical(logits, axis=-1)[:, None]
            idx = mx.concatenate([idx, nxt], axis=1)
        return idx
