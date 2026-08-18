"""跨设备验证 Phase 0 的结论：**decode 是 memory-bandwidth-bound 吗？**

### 为什么需要跨设备

Phase 0 在单台 M4 Pro 上测出「prefill 是 compute-bound、decode 是
memory-bandwidth-bound」，并据此预测了 14B 的解码速度（误差 10% 内）。
但那是**同一台机器上的自证**：我用带宽算出速度，再用速度反推带宽成立。

现在有两台内存带宽差约 5 倍的设备，可以做一次**独立的、可证伪的检验**：

| | M4 Pro | Snapdragon 7+ Gen 2 (SM7475) |
|---|---|---|
| 内存带宽 | ~273 GB/s | ~51 GB/s (LPDDR5) |
| 比值 | | **约 5.3×** |

### 可证伪的预测

    若 decode 受内存带宽限制  ->  TPOT 比值 ≈ 5.3（与带宽比同量级）
    若 prefill 受算力限制     ->  TTFT 比值 ≠ 5.3（应明显不同）

**两条都要看。** 只看 TPOT 比值接近 5.3 是不够的 ——
如果 TTFT 比值也是 5.3，那说明差异来自某个全局因素（比如整机性能差 5 倍），
而不是「两种负载受不同资源限制」。**必须是两个比值分离，结论才成立。**

### 测量纪律（Phase 5 的教训）

1. **多轮取中位数并报极差** —— 小于极差的差异不是信号。
2. **检测降频** —— 手机跑久了会发烫降频，后几轮变慢会污染结果。
   脚本单独报「前半轮 vs 后半轮」的 TPOT，两者差异大就说明在降频。
3. **固定模型与量化** —— 比硬件必须固定软件，否则比的是模型不是带宽。
4. **预热** —— 首轮包含模型加载，必须丢弃（Phase 1 实测过冷/热会给出不同结果）。

    uv run deployment/bench_cross_device.py \
        --local http://localhost:11434 --remote http://10.122.94.11:11434 \
        --model qwen3:4b --rounds 6
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import time

import requests

PROMPT = ("List three common causes of a Kubernetes pod entering CrashLoopBackOff. "
          "Answer concisely.")


def measure(endpoint: str, model: str, n_predict: int, timeout: int = 600) -> dict | None:
    """一次流式生成，分别测 TTFT 与 TPOT。

    ⚑ TPOT 用**相邻 chunk 的间隔**算，不能用「总耗时 / token 数」——
      后者会把 prefill 的时间摊进 decode，把两种负载混成一个数字。
    """
    t0 = time.perf_counter()
    try:
        r = requests.post(f"{endpoint}/api/chat", json={
            "model": model,
            "messages": [{"role": "user", "content": PROMPT}],
            "stream": True, "think": False,
            "options": {"temperature": 0, "num_predict": n_predict},
            "keep_alive": "10m"}, timeout=timeout, stream=True)
        r.raise_for_status()
        ttft, stamps, ntok = None, [], 0
        for line in r.iter_lines():
            if not line:
                continue
            now = time.perf_counter()
            if ttft is None:
                ttft = now - t0
            stamps.append(now)
            try:
                d = json.loads(line)
                ntok += 1 if d.get("message", {}).get("content") else 0
                if d.get("done"):
                    srv = {k: d[k] for k in
                           ("total_duration", "load_duration", "prompt_eval_count",
                            "prompt_eval_duration", "eval_count", "eval_duration")
                           if k in d}
                    break
            except Exception:      # noqa: BLE001
                pass
        if ttft is None or len(stamps) < 3:
            return None
        tpot = (stamps[-1] - stamps[0]) / (len(stamps) - 1)
        return {"ttft": ttft, "tpot": tpot, "chunks": len(stamps),
                "tokens": ntok, "server": srv if "srv" in dir() else {}}
    except Exception as e:         # noqa: BLE001
        print(f"    ✗ {type(e).__name__}: {str(e)[:60]}")
        return None


def run(label: str, endpoint: str, model: str, rounds: int, n_predict: int) -> dict:
    print(f"\n▶ {label}  ({endpoint})")
    print("  预热一轮（含模型加载，丢弃）…")
    measure(endpoint, model, min(n_predict, 16))

    rows = []
    for i in range(rounds):
        m = measure(endpoint, model, n_predict)
        if m:
            rows.append(m)
            print(f"    第{i+1}轮  TTFT {m['ttft']*1000:7.0f}ms   "
                  f"TPOT {m['tpot']*1000:6.1f}ms   chunk {m['chunks']}")
    if not rows:
        return {}
    ttfts = [r["ttft"] for r in rows]
    tpots = [r["tpot"] for r in rows]
    half = max(len(tpots) // 2, 1)
    out = {
        "label": label, "n": len(rows),
        "ttft_med": st.median(ttfts), "ttft_range": max(ttfts) - min(ttfts),
        "tpot_med": st.median(tpots), "tpot_range": max(tpots) - min(tpots),
        "tpot_first_half": st.median(tpots[:half]),
        "tpot_second_half": st.median(tpots[half:]),
    }
    print(f"  TTFT 中位 {out['ttft_med']*1000:.0f}ms  极差 {out['ttft_range']*1000:.0f}ms")
    print(f"  TPOT 中位 {out['tpot_med']*1000:.1f}ms  极差 {out['tpot_range']*1000:.1f}ms")
    drift = out["tpot_second_half"] / max(out["tpot_first_half"], 1e-9)
    flag = "  ⚠️ 疑似降频/热节流" if drift > 1.25 else ""
    print(f"  前半轮 {out['tpot_first_half']*1000:.1f}ms → 后半轮 "
          f"{out['tpot_second_half']*1000:.1f}ms（×{drift:.2f}）{flag}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", default="http://localhost:11434")
    ap.add_argument("--remote", required=True)
    ap.add_argument("--model", default="qwen3:4b")
    ap.add_argument("--rounds", type=int, default=6)
    ap.add_argument("--n-predict", type=int, default=64)
    ap.add_argument("--bw-local", type=float, default=273.0, help="本地内存带宽 GB/s")
    ap.add_argument("--bw-remote", type=float, default=51.0, help="远端内存带宽 GB/s")
    a = ap.parse_args()

    print("=" * 78)
    print(f"跨设备验证：decode 是否受内存带宽限制   模型={a.model}")
    print("=" * 78)
    print("可证伪的预测：TPOT 比值 ≈ 带宽比值，而 TTFT 比值【明显不同】。")
    print("若两个比值都接近带宽比 -> 说明是整机性能差异，不能归因于「两种负载受不同资源限制」。\n")

    L = run("本地 (M4 Pro)", a.local, a.model, a.rounds, a.n_predict)
    R = run("远端 (手机)", a.remote, a.model, a.rounds, a.n_predict)
    if not L or not R:
        print("\n✗ 数据不足，无法比较")
        return

    bw_ratio = a.bw_local / a.bw_remote
    tpot_ratio = R["tpot_med"] / L["tpot_med"]
    ttft_ratio = R["ttft_med"] / L["ttft_med"]

    print(f"\n{'='*78}\n结果\n{'='*78}")
    print(f"  内存带宽比（M4 Pro / 手机）   {bw_ratio:6.2f}×   ← 预测的 TPOT 比值")
    print(f"  实测 TPOT 比值               {tpot_ratio:6.2f}×")
    print(f"  实测 TTFT 比值               {ttft_ratio:6.2f}×")

    # 极差决定分辨力：比值的不确定度必须小于我们想区分的差异
    rel_noise = (L["tpot_range"] / L["tpot_med"] + R["tpot_range"] / R["tpot_med"])
    print(f"\n  TPOT 相对极差合计 {rel_noise:.0%}  ← 小于此幅度的差异不能当信号")

    close = abs(tpot_ratio - bw_ratio) / bw_ratio < 0.4
    separated = abs(ttft_ratio - tpot_ratio) / max(tpot_ratio, 1e-9) > 0.3
    print("\n判定：")
    print(f"  ① TPOT 比值接近带宽比（±40%）      {'✅ 是' if close else '❌ 否'}")
    print(f"  ② TTFT 与 TPOT 的比值明显分离（>30%）{'✅ 是' if separated else '❌ 否'}")
    if close and separated:
        print("\n  → **两条都成立**：decode 受内存带宽限制这一结论在跨设备上被独立验证。")
    elif close and not separated:
        print("\n  → TPOT 比值虽接近带宽比，但 TTFT 比值也一样 ——")
        print("     **不能归因于内存带宽**，更可能是整机性能的整体差异。结论不成立。")
    else:
        print("\n  → TPOT 比值与带宽比不符。可能原因：量化格式不同、后端实现不同")
        print("     （llama.cpp 的 ARM NEON vs Metal 内核效率）、或手机在降频。")
        print("     **诚实记录，不要为了凑结论去挑参数。**")

    print("\n注：带宽数字来自公开规格而非实测（Apple/Qualcomm 均未提供可直接测量的接口），")
    print("    所以「±40%」这个judgement阈值本身是宽松的 —— 它只能区分「同量级」与「不同量级」。")


if __name__ == "__main__":
    main()
