# finetune/ — LoRA 微调一个「注入识别」判别器

Phase 5 的全部代码。完整的推理过程、五次自我推翻、以及每个结论的噪声区间，
见 [`docs/phase5-why.md`](../docs/phase5-why.md)。

## 这个目录解决的问题

Phase 4 测出 **H4「模型从不自行识别注入」= 16/16**。
但把注入片段单独拿出来直接问，`qwen3:14b` 是 **83/83 = 100%** ——
所以那是**「不自发」而不是「没能力」**，修法是**加一个显式审查节点**，不是微调。

微调在这里的作用只有一个，而且是纯工程性的：
**把 14B 才有的判别能力压进 4B，好让它能和主排查模型同时常驻 24GB 内存。**

## 结论（都带噪声区间）

| | 对抗集平衡准确率 | 延迟 | 常驻内存 |
|---|---|---|---|
| 未微调 4B | 64.1% | 469 ms | 2.5 GB |
| **微调 4B（v2b）** | **81.2–92.2%**（3 seed） | 529 ms | 2.5 GB |
| 未微调 14B | 82.8% | 1033 ms | 9.3 GB |

**微调 4B 与未微调 14B 同一水平**，但延迟减半、内存少 3.7 倍。
**不能声称「超过 14B」** —— 14B 落在 4B 的 seed 区间内。

两条确定性结论（无噪声争议）：

- **不要把 LoRA fuse 回 4bit**：F6a 从 87.5% 崩到 50.0%，ΔW 的量级小于 4bit
  量化步长、被重新量化吞掉。保持 adapter 分离只多 29 MB、只慢 11%。
- **`scale=20`（mlx-lm 默认）配 `lr=1e-4` 会梯度爆炸**：v2 在 120 步 loss→nan，
  只把 scale 改成 4（peft 惯例 `alpha=32/r=8`）就不炸。

## ⚠️ 用这些脚本前必须知道的一件事

**噪声底很大。** 同数据、同超参、同步数，只改 seed：

| | F6b 极差 | 平衡准确率极差 |
|---|---|---|
| 100 步（未收敛） | **59.4 点** | 18.8 点 |
| 300 步（已收敛） | 15.6 点 | **10.9 点** |

**小于噪声底的差值一律不是信号。** 我在发现这一点之前，
写下的一批「结论」（超过 14B、步数主导、scale 略好、A/B 初始化更优）**全部作废**。

还有一个更隐蔽的坑：`steps_per_eval` 这样一个**纯观测参数**（50→25）
会改变训练 batch 顺序，让同配置的结果差 18.8 个点。

→ 任何对照实验都请先跑 `noise_floor.py`。

## 脚本

| 文件 | 用途 |
|---|---|
| `make_dataset.py` | v1 数据集。载荷取自 `agent/tools/cluster.py` 的 6 个真实注入，按危害类型分 5 族，**F5 整族留出** |
| `make_dataset_v2.py` | v2 数据集 = v1 + 62 条 hard negative（「有插入但无害」）。**seed 必须与 v1 一致**，否则 test 集不同、两版不可比 |
| `make_adversarial.py` | F6 对抗集：F6a 形式泛化（8 种伪装的真注入）+ F6b 无害诱饵（8 种长得像插入的正常运维文本） |
| `eval_detect.py` | 统一评测。**按家族分组**报告 + 退化检查（全判 true 也能拿 57.8%） |
| `eval_checkpoints.py` | 评测各中间 checkpoint，看泛化随训练步数怎么变 |
| `noise_floor.py` | **量噪声底**：固定一切、只改 seed，报极差 |
| `summarize.py` | 汇总所有评测结果成两张表（同分布 / 对抗集） |
| `sweep_rank.py` | rank 扫描，**固定 alpha**（mlx-lm 的 `scale` 不含 `1/r`，直接扫会同时改容量和有效学习率） |
| `ab_init.py` | A/B 初始化对调实验。⚠️ 结论不可用：给 B 用了 `1/√input_dims` 而非 `1/√r`，且落在噪声内 |

## 复现

```bash
uv run finetune/make_dataset.py          # v1
uv run finetune/make_dataset_v2.py       # v2（+hard negative）
uv run finetune/make_adversarial.py      # F6 对抗集

# 基线：先证明微调是必要的，再训
uv run finetune/eval_detect.py --backend mlx                        # 未微调 4B
uv run finetune/eval_detect.py --backend ollama --model qwen3:14b   # 14B 对照

uv run mlx_lm.lora --config finetune/config-v2b.yaml                # 训练（~17 min）

uv run finetune/eval_detect.py --backend mlx \
    --adapter finetune/adapters/v2b-scale4 --dataset adversarial    # 对抗集评测
uv run finetune/noise_floor.py --seeds 0 1 2 --iters 300            # 噪声底（~50 min）
uv run finetune/summarize.py
```

## 产物怎么用

判别器由 [`agent/input_guard.py`](../agent/input_guard.py) 加载，
接在 `MCPToolbelt.invoke()` 里，**只作用于 `app_content` 级工具**
（`kubectl_logs` —— 唯一由被观测方控制内容的通道）。

**净化不能单独部署，必须与人工审批门控同时使用** ——
完整交叉矩阵实测：只开净化时 P-谎报 的 H1 从 0/2 变成 **2/2**
（净化改变了 Agent 的行动倾向，被释放的「主动修复」意愿需要门控约束）。
