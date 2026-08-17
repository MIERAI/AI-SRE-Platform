"""把 finetune/results/ 下所有评测结果汇总成一张表。

两个数据集分开报，因为**它们回答不同的问题**：

    test.jsonl        同分布测试集 —— F5 是语义留出，但形式与训练相同
    adversarial.jsonl 对抗集     —— F6a 形式留出（真注入）/ F6b 无害诱饵（应判 false）

**必须看平衡准确率 (召回+特异性)/2**，不能看总准确率：
偏向某一类的常数倾向会在对应子集上「恰好正确」，
未微调 4B 的 F6b 93.8% 和微调 4B 的 F6a 100% 都是这种假象。

    uv run finetune/summarize.py
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent
RES = HERE / "results"

# 展示顺序与人类可读名
KNOWN = [
    ("baseline-4b.json", "未微调 4B (MLX 4bit)"),
    ("baseline-4b-ollama.json", "未微调 4B (Ollama Q4_K_M)"),
    ("baseline-14b.json", "未微调 14B (Ollama)"),
    ("tuned-v1-4b.json", "微调 4B · v1 300步 s20"),
    ("tuned-v2-4b.json", "微调 4B · v2 ckpt100 s20"),
    ("tuned-v2b-4b.json", "微调 4B · v2b 300步 s4"),
    ("adv-base-4b.json", "未微调 4B (MLX 4bit)"),
    ("adv-base-14b.json", "未微调 14B (Ollama)"),
    ("adv-tuned-4b.json", "微调 4B · v1 300步 s20"),
    ("adv-tuned-v2-4b.json", "微调 4B · v2 ckpt100 s20"),
    ("adv-tuned-v2b-4b.json", "微调 4B · v2b 300步 s4"),
    ("adv-nomask.json", "  ├ 同上但 mask=false"),
    ("adv-fused-deq.json", "  ├ 同上 fuse→bf16"),
    ("adv-fused-4bit.json", "  └ 同上 fuse→4bit ⚠"),
]


def load(name: str) -> dict | None:
    p = RES / name
    return json.loads(p.read_text()) if p.exists() else None


def rates(e: dict) -> tuple[float, float, float]:
    """返回 (召回, 特异性, 平衡准确率)。"""
    tp, fp, fn, tn = e["tp"], e["fp"], e["fn"], e["tn"]
    rec = tp / (tp + fn) if tp + fn else float("nan")
    spec = tn / (tn + fp) if tn + fp else float("nan")
    return rec, spec, (rec + spec) / 2


def table(names: list[tuple[str, str]], title: str, fam_cols: list[tuple[str, str]]):
    got = [(lbl, e) for f, lbl in names if (e := load(f))]
    if not got:
        return
    print(f"\n{'='*104}\n{title}\n{'='*104}")
    head = f"{'配置':<26}"
    for _, cn in fam_cols:
        head += f"{cn:>12}"
    head += f"{'召回':>8}{'特异性':>9}{'平衡准确率':>12}{'延迟':>9}"
    print(head)
    print("-" * 104)
    for lbl, e in got:
        line = f"{lbl:<26}"
        for key, _ in fam_cols:
            v = e["by_family"].get(key)
            line += f"{(f'{v[0]}/{v[1]}' if v else '—'):>12}"
        rec, spec, bal = rates(e)
        line += f"{rec:>8.1%}{spec:>9.1%}{bal:>12.1%}{e['median_latency_ms']:>8.0f}ms"
        if e.get("unparsed"):
            line += f"  解析失败{e['unparsed']}"
        print(line)


def main():
    print("Phase 5 · 注入识别任务 · 全部评测结果汇总")

    table(KNOWN[:6], "① 同分布测试集 test.jsonl（83 条）—— F5 是【语义】留出，形式同训练",
          [("F1_谎报正常", "F1谎报"), ("F2_指挥破坏", "F2指挥"),
           ("F3_压制排查", "F3压制"), ("F4_嫁祸", "F4嫁祸"),
           ("F5_诱导泄露", "★F5留出"), ("clean", "clean")])

    table(KNOWN[6:], "② 对抗集 adversarial.jsonl（64 条）—— F6a【形式】留出 / F6b 无害诱饵",
          [("F6a_形式泛化", "★F6a真注入"), ("F6b_无害诱饵", "★F6b应false")])

    print("\n" + "-" * 104)
    print("读法：")
    print("  · ① 表几乎没有分辨力：14B 与两个 s20 微调模型都是 100%。")
    print("    **差异只在 ② 对抗集里出现** —— 这就是为什么必须造对抗集。")
    print("  · 平衡准确率 = (召回+特异性)/2。单看一侧会被「常数倾向」骗：")
    print("    未微调 4B 的 F6b 93.8% 是免费的（它本来就倾向 false，基线召回仅 31%）；")
    print("    v1 微调的 F6a 100% 同理（凡自然语言即 true，在全是真注入的 F6a 上恰好全对）。")
    print("  · ⚑ **上表每一行都是单次运行的点估计**，而噪声底实测为：")
    print("      100 步：F6b 极差 59.4 点 / 平衡准确率 18.8 点")
    print("      300 步：F6b 极差 15.6 点 / 平衡准确率 10.9 点   （同数据同超参，只改 seed）")
    print("    **小于噪声底的差值一律不能当信号。** 见 noise_floor.py 与 phase5-why.md §9。")
    print("    带区间重裁后：")
    print("      微调有效（81.2–92.2% vs 未微调 64.1%）              可信")
    print("      v2 数据优于 v1（F6b 78.1–93.8% vs 34.4%）           可信")
    print("      「4B 超过 14B」（81.2–92.2% vs 82.8%）              **不能声称**")
    print("      300 步优于 100 步（均值 88.0% vs 74.5%）            趋势明显，n=3 不显著")
    print("      scale 20/4 的质量差、A/B 初始化优劣                 **不能判定**")
    print("  · 14B 与未微调 4B 无训练随机性（纯推理 temp=0），其数字是精确值。")
    print("  · ⚠ fuse→4bit 那行是**确定性**结果：F6a 87.5%→50.0%（-37.5 点）。")
    print("    ΔW 量级小于 4bit 量化步长，被重新量化吞掉 -> **不要 fuse 回 4bit**。")
    print("  · mask=false 那行落在 mask=true 的噪声区间内 -> 无可检测差异。")
    print("  · 延迟差异含义：4B 约 470–545ms、14B 约 1030ms；24GB 上 14B 常驻会挤掉主模型。")


if __name__ == "__main__":
    main()
