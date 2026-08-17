"""量 F6b 指标的噪声底：**同配置、只改 seed，重复跑**。

### 为什么必须先做这个

一次意外的重复暴露了问题：

    init-normal   (data_v2, scale4, lr1e-4, seed0, 100步)   F6b  9/32 = 28.1%
    v2b ckpt100   (data_v2, scale4, lr1e-4, seed0, 100步)   F6b 15/32 = 46.9%

**这两个本该是同一个模型**（唯一差异是 `steps_per_eval` 25 vs 50 和 `iters` 100 vs 300，
都不该影响 100 步时的权重 —— 除非 val 计算消耗了全局 rng、改变了训练 batch 顺序）。
却差 **18.8 个百分点**。

在噪声底未知的情况下，下面这些结论全都悬空：

    「只差 scale」        78.1% vs 73.5%   差 4.6 点
    「步数是主导变量」     73.5% -> 90.6%   差 17.1 点
    「v2b 超过 14B」      90.6% vs 82.8%   差 7.8 点
    「A/B 对调更好」      28.1% vs 93.8%   差 65.7 点

这是 Phase 1 立下的判据 —— **先量噪声底，再谈信号** —— 在 F6b 这条指标上的失守。
我一直在比较单次运行的差值，直到这次意外重复才撞上它。

### 做法

固定一切、只改 seed，各跑 N 次，报 F6b 与平衡准确率的 min/max/极差。
**极差就是噪声底**：任何小于它的差值都不能当信号。

    uv run finetune/noise_floor.py --seeds 0 1 2          # normal（主流初始化）
    uv run finetune/noise_floor.py --seeds 0 1 2 --swapped
"""

from __future__ import annotations

import argparse
import json
import os
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
adapter_path: {adapter}
seed: {seed}
num_layers: 16
batch_size: 4
iters: {iters}
max_seq_length: 1024
learning_rate: 1.0e-4
mask_prompt: true
steps_per_report: 50
steps_per_eval: 50
val_batches: 6
save_every: 1000
lora_parameters:
  rank: 8
  dropout: 0.0
  scale: 4.0
