"""约束解码（constrained decoding）—— Structured Output 的第二条技术路线。

用 Phase 0 训出来的莎士比亚模型做演示。这个模型对 JSON、对运维告警一无所知，
但约束解码能让它 100% 输出合法格式 —— 因为保证来自采样器，不来自模型。

对照的第一条路线是 prompt 约束："请输出 JSON"，模型可能听可能不听。

    uv run labs/00-nano-gpt/constrained.py
"""

import sys
from pathlib import Path

import mlx.core as mx

sys.path.insert(0, str(Path(__file__).parent))
from data import decode, load_meta       # noqa: E402
from model import GPT, GPTConfig         # noqa: E402

HERE = Path(__file__).parent


class TrieConstraint:
    """只允许生成给定字符串集合中的某一个。

    维护已生成的前缀，每步返回「能让前缀继续保持合法」的字符集合。
    这就是 llama.cpp 的 GBNF、Outlines 库在做的事情，只是它们的语法
    表达能力更强（正则 / CFG），核心机制完全一样：**在 softmax 之前掐掉非法 token**。
    """

    def __init__(self, options: list[str], stoi: dict):
        self.options, self.stoi, self.buf = options, stoi, ""

    def allowed_ids(self) -> list[int]:
        nxt = {o[len(self.buf)] for o in self.options
               if o.startswith(self.buf) and len(o) > len(self.buf)}
        return [self.stoi[c] for c in nxt if c in self.stoi]

    def accept(self, ch: str):
        self.buf += ch

    def finished(self) -> bool:
        return self.buf in self.options


def generate_constrained(model, prompt_ids, constraint, itos, verbose=True):
    """带约束的贪心解码，同时记录模型自己在合法集合上的概率质量。"""
    idx = prompt_ids
    caches = model.new_caches()
    logits = model(idx, caches)[:, -1, :]

    if verbose:
        print(f"{'步':>3}{'合法 token 数':>14}{'模型给合法集的概率':>20}{'选中':>8}")

    total_mass = []
    while not constraint.finished():
        ids = constraint.allowed_ids()
        if not ids:
            break
        probs = mx.softmax(logits, axis=-1)
        allowed = mx.array(ids)

        mass = float(probs[0, allowed].sum())          # 模型本来想输出合法内容的概率
        total_mass.append(mass)

        masked = mx.full(logits.shape, -mx.inf)
        masked[0, allowed] = logits[0, allowed]        # 非法 token 全部压成 -inf
        nxt = mx.argmax(masked, axis=-1, keepdims=True)

        ch = itos[int(nxt[0, 0])]
        if verbose:
            print(f"{len(total_mass):>3}{len(ids):>14}{mass:>19.6%}{repr(ch):>8}")
        constraint.accept(ch)
        idx = mx.concatenate([idx, nxt], axis=1)
        logits = model(nxt, caches)[:, -1, :]

    return constraint.buf, total_mass


def main():
    meta = load_meta()
    cfg = GPTConfig(vocab_size=meta["vocab_size"], block_size=128,
                    n_layer=4, n_head=4, n_embd=192)
    model = GPT(cfg)
    model.load_weights(str(HERE / "out" / "ckpt_small.safetensors"))
    model.eval()
    mx.eval(model.parameters())

    prompt = mx.array([[meta["stoi"]["\n"]]])

    print("=" * 72)
    print("对照组：无约束，让模型自由发挥")
    print("=" * 72)
    free = model.generate(prompt, 60, temperature=0)
    mx.eval(free)
    print(repr(decode(free[0].tolist(), meta["itos"])))

    print()
    print("=" * 72)
    print("实验组：约束到 'severity: {critical|warning|info}'")
    print("=" * 72)
    options = [f"severity: {s}\n" for s in ("critical", "warning", "info")]
    out, mass = generate_constrained(
        model, prompt, TrieConstraint(options, meta["stoi"]), meta["itos"]
    )

    print()
    print(f"输出        : {out!r}")
    print(f"格式合法    : {out in options}   <- 数学上不可能为 False")
    import math
    joint = math.exp(sum(math.log(max(m, 1e-300)) for m in mass))
    print(f"模型自发产出这个字符串的概率 : {joint:.3e}")
    print()
    print("约束解码保证的是【形式】，不是【内容】。")
    print("模型对告警严重度一无所知，它只是在被允许的字符里挑相对概率最高的那个。")


if __name__ == "__main__":
    main()
