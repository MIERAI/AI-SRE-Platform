"""对照实验：把 LoRA 的 A/B 初始化**对调**，看收敛差多少。

### 为什么这个实验值得做

mlx-lm（和所有主流实现）是：

    self.lora_a = mx.random.uniform(low=-1/√d, high=1/√d, shape=(input_dims, r))
    self.lora_b = mx.zeros(shape=(r, output_dims))

网上对「为什么 B 零初始化而不是 A」最常见的解释是**「否则梯度为零，学不动」**。
算一下就知道这是错的。令 `z = (xA)B`：

    ∂L/∂B = (xA)ᵀ · g      —— A≠0 所以非零，B 第一步就能动
    ∂L/∂A = xᵀ · (g Bᵀ)    —— B=0 所以第一步为 0，A 第一步不动

B=0 时是「B 先动、A 后动」，能启动。
反过来 A=0 / B 随机时，`∂L/∂A = xᵀ(gBᵀ)` 因 B≠0 而**非零，A 也能动，并不死锁**。

所以真正的理由应该是：**A=0 会让 `x @ A ≡ 0`，B 通路第一步收不到任何输入信号**；
而 A 随机（±1/√d 均匀）是近似保距的随机投影，把输入压到 r 维再交给 B。

**这是我的推断，不是源码能证明的。** 源码只说设计是什么，不说设计对不对 —— 所以跑实验。

实验很干净：对调后 **ΔW = 0 的起点性质依然成立**（A=0 也让 ΔW=0），
所以「从预训练解出发」这个混淆因素被自动消掉，测的纯粹是「输入信号」这一项。

    uv run finetune/ab_init.py --mode normal    # A随机 / B=0（主流）
    uv run finetune/ab_init.py --mode swapped   # A=0 / B随机（对调）
    uv run finetune/ab_init.py --mode both      # 两组都跑并对比
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent

CFG = """model: mlx-community/Qwen3-4B-4bit
train: true
fine_tune_type: lora
data: finetune/data_v2
adapter_path: finetune/adapters/init-{mode}
seed: 0
num_layers: 16
batch_size: 4
iters: {iters}
max_seq_length: 1024
learning_rate: 1.0e-4
mask_prompt: true
steps_per_report: 10
steps_per_eval: 25
val_batches: 6
save_every: 1000
lora_parameters:
  rank: 8
  dropout: 0.0
  scale: 4.0
