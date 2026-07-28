"""训练循环。

LR schedule 手写而不是调 mlx.optimizers 的 scheduler —— warmup 的形状要能一眼看见，
而且 --no-warmup 是 [追问 ⑧] 的对照实验开关。

    uv run labs/00-nano-gpt/train.py                  # 基线
    uv run labs/00-nano-gpt/train.py --no-warmup      # 对照：去掉 warmup
"""

import argparse
import csv
import math
import sys
import time
from pathlib import Path

import mlx.core as mx
import mlx.nn as nn
import mlx.optimizers as optim
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from data import decode, load_meta            # noqa: E402
from model import GPT, GPTConfig              # noqa: E402

HERE = Path(__file__).parent
DATA, OUT = HERE / "data", HERE / "out"


def get_batch(split_data, batch_size, block_size):
    """随机采样一批滑动窗口。y 是 x 右移一位 —— 每个位置预测下一个 token。"""
    ix = np.random.randint(0, len(split_data) - block_size - 1, size=batch_size)
    x = np.stack([split_data[i : i + block_size] for i in ix]).astype(np.int32)
    y = np.stack([split_data[i + 1 : i + 1 + block_size] for i in ix]).astype(np.int32)
    return mx.array(x), mx.array(y)


def lr_at(step, *, base_lr, warmup, total, min_ratio=0.1, use_warmup=True):
    """warmup(线性升) + cosine decay(余弦降)。"""
    if use_warmup and step < warmup:
        return base_lr * (step + 1) / warmup
    progress = (step - (warmup if use_warmup else 0)) / max(1, total - (warmup if use_warmup else 0))
    progress = min(1.0, max(0.0, progress))
    return base_lr * (min_ratio + (1 - min_ratio) * 0.5 * (1 + math.cos(math.pi * progress)))


def estimate_loss(model, splits, batch_size, block_size, iters=20):
    model.eval()
    out = {}
    for name, d in splits.items():
        losses = []
        for _ in range(iters):
            x, y = get_batch(d, batch_size, block_size)
            losses.append(model.loss(x, y).item())
        out[name] = sum(losses) / len(losses)
    model.train()
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--steps", type=int, default=2000)
    p.add_argument("--batch-size", type=int, default=64)
    p.add_argument("--block-size", type=int, default=128)
    p.add_argument("--n-layer", type=int, default=4)
    p.add_argument("--n-head", type=int, default=4)
    p.add_argument("--n-embd", type=int, default=128)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--warmup", type=int, default=100)
    p.add_argument("--no-warmup", action="store_true", help="对照实验：去掉 warmup")
    p.add_argument("--post-ln", action="store_true", help="对照实验：用原论文的 Post-LN")
    p.add_argument("--eval-interval", type=int, default=100)
    p.add_argument("--tag", type=str, default="base", help="本次实验名，用于区分日志")
    args = p.parse_args()

    OUT.mkdir(exist_ok=True)
    meta = load_meta()
    train_data = np.load(DATA / "train.npy", mmap_mode="r")
    val_data = np.load(DATA / "val.npy", mmap_mode="r")
    splits = {"train": train_data, "val": val_data}

    cfg = GPTConfig(
        vocab_size=meta["vocab_size"], block_size=args.block_size,
        n_layer=args.n_layer, n_head=args.n_head, n_embd=args.n_embd,
        post_ln=args.post_ln,
    )
    model = GPT(cfg)
    mx.eval(model.parameters())
    print(f"[{args.tag}] 参数量 {model.n_params():,} | "
          f"{'Post-LN' if args.post_ln else 'Pre-LN'} | "
          f"warmup={'off' if args.no_warmup else args.warmup} | lr={args.lr:g}")

    optimizer = optim.AdamW(learning_rate=args.lr, weight_decay=0.1)
    loss_and_grad = nn.value_and_grad(model, lambda m, x, y: m.loss(x, y))

    log_path = OUT / f"log_{args.tag}.csv"
    log = csv.writer(log_path.open("w", newline=""))
    log.writerow(["step", "lr", "train_loss", "val_loss", "elapsed_s"])

    # 只存 val 最优的权重。base 那次跑就是栽在这里：val 在 step 1750 触底，
    # 之后一路过拟合到 2999，最优权重却没留下来，只剩下最终那个更差的状态。
    best_val, best_step = float("inf"), -1
    ckpt = OUT / f"ckpt_{args.tag}.safetensors"

    t0 = time.time()
    for step in range(args.steps):
        optimizer.learning_rate = lr_at(
            step, base_lr=args.lr, warmup=args.warmup,
            total=args.steps, use_warmup=not args.no_warmup,
        )
        x, y = get_batch(train_data, args.batch_size, args.block_size)
        loss, grads = loss_and_grad(model, x, y)
        optimizer.update(model, grads)
        mx.eval(model.parameters(), optimizer.state)

        if step % args.eval_interval == 0 or step == args.steps - 1:
            e = estimate_loss(model, splits, args.batch_size, args.block_size)
            el = time.time() - t0
            star = ""
            if e["val"] < best_val:
                best_val, best_step = e["val"], step
                model.save_weights(str(ckpt))
                star = " *"
            print(f"step {step:>5} | lr {optimizer.learning_rate.item():.2e} | "
                  f"train {e['train']:.4f} | val {e['val']:.4f} | {el:.0f}s{star}")
            log.writerow([step, float(optimizer.learning_rate.item()), e["train"], e["val"], round(el, 1)])

    # 用 val 最优的权重采样，而不是最后一步那个可能已经过拟合的
    print(f"\n最优 val {best_val:.4f} @ step {best_step}（末步 val {e['val']:.4f}）")
    model.load_weights(str(ckpt))
    model.eval()
    prompt = mx.array([[meta["stoi"]["\n"]]])
    gen = model.generate(prompt, 400, temperature=0.8, top_k=40)
    mx.eval(gen)
    sample = decode(gen[0].tolist(), meta["itos"])
    print("\n--- 生成样例 ---\n" + sample)
    (OUT / f"sample_{args.tag}.txt").write_text(sample)
    print(f"\n日志: {log_path}")


if __name__ == "__main__":
    main()