"""

# ⚑ 与 ab_init.py 的区别：对调时 B 用 1/√r 而不是 1/√input_dims。
#   ab_init.py 第一版给 B 用了 1/√input_dims（≈1/√2560≈0.0198），
#   但 **B 的 fan_in 是 r**，对称的选择是 1/√8≈0.354 —— 差 18 倍。
#   那一版跑的不是「干净的对调」，而是「A=0 且 B 是个极小的随机值」。
RUNNER = r'''
import sys, math, mlx.core as mx
from mlx_lm.tuner import lora as L
MODE, cfg = sys.argv[1], sys.argv[2]
_orig = L.LoRALinear.__init__
def patched(self, input_dims, output_dims, r=8, dropout=0.0, scale=20.0, bias=False):
    _orig(self, input_dims, output_dims, r=r, dropout=dropout, scale=scale, bias=bias)
    if MODE == "swapped":
        s = 1 / math.sqrt(r)          # ← fan_in 是 r，不是 input_dims
        self.lora_a = mx.zeros(shape=(input_dims, r))
        self.lora_b = mx.random.uniform(low=-s, high=s, shape=(r, output_dims))
L.LoRALinear.__init__ = patched
probe = L.LoRALinear(input_dims=64, output_dims=32, r=4)
a0 = bool(mx.all(probe.lora_a == 0).item()); b0 = bool(mx.all(probe.lora_b == 0).item())
assert (a0, b0) == ((True, False) if MODE == "swapped" else (False, True)), "patch 未生效"
print(f"[patch 已验证] mode={MODE} A全零={a0} B全零={b0}", flush=True)
sys.argv = ["mlx_lm.lora", "--config", cfg]
from mlx_lm.lora import main
main()
'''


def one(seed: int, iters: int, swapped: bool) -> dict:
    mode = "swapped" if swapped else "normal"
    tag = f"noise-{mode}-s{seed}"
    adapter = f"finetune/adapters/{tag}"
    cfg = HERE / f"config-{tag}.yaml"
    cfg.write_text(CFG.format(adapter=adapter, seed=seed, iters=iters))
    runner = HERE / "_run_noise.py"
    runner.write_text(RUNNER)

    t0 = time.perf_counter()
    p = subprocess.run([sys.executable, str(runner), mode, str(cfg)],
                       cwd=ROOT, capture_output=True, text=True,
                       env={**os.environ, "PYTHONUNBUFFERED": "1"})
    dt = time.perf_counter() - t0
    out = p.stdout + p.stderr
    (HERE / "logs").mkdir(exist_ok=True)
    (HERE / f"logs/{tag}.log").write_text(out)
    if p.returncode != 0:
        print(f"  seed {seed}: 训练失败 rc={p.returncode}")
        return {"seed": seed, "failed": True}
    if "nan" in out.lower():
        print(f"  seed {seed}: ⚑ 日志里出现 nan")

    val = [(int(a), float(b)) for a, b in re.findall(r"Iter (\d+): Val loss ([\d.]+)", out)]
    subprocess.run(["uv", "run", "finetune/eval_detect.py", "--backend", "mlx",
                    "--adapter", adapter, "--dataset", "adversarial",
                    "--save", f"{adapter}/eval.json"],
                   cwd=ROOT, capture_output=True, text=True)
    ep = ROOT / adapter / "eval.json"
    if not ep.exists():
        print(f"  seed {seed}: 评测失败")
        return {"seed": seed, "failed": True}
    e = json.loads(ep.read_text())
    f6a = e["by_family"].get("F6a_形式泛化", [0, 1])
    f6b = e["by_family"].get("F6b_无害诱饵", [0, 1])
    rec = e["tp"] / (e["tp"] + e["fn"]) if e["tp"] + e["fn"] else 0.0
    spec = e["tn"] / (e["tn"] + e["fp"]) if e["tn"] + e["fp"] else 0.0
    r = {"seed": seed, "failed": False, "seconds": round(dt, 1),
         "val_last": val[-1][1] if val else None,
         "f6a": f6a, "f6b": f6b, "balanced": (rec + spec) / 2,
         "unparsed": e["unparsed"]}
    print(f"  seed {seed}: val末 {r['val_last']}  F6a {f6a[0]}/{f6a[1]}  "
          f"F6b {f6b[0]}/{f6b[1]}={f6b[0]/f6b[1]:.1%}  平衡 {r['balanced']:.1%}  {dt:.0f}s")
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    ap.add_argument("--iters", type=int, default=100)
    ap.add_argument("--swapped", action="store_true")
    a = ap.parse_args()

    mode = "swapped(A=0/B随机)" if a.swapped else "normal(A随机/B=0，主流)"
    print("=" * 88)
    print(f"F6b 噪声底测量 · {mode} · {a.iters} 步 · 只改 seed")
    print("=" * 88)

    rows = [one(s, a.iters, a.swapped) for s in a.seeds]
    ok = [r for r in rows if not r.get("failed")]
    out = HERE / f"results/noise-{'swapped' if a.swapped else 'normal'}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2))

    if len(ok) >= 2:
        f6b = [r["f6b"][0] / r["f6b"][1] for r in ok]
        bal = [r["balanced"] for r in ok]
        print(f"\n{'-'*88}")
        print(f"F6b     min {min(f6b):.1%}  max {max(f6b):.1%}  "
              f"**极差 {max(f6b)-min(f6b):.1%}**")
        print(f"平衡准确率 min {min(bal):.1%}  max {max(bal):.1%}  "
              f"**极差 {max(bal)-min(bal):.1%}**")
        print("\n**极差就是噪声底**：任何小于它的差值都不能当信号。")
        print(f"（n={len(ok)}，极差本身也是低估 —— 更多次重复只会让它变大。）")
    print(f"\n→ {out}")


if __name__ == "__main__":
    main()
