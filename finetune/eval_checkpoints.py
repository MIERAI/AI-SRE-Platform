"""评测训练过程中的各个 checkpoint —— 看 **F5 泛化随训练步数怎么变**。

这是个免费的对照实验：`save_every: 100` 已经把中间权重存下来了，不用额外训练。

要回答的问题：**val loss 在 50 步就到 0.001，继续训到 300 步是在学什么？**
两种可能，只有 F5 曲线能分辨：

  · F5 随步数继续上升  -> 还在学「注入」这个概念，训练到底是对的
  · F5 先升后降        -> 过拟合确实损害泛化，应该早停（而 val loss 完全看不出来，
                          因为 valid 是从训练集切的同族同措辞）

⚑ mlx-lm 的 checkpoint 命名是 `0000100_adapters.safetensors`，而 `load()` 只认
  目录下的 `adapters.safetensors`。所以要为每个 checkpoint 建一个临时目录，
  把权重改名放进去，并**复制 adapter_config.json**（缺了它 load 会失败）。

    uv run finetune/eval_checkpoints.py finetune/adapters/r8
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent


def main():
    src = Path(sys.argv[1] if len(sys.argv) > 1 else "finetune/adapters/r8")
    if not (ROOT / src).is_dir():
        sys.exit(f"没有这个 adapter 目录：{src}")
    d = ROOT / src

    ckpts = sorted(d.glob("*_adapters.safetensors"),
                   key=lambda p: int(re.match(r"(\d+)", p.name).group(1)))
    final = d / "adapters.safetensors"
    items = [(int(re.match(r"(\d+)", p.name).group(1)), p) for p in ckpts]
    if final.exists() and (not items or final.stat().st_size):
        items.append(("final", final))
    print(f"{src} 下找到 {len(items)} 个 checkpoint：{[i for i, _ in items]}\n")

    rows = []
    for step, path in items:
        tmp = ROOT / "finetune/adapters/_ckpt_tmp"
        if tmp.exists():
            shutil.rmtree(tmp)
        tmp.mkdir(parents=True)
        shutil.copy(path, tmp / "adapters.safetensors")
        shutil.copy(d / "adapter_config.json", tmp / "adapter_config.json")

        save = ROOT / f"finetune/results/ckpt-{src.name}-{step}.json"
        proc = subprocess.run(
            ["uv", "run", "finetune/eval_detect.py", "--backend", "mlx",
             "--adapter", "finetune/adapters/_ckpt_tmp", "--save", str(save)],
            cwd=ROOT, capture_output=True, text=True)
        if not save.exists():
            print(f"  step {step}: 评测失败\n{proc.stdout[-800:]}{proc.stderr[-800:]}")
            continue
        e = json.loads(save.read_text())
        fam = e["by_family"]
        seen = [sum(fam.get(k, [0, 0])[0] for k in fam if k.startswith(("F1", "F2", "F3", "F4"))),
                sum(fam.get(k, [0, 0])[1] for k in fam if k.startswith(("F1", "F2", "F3", "F4")))]
        f5 = fam.get("F5_诱导泄露", [0, 1])
        cl = fam.get("clean", [0, 1])
        rows.append({"step": step, "total": e["total"], "seen": seen, "f5": f5,
                     "clean": cl, "unparsed": e["unparsed"]})
        print(f"  step {str(step):>5}  总计 {e['total'][0]}/{e['total'][1]}"
              f"  见过的四族 {seen[0]}/{seen[1]}  ★F5 {f5[0]}/{f5[1]}"
              f"  clean {cl[0]}/{cl[1]}  解析失败 {e['unparsed']}")

    shutil.rmtree(ROOT / "finetune/adapters/_ckpt_tmp", ignore_errors=True)

    print(f"\n{'='*78}\n{'步数':>8}{'见过的四族':>14}{'★F5(没见过)':>14}{'clean':>12}{'总准确率':>12}")
    print("-" * 78)
    for r in rows:
        print(f"{str(r['step']):>8}{f'{r['seen'][0]}/{r['seen'][1]}':>12}"
              f"{r['seen'][0]/max(r['seen'][1],1):>7.0%}"
              f"{f'{r['f5'][0]}/{r['f5'][1]}':>10}{r['f5'][0]/r['f5'][1]:>7.0%}"
              f"{f'{r['clean'][0]}/{r['clean'][1]}':>9}"
              f"{r['total'][0]/r['total'][1]:>12.1%}")

    out = ROOT / f"finetune/results/ckpt-curve-{src.name}.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    print(f"\n→ {out}")
    print("对照：未微调 4B 的 F5 = 8/24 = 33.3%，14B = 24/24 = 100%。")


if __name__ == "__main__":
    main()
