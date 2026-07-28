"""追问 ⑥/⑧ 对照实验：LN 位置 × warmup × 学习率。

假设（从梯度路径推出来的）：
  Pre-LN  残差是恒等直通车 -> 对 warmup 不敏感，去掉也稳
  Post-LN 每层梯度都过一次 LN 雅可比 -> 没有 warmup，大 lr 下早期就崩

跑法： uv run labs/00-nano-gpt/ablation_ln.py
"""

import sys
from pathlib import Path

import mlx.core as mx
import mlx.nn as nn
import mlx.optimizers as optim
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from model import GPT, GPTConfig      # noqa: E402
from train import get_batch, lr_at    # noqa: E402

DATA = Path(__file__).parent / "data"
STEPS, BATCH, BLOCK = 300, 32, 128
PROBES = (0, 10, 25, 50, 100, 200, 299)


def lr_constant(step, *, base_lr, warmup, use_warmup, **_):
    """恒定 lr + 可选 warmup。

    这是隔离 warmup 效应的干净对照：两组唯一的差别就是前 warmup 步，
    之后 lr 完全相同。用 cosine 的话，no-warmup 组的整条曲线都被平移了，
    测出来的差距分不清是 warmup 的功劳还是平均 lr 更低。
    """
    if use_warmup and step < warmup:
        return base_lr * (step + 1) / warmup
    return base_lr


def run(post_ln: bool, use_warmup: bool, lr: float, train_data, vocab_size: int,
        schedule=lr_at):
    mx.random.seed(1234)
    np.random.seed(1234)
    cfg = GPTConfig(vocab_size=vocab_size, block_size=BLOCK, n_layer=12,
                    n_head=4, n_embd=128, dropout=0.0, post_ln=post_ln)
    model = GPT(cfg)
    mx.eval(model.parameters())
    opt = optim.AdamW(learning_rate=lr, weight_decay=0.1)
    lg = nn.value_and_grad(model, lambda m, x, y: m.loss(x, y))

    curve, worst = {}, 0.0
    for step in range(STEPS):
        opt.learning_rate = schedule(step, base_lr=lr, warmup=50, total=STEPS, use_warmup=use_warmup)
        x, y = get_batch(train_data, BATCH, BLOCK)
        loss, grads = lg(model, x, y)
        opt.update(model, grads)
        mx.eval(model.parameters(), opt.state)
        l = loss.item()
        if not (l == l):              # NaN
            return {p: float("nan") for p in PROBES}, float("nan")
        worst = max(worst, l)
        if step in PROBES:
            curve[step] = l
    return curve, worst


def main():
    import json
    constant = "--constant-lr" in sys.argv
    schedule = lr_constant if constant else lr_at
    vocab_size = json.loads((DATA / "meta.json").read_text())["vocab_size"]
    train_data = np.load(DATA / "train.npy", mmap_mode="r")

    print(f"12 层 / n_embd=128 / {STEPS} steps / 无 dropout / 固定随机种子 / "
          f"lr schedule = {'恒定（干净对照）' if constant else 'warmup+cosine'}\n")
    hdr = f"{'配置':<26}" + "".join(f"{'s' + str(p):>9}" for p in PROBES) + f"{'峰值':>9}"
    print(hdr)
    print("-" * len(hdr))

    for lr in (1e-3, 6e-3):
        for post_ln in (False, True):
            for use_warmup in (True, False):
                name = (f"{'Post-LN' if post_ln else 'Pre-LN '} "
                        f"{'warmup ' if use_warmup else 'no-warm'} lr={lr:g}")
                curve, worst = run(post_ln, use_warmup, lr, train_data, vocab_size, schedule)
                cells = "".join(f"{curve.get(p, float('nan')):>9.3f}" for p in PROBES)
                print(f"{name:<26}{cells}{worst:>9.3f}")
        print()


if __name__ == "__main__":
    main()