"""

# 在子进程里执行的 patch + 启动代码。写成子进程是为了每组都从干净的
# 解释器状态开始 —— 同进程内连跑两次，MLX 的图/内存状态会互相影响。
RUNNER = r'''
import sys, math, mlx.core as mx
from mlx_lm.tuner import lora as L

MODE = sys.argv[1]
cfg  = sys.argv[2]

_orig = L.LoRALinear.__init__
def patched(self, input_dims, output_dims, r=8, dropout=0.0, scale=20.0, bias=False):
    _orig(self, input_dims, output_dims, r=r, dropout=dropout, scale=scale, bias=bias)
    if MODE == "swapped":
        s = 1 / math.sqrt(input_dims)
        self.lora_a = mx.zeros(shape=(input_dims, r))
        self.lora_b = mx.random.uniform(low=-s, high=s, shape=(r, output_dims))
L.LoRALinear.__init__ = patched

# 断言 patch 真的生效了 —— 不能假设
probe = L.LoRALinear(input_dims=64, output_dims=32, r=4)
a0 = bool(mx.all(probe.lora_a == 0).item())
b0 = bool(mx.all(probe.lora_b == 0).item())
want = (True, False) if MODE == "swapped" else (False, True)
assert (a0, b0) == want, f"patch 未生效: A全零={a0} B全零={b0}, 期望 {want}"
print(f"[patch 已验证] mode={MODE}  A全零={a0}  B全零={b0}", flush=True)

sys.argv = ["mlx_lm.lora", "--config", cfg]
from mlx_lm.lora import main
main()
'''


def run(mode: str, iters: int) -> dict:
    cfg = HERE / f"config-init-{mode}.yaml"
    cfg.write_text(CFG.format(mode=mode, iters=iters))
    runner = HERE / "_run_init.py"
    runner.write_text(RUNNER)

    print(f"\n▶ mode={mode}  ({'A随机 / B=0，主流' if mode=='normal' else 'A=0 / B随机，对调'})")
    t0 = time.perf_counter()
    proc = subprocess.run([sys.executable, str(runner), mode, str(cfg)],
                          cwd=ROOT, capture_output=True, text=True,
                          env={**__import__("os").environ, "PYTHONUNBUFFERED": "1"})
    dt = time.perf_counter() - t0
    out = proc.stdout + proc.stderr
    (HERE / f"logs/init-{mode}.log").parent.mkdir(exist_ok=True)
    (HERE / f"logs/init-{mode}.log").write_text(out)

    if proc.returncode != 0:
        print(f"  ✗ rc={proc.returncode}\n{out[-2000:]}")
        return {"mode": mode, "failed": True}
    if "[patch 已验证]" in out:
        print("  " + [l for l in out.splitlines() if "[patch 已验证]" in l][0])

    train = [(int(a), float(b)) for a, b in re.findall(r"Iter (\d+): Train loss ([\d.]+)", out)]
    val = [(int(a), float(b)) for a, b in re.findall(r"Iter (\d+): Val loss ([\d.]+)", out)]
    print(f"  训练 {dt:.0f}s   val: " +
          "  ".join(f"{s}步={v:.4f}" for s, v in val))
    return {"mode": mode, "failed": False, "seconds": round(dt, 1),
            "train_curve": train, "val_curve": val,
            "adapter": f"finetune/adapters/init-{mode}"}


def evaluate(adapter: str) -> dict:
    subprocess.run(["uv", "run", "finetune/eval_detect.py", "--backend", "mlx",
                    "--adapter", adapter, "--dataset", "adversarial",
                    "--save", f"{adapter}/eval.json"],
                   cwd=ROOT, capture_output=True, text=True)
    p = ROOT / adapter / "eval.json"
    return json.loads(p.read_text()) if p.exists() else {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["normal", "swapped", "both"], default="both")
    ap.add_argument("--iters", type=int, default=100)
    a = ap.parse_args()

    print("=" * 84)
    print("LoRA A/B 初始化对调 —— 检验「A=0 会让 B 收不到输入信号」这个推断")
    print("=" * 84)
    print("注意：两种初始化【都】满足 ΔW=0 的起点性质，所以「从预训练解出发」")
    print("这个混淆因素自动消掉，测的纯粹是输入信号那一项。\n")

    modes = ["normal", "swapped"] if a.mode == "both" else [a.mode]
    rows = []
    for m in modes:
        r = run(m, a.iters)
        if not r.get("failed"):
            r["eval"] = evaluate(r["adapter"])
            e = r["eval"]
            if e:
                f5 = e["by_family"].get("F6b_无害诱饵", [0, 1])
                print(f"  评测 总计 {e['total'][0]}/{e['total'][1]}"
                      f"={e['total'][0]/e['total'][1]:.1%}   ★F6b {f5[0]}/{f5[1]}={f5[0]/f5[1]:.1%}")
        rows.append(r)

    out = HERE / "results/ab-init.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2))

    if len(rows) == 2 and not any(r.get("failed") for r in rows):
        print(f"\n{'='*84}")
        print(f"{'初始化':<22}{'首个val':>10}{'末val':>10}{'总准确率':>11}{'★F6b':>9}{'耗时':>8}")
        print("-" * 84)
        for r in rows:
            e = r.get("eval") or {}
            tot = e.get("total", [0, 1])
            f5 = e.get("by_family", {}).get("F6b_无害诱饵", [0, 1])
            name = "A随机/B=0（主流）" if r["mode"] == "normal" else "A=0/B随机（对调）"
            vc = r["val_curve"]
            print(f"{name:<20}{vc[0][1] if vc else float('nan'):>10.4f}"
                  f"{vc[-1][1] if vc else float('nan'):>10.4f}"
                  f"{tot[0]/tot[1]:>11.1%}{f5[0]/f5[1]:>9.1%}{r['seconds']:>7.0f}s")
        print("\n若两组 val 曲线与 F6b 都无差别，则「A=0 更差」这个推断在本任务上【不成立】——")
        print("那说明主流写法的理由另有出处（或只是约定），得照实记下来。")
    print(f"\n→ {out}")


if __name__ == "__main__":
    main()
