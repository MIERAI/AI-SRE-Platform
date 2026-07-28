"""KV cache 加速比实测。

对照两条路径生成同样多的 token：
  use_cache=False  每步重算整个序列   O(N²)
  use_cache=True   prefill 一次 + 每步 1 token   O(N)
"""

import sys
import time
from pathlib import Path

import mlx.core as mx

sys.path.insert(0, str(Path(__file__).parent))
from model import GPT, GPTConfig  # noqa: E402


def timed(fn, warmup=1, runs=3):
    for _ in range(warmup):
        mx.eval(fn())
    ts = []
    for _ in range(runs):
        t = time.perf_counter()
        mx.eval(fn())
        ts.append(time.perf_counter() - t)
    return min(ts)


def main():
    cfg = GPTConfig(block_size=256, n_layer=6, n_head=6, n_embd=384)
    model = GPT(cfg)
    model.eval()
    mx.eval(model.parameters())
    prompt = mx.array([[1]])

    print(f"模型 {model.n_params():,} 参数 | block_size={cfg.block_size}\n")
    print(f"{'生成长度':>8}{'无 cache':>12}{'有 cache':>12}{'加速比':>10}"
          f"{'理论前向量比':>14}")

    for n in (32, 64, 128, 255):
        t_no = timed(lambda: model.generate(prompt, n, temperature=0, use_cache=False))
        t_yes = timed(lambda: model.generate(prompt, n, temperature=0, use_cache=True))
        # 理论：无 cache 累计前向 token 数 = 1+2+...+n；有 cache = n
        theory = sum(range(1, n + 1)) / n
        print(f"{n:>8}{t_no:>11.3f}s{t_yes:>11.3f}s{t_no / t_yes:>9.1f}x{theory:>13.1f}x")

    print("\n加速比达不到理论值是正常的 —— 解码时每步只有 1 个 token，"
          "\nGPU 严重欠载，瓶颈从算力变成了访存和 kernel 启动开销。"
          "\n这正是 continuous batching 存在的理由：把多个请求的解码步凑成一批。[Phase 6]")


if __name__ == "__main__":
    main()
