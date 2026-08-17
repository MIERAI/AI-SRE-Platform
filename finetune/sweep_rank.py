"""扫 LoRA rank，**固定 alpha 而不是固定 scale**。

### 为什么不能直接扫 rank

mlx-lm 的 `LoRALinear` 里 `self.scale` 是构造时定死的常数，**不含 1/r**：

    def __call__(self, x):
        z = (self.dropout(x) @ self.lora_a) @ self.lora_b
        return y + (self.scale * z)

HF peft 的 `scale = lora_alpha / r` 才带 1/r —— 那个除法正是为了让不同 rank 下
ΔW 的量级可比。所以在 mlx-lm 里保持 `scale=20` 扫 rank，会**同时改动容量和
有效学习率**两个变量，测出来的差异无法归因。

这是同一个混淆变量的坑第三次出现（Phase 0 的 warmup 连带 cosine、
Phase 0 的 KV cache 连带 n_layer+n_embd）。所以这里换算成固定 alpha：

    alpha := scale_ref × rank_ref = 20 × 8 = 160
    scale(r) = 160 / r      ->   r=4:40   r=8:20   r=16:10   r=64:2.5

`--fixed-scale` 可以跑「错误」的那一组（scale 恒为 20）做对照 ——
**证明这个混淆是真的存在，而不是我纸上推的。**

    uv run finetune/sweep_rank.py                 # 固定 alpha（正确）
    uv run finetune/sweep_rank.py --fixed-scale   # 固定 scale（作为反面对照）
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
ALPHA = 160.0          # = 主实验的 scale 20 × rank 8
RANKS = [4, 8, 16, 64]

BASE = """model: mlx-community/Qwen3-4B-4bit
train: true
fine_tune_type: lora
data: finetune/data
adapter_path: {adapter}
seed: 0
num_layers: 16
batch_size: 4
iters: {iters}
max_seq_length: 1024
learning_rate: 1.0e-4
mask_prompt: true
steps_per_report: 50
steps_per_eval: 100
val_batches: 6
save_every: 1000
lora_parameters:
  rank: {rank}
  dropout: 0.0
  scale: {scale}
"""


def train_one(rank: float, scale: float, iters: int, tag: str) -> dict:
    cfg = HERE / f"config-sweep-{tag}.yaml"
    adapter = f"finetune/adapters/{tag}"
    cfg.write_text(BASE.format(adapter=adapter, rank=rank, scale=scale, iters=iters))

    log = HERE / f"logs/train-{tag}.log"
    log.parent.mkdir(exist_ok=True)
    t0 = time.perf_counter()
    # /usr/bin/time -l 给出 maximum resident set size（峰值内存）
    proc = subprocess.run(
        ["/usr/bin/time", "-l", "uv", "run", "mlx_lm.lora", "--config", str(cfg)],
        cwd=ROOT, capture_output=True, text=True,
        env={**__import__("os").environ, "PYTHONUNBUFFERED": "1"})
    dt = time.perf_counter() - t0
    out = proc.stdout + proc.stderr
    log.write_text(out)

    if proc.returncode != 0:
        print(f"  ✗ 训练失败 rc={proc.returncode}，见 {log}")
        return {"tag": tag, "failed": True}

    vals = [(int(a), float(b)) for a, b in
            re.findall(r"Iter (\d+): Val loss ([\d.]+)", out)]
    trainable = re.search(r"Trainable parameters: ([\d.]+)% \(([\d.]+)M", out)
    rss = re.search(r"([\d]+)\s+maximum resident set size", out)
    ad = Path(ROOT / adapter / "adapters.safetensors")
    return {
        "tag": tag, "rank": rank, "scale": scale, "failed": False,
        "train_seconds": round(dt, 1),
        "val_loss_first": vals[0][1] if vals else None,
        "val_loss_last": vals[-1][1] if vals else None,
        "val_curve": vals,
        "trainable_pct": float(trainable.group(1)) if trainable else None,
        "trainable_M": float(trainable.group(2)) if trainable else None,
        "peak_rss_gb": round(int(rss.group(1)) / 1e9, 2) if rss else None,
        "adapter_mb": round(ad.stat().st_size / 1e6, 2) if ad.exists() else None,
        "adapter": adapter,
    }


def eval_one(adapter: str) -> dict:
    proc = subprocess.run(
        ["uv", "run", "finetune/eval_detect.py", "--backend", "mlx",
         "--adapter", adapter, "--save", f"{adapter}/eval.json"],
        cwd=ROOT, capture_output=True, text=True)
    p = ROOT / adapter / "eval.json"
    if not p.exists():
        print(f"  ✗ 评测失败:\n{proc.stdout[-1500:]}\n{proc.stderr[-1500:]}")
        return {}
    return json.loads(p.read_text())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixed-scale", action="store_true",
                    help="反面对照：scale 恒为 20，不随 rank 缩放")
    ap.add_argument("--iters", type=int, default=300)
    ap.add_argument("--ranks", type=int, nargs="+", default=RANKS)
    a = ap.parse_args()

    mode = "fixedscale" if a.fixed_scale else "fixedalpha"
    print("=" * 96)
    print(f"LoRA rank 扫描 · {'固定 scale=20（反面对照，含混淆）' if a.fixed_scale else f'固定 alpha={ALPHA:.0f}（正确）'}")
    print("=" * 96)

    rows = []
    for rank in a.ranks:
        scale = 20.0 if a.fixed_scale else ALPHA / rank
        tag = f"{mode}-r{rank}"
        print(f"\n▶ rank={rank}  scale={scale:g}  ({tag})")
        r = train_one(rank, scale, a.iters, tag)
        if r.get("failed"):
            rows.append(r)
            continue
        print(f"  训练 {r['train_seconds']}s  可训练 {r['trainable_M']}M "
              f"({r['trainable_pct']}%)  峰值 {r['peak_rss_gb']}GB  "
              f"adapter {r['adapter_mb']}MB  val {r['val_loss_first']}→{r['val_loss_last']}")
        r["eval"] = eval_one(r["adapter"])
        if r["eval"]:
            f5 = r["eval"]["by_family"].get("F5_诱导泄露", [0, 1])
            tot = r["eval"]["total"]
            print(f"  评测 总计 {tot[0]}/{tot[1]}={tot[0]/tot[1]:.1%}   "
                  f"★F5 {f5[0]}/{f5[1]}={f5[0]/f5[1]:.1%}")
        rows.append(r)

    out = HERE / f"results/sweep-{mode}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2))

    print(f"\n{'='*96}")
    print(f"{'rank':>6}{'scale':>8}{'可训练':>10}{'训练':>9}{'峰值内存':>10}"
          f"{'adapter':>10}{'val_loss':>11}{'总准确率':>10}{'★F5':>10}")
    print("-" * 96)
    for r in rows:
        if r.get("failed"):
            print(f"{r['tag']:>14}  训练失败")
            continue
        e = r.get("eval") or {}
        tot = e.get("total", [0, 1])
        f5 = e.get("by_family", {}).get("F5_诱导泄露", [0, 1])
        print(f"{r['rank']:>6}{r['scale']:>8g}{r['trainable_M']:>9.1f}M"
              f"{r['train_seconds']:>8.0f}s{r['peak_rss_gb']:>9.1f}G"
              f"{r['adapter_mb']:>9.1f}M{r['val_loss_last']:>11.3f}"
              f"{tot[0]/tot[1]:>10.1%}{f5[0]/f5[1]:>10.1%}")
    print(f"\n→ {out}")
    if not a.fixed_scale:
        print("\n跑 --fixed-scale 得到反面对照：若两组的 rank 趋势不同，")
        print("就实证了「scale 不随 rank 缩放」是真实的混淆变量，而非纸上推论。")


if __name__ == "__main__":
    sys.exit(main())
