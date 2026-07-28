# AI Engineer 学习路线 · v3（Claude Code 实操版）

> 基于《AI Engineer 学习指导手册 v2.0》改写。v2 的定位是"给任何 AI 复制粘贴的提示词手册"，
> v3 的定位是**在 Claude Code 里直接做的施工图 + 进度台账**。
>
> **这份文档是活的**：每完成一项就勾掉 `[ ]`，每个阶段结束在文末《学习日志》追加一条。
> 隔了两周回来，只看《当前进度》一节就知道站在哪。

---

## 📍 当前进度

| 项 | 值 |
|---|---|
| **当前阶段** | Phase 1 · Prompt Engineering + Function Calling |
| **状态** | 🏗️ 进行中 |
| **上次更新** | 2026-07-28 |
| **下一步动作** | 手写 Function Calling 完整循环（工具执行 + 结果回灌 + 多轮），这是 Phase 2 Agent 的骨架 |

**Phase 0 已暂停** ⏸️（2026-07-28）：跳 1 完成，追问 ①④⑥⑧ 结案，核心目标（看得见模型内部）已达成。
未做完的留在下面，随时可回来补：追问 ②③⑤⑦、对读 nanoGPT、跳 2（BPE + TinyStories）。

进度总览：

| 阶段 | 内容 | 周期 | 状态 |
|---|---|---|---|
| **Phase 0** | 从零训小 GPT（MLX，10–50M 参数） | 2–3 天 | ⏸️ 暂停（跳 1 完成，追问 ②③⑤⑦ 与跳 2 待补） |
| **Phase 1** | Prompt · Function Calling · Structured Output | 2 周 | 🏗️ 进行中 |
| **Phase 2** | Agent：LangGraph · Agents SDK · MCP | 4 周 | ⬜ |
| **Phase 3** | 企业级 RAG（Runbook / Postmortem） | 3 周 | ⬜ |
| **Phase 4** | Evaluation：Ragas · DeepEval | 2 周 | ⬜ |
| **Phase 5** | LoRA / QLoRA（源码级，非浅尝） | 1.5 周 | ⬜ |
| **Phase 6** | 生产部署：推理引擎 · K8s · 监控 | 3 周 | ⬜ |

状态图例：🔜 未开始 · 🏗️ 进行中 · ✅ 完成 · ⏸️ 暂停 · ⬜ 未排期

---

## 🎯 硬约束与已定决策

**设备**：MacBook Pro 14" · M4 Pro · 24GB 统一内存 · macOS Tahoe 26.5.2

**没有其他 GPU 资源**——无公司 GPU 集群，暂不租云 GPU。这条直接改写了 Phase 6，见该章。

已定的四条决策（相对 v2 手册的修改）：

| # | v2 手册 | v3 决策 | 理由 |
|---|---|---|---|
| ① | 无预训练内容 | **新增 Phase 0**，2–3 天训小 GPT | 训生产级模型不可能（需 ~1T token），但 10–50M 参数玩具模型在 M4 Pro 上几小时跑完。后面 KV cache / LoRA 低秩假设 / PagedAttention 全部建立在这上面 |
| ② | Phase 6 用 vLLM 实战 | **改为架构演练**：kind + llama.cpp server | vLLM 在 Apple Silicon 只有 CPU 后端，测不出真实 GPU 性能。学得到架构和监控链路，学不到调优 |
| ③ | 每节给"复制给 AI 的提示词" | **全部删除** | 在 Claude Code 里能直接读代码、跑训练、翻框架源码，不需要中间层 |
| ④ | LoRA "浅学，跑通就行" | **加厚到源码级**，1 周→1.5 周 | "80% 项目不需要微调"这个判断对，但本人明确要学 Llama/Qwen/DeepSeek 微调，且学习方式要求读到实现层 |

---

## 🔁 每个阶段的固定三道工序

这是这份路线和普通教程的唯一区别，**任何阶段都不许跳 ② 和 ③**：

```
① 跑通    最小可运行实现，不抄现成 demo
② 拆源码  读框架关键实现，回答"为什么这么设计 / 为什么不是另一种设计"
③ 落仓    代码进主仓库对应目录 + docs/ 写下 ② 的答案
```

只会 `graph.add_node(...)` 等于没学。② 里的追问清单每个阶段都列好了，那是这份文档最值钱的部分。
③ 产出的 `docs/` 会自然长成技术博客素材，也是 2027 年这个仓库最有说服力的部分。

---

## 🏛️ 主仓库结构（终点形态）

```
AI-SRE-Platform/
├── agent/          ← Phase 2   LangGraph ReAct 主循环、工具注册
├── rag/            ← Phase 3   Runbook 索引、混合检索、Reranker
├── mcp/            ← Phase 2   K8s MCP Server
├── evaluation/     ← Phase 4   Ragas / DeepEval 测试集与报告
├── finetune/       ← Phase 5   MLX LoRA 脚本与数据集
├── deployment/     ← Phase 6   推理服务、Dockerfile
├── kubernetes/     ← Phase 6   Deployment / KEDA / ServiceMonitor
├── monitoring/     ← Phase 6   Prometheus rules、Grafana dashboard JSON
├── dashboard/      ← Phase 6   前端（最后做）
├── labs/           ← 原理实验区，不属于产品
│   └── 00-nano-gpt/    ← Phase 0
└── docs/           ← 每阶段的"为什么"答案 + 本文档
```

**从第一天就是这个仓库**，逐阶段往里长，不在最后拼装。`labs/` 放原理实验，
它们不进产品目录但要留着——那是"我真的懂"的证据。

---

## Phase 0 · 从零训一个小 GPT

**周期** 2–3 天 · **状态** 🔜 未开始 · **产出** `labs/00-nano-gpt/`

不是为了得到能用的模型，是为了**后面五个阶段都在"看得见模型内部"的状态下学**。

### 目标

在 M4 Pro 上用 MLX 从零训一个 10–50M 参数的字符级/BPE GPT，跑 TinyStories 级数据，
看到 loss 从 ~10 降到 ~1.5，能生成语法通顺的短故事。

### ① 跑通

**两跳策略**（2026-07-28 定）：先用小语料 + char-level 换取"改一行→几分钟看结果"的反馈速度，
把链路和对照实验做完，再换 BPE 上 TinyStories。直接上 TinyStories 的话一次实验一小时，
`去掉 warmup 会怎样` 这类对照实验根本做不起。

**跳 1 · tinyshakespeare(1.1MB) + char-level**

- [x] 环境：uv + Python 3.12 + `mlx 0.32`，确认 `Device(gpu, 0)` 可用
- [x] 数据：char-level tokenizer，vocab=65，1.1M tokens → `data.py`
- [x] 模型：手写 GPT（合并 QKV 投影 / 多头 / Pre-LN / 因果掩码），**未用任何现成 Transformer 组件** → `model.py`
- [x] sanity check：随机初始 loss 4.20 ≈ ln(65)=4.17 ✅
- [x] 实证因果掩码：改动 t=4 之后的 token，位置 0–3 输出差异精确为 0 ✅
- [x] 训练：AdamW + warmup + cosine，loss/lr 落 CSV → `train.py`
- [x] 采样：greedy / temperature / top-k
- [x] 正式跑 3000 steps（10.7M 参数）→ **val 最低 1.4635 @ step 1750，之后过拟合到 1.6012**
      生成样例有正确的剧本格式和角色名。教训：1.1M 字符喂 10.7M 参数 = 数据不够，模型在背书
- [x] 加 checkpoint：只存 val 最优权重（base 那次跑最优权重没留住，是真实的工程漏洞）
- [x] KV cache 实现 + 正确性验证（greedy 下有无 cache 输出完全一致；去掉位置偏移则静默退化）
- [x] top-p 核采样
- [x] KV cache 加速比实测 → `bench_kvcache.py`：**只有 3.3x（理论 128x）**，由此挖出解码是
      memory-bandwidth-bound，并从第一性原理预测出 deepseek-r1:14b 的 22 tok/s（误差 10%）
- [x] 对照实验 2×2×2：LN 位置 × warmup × lr → `ablation_ln.py`（含恒定 lr 的干净对照）

**跳 2 · TinyStories + BPE**

- [ ] 换 tiktoken GPT-2 BPE，重训，对比同参数量下的生成质量
- [ ] 位置编码从可学习绝对位置换成 RoPE，对比外推能力

### ② 拆源码 · 设计追问

每一条都要在 `docs/phase0-why.md` 里写出答案，不是背结论，要能说清"不这么做会怎样"：

- [x] **① Tokenizer 三角权衡** —— 已结案，同语料实测：char(65 词表/1.12M tokens)、word(13k/263k，45.3% 词只出现一次)、BPE(11.7k/338k)。关键结论：BPE 与 char 共有**闭包性**（字节回退，永不 OOV），word-level 独缺；小模型必须用小词表的真正原因是**参数预算**（BPE 嵌入层 450 万参数 > 整个模型）；char-level 的真实代价是**有效上下文缩水 3.3 倍**，不是速度
- [ ] **Attention**：为什么是 Q/K/V 三个投影而不是两个？多头相比单头到底多了什么（不是"关注不同方面"这种空话，从矩阵秩的角度说）
- [x] **④ Causal mask → KV cache** —— 已结案。训练能并行需要两个条件（无位置依赖 + teacher forcing，后者带来 exposure bias）；缓存 K/V 的判据是**复用性**不是不可变性（过去的 Q 同样不变，但再也用不上）；实证掩码差异精确为 0；有无 cache 输出等价测试通过
- [x] **⑥ Pre-LN vs Post-LN** —— 已结案。Pre-LN 的 `I + J_f` 是梯度直通车；Post-LN 每层乘一次 LN 雅可比，随深度指数变化。**Pre-LN 的价值是拉宽可用 lr 范围**，不是效果更好（Post-LN+warmup 在 lr=1e-3 下反而最优 1.975）。代价：残差流方差累加，深层被稀释
- [ ] **位置编码**：绝对位置编码 → RoPE，RoPE 解决了什么绝对编码解决不了的问题？为什么它能外推
- [x] **⑧ LR schedule / warmup** —— 已结案，2×2×2 对照 + 恒定 lr 干净复核。**warmup 防的是早期不可逆损伤，不是加速收敛**：无 warmup 组头 50 步全部趴在塌缩值 3.3 附近，Pre-LN 能爬出来，Post-LN 爬不出来。lr=6e-3 时 Post-LN 两组皆死
- [ ] 对照阅读 karpathy/nanoGPT 的 `model.py`，找出你的实现和它的每一处差异，解释谁对

### ③ 落仓

- [ ] 代码进 `labs/00-nano-gpt/`
- [ ] `docs/phase0-why.md` 写完上面 7 条
- [ ] loss 曲线图 + 生成样例进 README

### 检查清单（通过才进 Phase 1）

- [ ] 能徒手在白板上画出一个 Transformer block 的完整数据流和张量形状变化
- [ ] 能解释 KV cache 缓存的到底是什么、为什么可以缓存、显存占用怎么算
- [ ] 训练 loss 正常下降，生成的文本语法通顺

---

## Phase 1 · Prompt Engineering + Function Calling

**周期** 2 周 · **状态** ⬜ · **产出** `agent/parser/`（告警解析模块）

v2 手册的定位没问题：这是地基。但内容要从"技巧罗列"改成"机制理解"。

### ① 跑通

> **环境约束**：无 API key，全程本地 Ollama。原计划的「Anthropic API vs Ollama 对比」改为
> 「qwen3:14b vs deepseek-r1:14b 对比」—— 结果反而更有料，见 ② 的实测发现。

- [x] 本地模型：`qwen3:14b`（9.3GB）已就绪；`deepseek-r1:14b` 已有
- [x] 20 条测试告警就绪 → `agent/parser/testdata/alerts.jsonl`，含 8 条难例
      （resolved 误判 / 信息不足 / 截断 / 提示词注入 / JSON 转义 / 根因在上游 / 日语 / 多故障）
- [x] 目标 schema → `agent/parser/schema.py`（一物三用：prompt / 约束解码 / 校验）
- [x] 写抽取 Prompt，跑 20 条出通过率 → `agent/parser/extract.py`
      三轮迭代 v1→v2a→v2b→v2c，全对 **16→18→19/20**，格式全程 100%。
      第一轮 4 个失败项 **0 个是模型能力问题**：2 个我的 prompt bug、1 个 schema 结构缺陷、
      1 个我的答案键错。枚举 v1 有 40% 落 Unknown → 按实测分布重设为 16 类
- [x] 约束解码价值量化：**收益 ≈ 基线不合规率**。T=0 收益为 0；T=1.6 约 1.7%（1/60 次枚举越界）。
      内容质量差异全在 **±2/20 的噪声**内 —— 先量噪声再解读，我的第一版解读被自己推翻
- [ ] 手写 Function Calling 循环：工具定义 → tool_call → 执行 → 结果回灌 → 最终回答
- [ ] `nomic-embed-text`（Phase 3 才需要）

### ② 拆源码 · 设计追问

- [x] **Function Calling 在 API 层传了什么** —— 已结案。读 qwen3 的 chat template + 手写同样的
      system prompt 绕过 `tools` 参数，拿到完全相同的语义输出。**它就是 prompt 工程 + 输出端字符串解析**。
      三个推论：工具定义占 system prompt token；`tool_calls` 是解析产物会失败；**`tool` 角色被渲染成
      `user` 消息 → 提示词注入攻击面**
- [x] **"支持工具"是模型能力还是模板能力** —— 已结案。deepseek-r1 模板 0 处提及 tool，被 API 层拒绝；
      手写 prompt 绕过后语义正确但格式错误（用了 ` ```json ` 而非 `<tool_call>`）。**= 模板槽位 + 训练语法**
- [x] **Structured Output 两条路线** —— 已结案。在 Phase 0 的莎士比亚模型上自己实现了约束解码
      （`labs/00-nano-gpt/constrained.py`）：18 步里 17 步只有 1 个合法 token，模型自发产出该串的
      概率 7.4e-19。**保证来自采样器不来自模型**。副产品：「模型给合法集的概率质量」可作生产监控指标
- [ ] ⚠️ **未解决**：约束解码下 deepseek-r1 的字符串字段被系统性污染（5 个不同错误值），
      qwen3 完全正常。两个机制假设（off-distribution thinking / token healing）**都被实验否证**。
      要往下查需要 token 级 logprobs → llama.cpp `--logits-all`
- [ ] 接 Phase 0：temperature / top-p 具体怎么影响 JSON 稳定性？从你自己写的采样代码解释
- [ ] 为什么模型会输出 ` ```json ` 包裹？和训练数据分布的关系
- [ ] CoT 为什么有效——是真推理还是给了更多计算步？（读一下相关质疑论文，别只信厂商说法）

### ③ 落仓

- [ ] 告警解析模块进 `agent/parser/`，带 20 条测试用例
- [ ] `docs/phase1-why.md`

### 检查清单

- [x] 20 条测试全部 `json.loads()` 成功（20/20，且 4 个配置 × 3 个温度下格式通过率均为 100%，
      唯一一次失败是 T=1.6 下的枚举越界 `severity='error'`）
- [x] 能说清约束解码和 prompt 约束的本质区别，并说出各自代价 → `docs/phase1-why.md`
- [x] 能画出 Function Calling 完整时序图，标明哪一步在模型侧、哪一步在你的代码侧
      → 已用 A/B 对照实证：手写 system prompt 可复现 `tools` 参数的全部效果

---

## Phase 2 · Agent 开发（核心阶段）

**周期** 4 周 · **状态** ⬜ · **产出** `agent/` + `mcp/`

四周分配：Week 1 LangGraph 基础 → Week 2 源码周 → Week 3 MCP → Week 4 K8s Agent v1

### ① 跑通

- [ ] LangGraph ReAct Agent，≥3 个工具（`read_file` / `run_command` 白名单 / `kubectl_get`）
- [ ] 加 Checkpointer（SQLite），杀掉进程后能从断点恢复
- [ ] 实现 Human-in-the-Loop：执行危险命令前 `interrupt`，等人工确认
- [ ] 用 OpenAI Agents SDK 把同一个 Agent 再写一遍，对比两者的抽象取舍
- [ ] Python MCP SDK 写一个 K8s MCP Server：`get_pods` / `get_logs` / `describe_node`
- [ ] 把这个 MCP Server 接进 Claude Code，实际调用成功

### ② 拆源码 · 设计追问（本阶段重头戏）

- [ ] **为什么是 StateGraph 而不是 DAG？** ReAct 本质是 while 循环，DAG 表达不了"不知道要循环几次"。那 LangGraph 用什么模型表达？→ 去读它的 **Pregel** 实现（`langgraph/pregel/`）。Pregel 是 Google 的图计算模型，BSP superstep——搞明白一个 superstep 里发生了什么
- [ ] **Channel 和 Reducer**：为什么 state 更新要写成 `Annotated[list, add]` 而不是直接赋值？多个节点并发写同一个 key 时会发生什么？读 `channels/` 目录
- [ ] **Checkpointer 为什么是必需品而不是可选功能？** 列出它同时解决的四件事（崩溃恢复、HITL、time travel 调试、多轮会话），并说明如果没有它，HITL 要怎么实现、代价是什么
- [ ] **interrupt 的实现机制**：暂停一个正在跑的图，本质上是"保存状态 + 抛异常"，恢复是"从 checkpoint 重放"。去代码里验证这个猜想对不对
- [ ] **MCP 协议层**：它是 JSON-RPC 2.0 over stdio/SSE。抓一次完整会话——`initialize` 握手协商了什么？`tools/list` 返回的 schema 和 Phase 1 的 tools 字段是什么关系？为什么说"写一次工具所有模型复用"，这个复用发生在哪一层？
- [ ] MCP 相比普通 Function Calling，多出来的成本是什么？（进程管理、序列化开销、调试难度）——什么场景下不该用 MCP

### ③ 落仓

- [ ] `agent/` 主循环 + 工具注册
- [ ] `mcp/k8s-server/`
- [ ] `docs/phase2-langgraph-internals.md`（Pregel/Channel/Checkpoint 三篇）
- [ ] `docs/phase2-mcp-protocol.md`

### 检查清单

- [ ] 能解释 Pregel superstep 模型，以及 LangGraph 为什么选它
- [ ] Agent 能自主完成 ≥3 步的任务
- [ ] 杀进程后能从 checkpoint 恢复，状态无丢失
- [ ] 自己写的 MCP Server 在 Claude Code 里被实际调用
- [ ] K8s Agent v1：输入告警 JSON，输出根因分析报告

---

## Phase 3 · 企业级 RAG

**周期** 3 周 · **状态** ⬜ · **产出** `rag/`

不做 PDF 聊天。知识库用真实运维材料：Runbook > Postmortem > K8s 最佳实践 > 告警规则说明。

> **语料决策（2026-07-28 定）**：先用 **K8s 官方文档 + CNCF / 公开 Postmortem 集**起步，
> 公司真实 Runbook 后续拿到再增量补进知识库。
> 因此 `rag/` 的索引流程从一开始就要设计成**可增量加载多来源语料**（source 字段区分公开/内部），
> 而不是写死一个目录——避免后面补料时重构。

### ① 跑通

- [ ] 完整 pipeline：加载 → 按段落切片（不是固定长度）→ Embedding → Chroma → 检索 → 回答
- [ ] 回答必须标注来源 `[文档名 · 第X段]`；无答案时明确说"未找到相关 Runbook"
- [ ] **混合检索**：向量 + BM25，对比单独用向量的召回率
- [ ] 加 Reranker（cross-encoder），Top-20 重排取 Top-3
- [ ] 封装成 Agent 工具 `search_runbook(query)` 接进 Phase 2 的 Agent
- [ ] 同一条告警，加 RAG 前后的回答质量对比（留证据，Phase 4 要用）

### ② 拆源码 · 设计追问

- [ ] **Embedding 为什么能做语义检索？** 从对比学习的训练目标解释，不是"它把语义变成向量"这种同义反复
- [ ] **向量索引**：Chroma 底层是 HNSW。HNSW 的多层图结构为什么比暴力搜索快？`M` 和 `ef_construction` 怎么权衡召回率和速度？——**这是精确近邻还是近似近邻，代价是什么**
- [ ] **BM25 的公式**里为什么有词频饱和项（saturation）？为什么不用朴素 TF-IDF
- [ ] **Reranker 为什么更准**：cross-encoder 和 bi-encoder 的本质区别（交互发生在编码前还是编码后），以及为什么不能直接用 cross-encoder 检索全库
- [ ] 切片策略：为什么"按段落切"对 Runbook 更好？语义切片 / 父子文档检索是在解决同一个问题吗

### ③ 落仓

- [ ] `rag/` 完整模块
- [ ] `docs/phase3-why.md` + 混合检索前后的召回率数字

### 检查清单

- [ ] 能解释 HNSW 为什么快、近似的代价在哪
- [ ] 混合检索相比纯向量，召回率有可量化提升
- [ ] RAG 作为工具接进 Agent，告警报告里包含 Runbook 内容
- [ ] 能说出 RAG 的 4 个常见失败模式及对策

---

## Phase 4 · Evaluation 评测体系

**周期** 2 周 · **状态** ⬜ · **产出** `evaluation/`

从 Demo 走向生产的分水岭，也是面试最容易拉开差距的地方。

### ① 跑通

- [ ] 手工构造 30 条运维问答测试集（question / ground_truth / contexts）
- [ ] Ragas 跑出四项指标：Context Recall · Context Precision · Faithfulness · Answer Relevancy
- [ ] 按评测结果改进 RAG，拿到改进前后的对比数字
- [ ] DeepEval 对比两个 System Prompt 下 Agent 的决策质量
- [ ] 接进 CI：每次改动自动跑评测，指标掉了就失败

目标线：Context Recall > 0.8 · Context Precision > 0.7 · Faithfulness > 0.9 · Answer Relevancy > 0.8

### ② 拆源码 · 设计追问

- [ ] **Ragas 的指标到底怎么算的？** 去读源码里 LLM-as-judge 的实际 prompt。Faithfulness 是把回答拆成 statement 再逐条判断有没有 grounding——看它是不是这么做的
- [ ] **LLM-as-judge 可信吗？** position bias、verbosity bias、self-preference bias 各是什么，怎么缓解
- [ ] 为什么 Context Recall 需要 ground truth 而 Faithfulness 不需要？这决定了哪些指标能在线上无标注地跑
- [ ] 评测本身要花多少 token / 时间？在 CI 里跑的成本模型

### ③ 落仓

- [ ] `evaluation/` 测试集 + 脚本 + CI 配置
- [ ] `docs/phase4-why.md`

### 检查清单

- [ ] 四项指标有具体数字，且改进前后有对比
- [ ] 能解释每项指标怎么算出来的（到 prompt 级别，不是概念级别）
- [ ] CI 里能自动跑，指标回退会拦住

---

## Phase 5 · LoRA / QLoRA（源码级）

**周期** 1.5 周 · **状态** ⬜ · **产出** `finetune/`

> v2 手册说"浅学，跑通就行"——这个建议对多数人成立（企业里 80% 项目不需要微调），
> 但对本路线不成立：明确要学 Llama/Qwen/DeepSeek 微调，且必须读到实现层。
> 位置保持在 Phase 4 之后不动——**没有评测体系就判断不了微调有没有效果**。

### ① 跑通

- [ ] MLX 下载 `Qwen3-4B` 的 MLX 版本
- [ ] 生成 100+ 条 K8s 运维 Q&A 训练数据（JSONL），比手册的 30 条更能看出效果
- [ ] `mlx_lm.lora` 跑 LoRA 微调 500 steps，loss 正常下降
- [ ] **用 Phase 4 的评测体系量化微调前后的差异**，而不是肉眼看两个回答
- [ ] 扫 rank ∈ {4, 8, 16, 64}，画出效果 / 训练时间 / 显存的曲线
- [ ] 试一次 QLoRA（14B 4bit），确认 24GB 能不能撑住

### ② 拆源码 · 设计追问

- [ ] **低秩假设为什么成立？** ΔW 真的是低秩的吗——读 LoRA 原论文和"intrinsic dimensionality"那条线索
- [ ] **为什么 B 初始化为 0 而 A 用高斯？** 反过来行不行，为什么
- [ ] **alpha / rank 的缩放系数**为什么重要？为什么调 rank 时通常要同步调 alpha 保持比值
- [ ] **LoRA 注入到哪些层？** 只给 q_proj/v_proj 和给全部 linear 层，差别多大？为什么早期论文只选注意力投影
- [ ] **peft / mlx-lm 是怎么把 LoRA 塞进 `nn.Linear` 的？** 读实现——是替换 Module 还是 hook 还是 monkey patch
- [ ] **QLoRA 三件套**：NF4 量化为什么比 int4 好、double quantization 省了多少、paged optimizer 解决什么
- [ ] 接 Phase 0：为什么微调改的是权重、而 RAG 和 Prompt 改的是输入？三者的作用位置画在一张图上

### ③ 落仓

- [ ] `finetune/` 数据集 + 训练脚本 + rank 扫描结果
- [ ] `docs/phase5-lora-internals.md`

### 检查清单

- [ ] 能说出 5 种"不需要微调，Prompt/RAG 能解决"的场景，并说清判断依据
- [ ] 微调前后有**评测数字**支撑，不是感觉
- [ ] 能讲清 LoRA 注入的代码路径（哪个类、哪个方法）

---

## Phase 6 · 生产部署

**周期** 3 周 · **状态** ⬜ · **产出** `deployment/` + `kubernetes/` + `monitoring/`

> ⚠️ **本阶段已按"只有 Mac"重新设计。**
> vLLM 在 Apple Silicon 只有 CPU 后端，PagedAttention 的性能收益、GPU 显存监控、
> 按 GPU 负载扩缩容——这些**在本机测不出真实数据**。
>
> 调整后的定位：**架构和可观测链路做真的，性能数字用公开 benchmark 替代 + 讲清原理**。
> 如果后续拿到 GPU（公司集群 / 租云），把标 🔶 的项目补做即可，其余不用改。

### ① 跑通

- [ ] `kind` 起本地 K8s 集群
- [ ] llama.cpp server（或 Ollama）容器化，写 Deployment YAML：资源限制 + liveness/readiness 探针
- [ ] **探针要探对东西**：LLM 服务的 readiness 不是端口通，是模型加载完且能返回一个 token——自己设计这个探针
- [ ] Prometheus + Grafana 装进 kind，ServiceMonitor 抓指标
- [ ] 暴露 LLM 专属指标：TTFT · Token Throughput · Queue Depth · Error Rate
- [ ] Grafana Dashboard 展示 SLO，JSON 存进 `monitoring/`
- [ ] KEDA ScaledObject 基于队列深度扩缩，压测触发扩容
- [ ] OpenTelemetry 打通 Agent 全链路追踪：一次告警处理经过 Agent→RAG→LLM 的完整 span
- [ ] 🔶 真 GPU 上跑 vLLM，对比 continuous batching 开关的吞吐差异

### ② 拆源码 · 设计追问

- [ ] **PagedAttention 到底解决什么？** 接 Phase 0 的 KV cache：为什么朴素实现要预分配 max_len 的显存、碎片率有多高、分页怎么解决。**Phase 0 认真做了的话这里应该秒懂**
- [ ] **continuous batching vs static batching**：为什么 LLM 推理特别适合前者？（不同请求生成长度差异巨大）
- [ ] **prefill vs decode 是两种完全不同的负载**：一个 compute-bound 一个 memory-bandwidth-bound。这解释了为什么 TTFT 和 TPOT 要分开看、为什么 batch size 对两者影响相反
- [ ] **为什么 LLM 服务的 HPA 不能按 CPU 扩？** 该按什么扩，为什么是队列深度
- [ ] LLM 服务的 SLO 该怎么定？和普通 Web 服务的 p99 延迟有什么本质不同（流式响应下"延迟"是什么）
- [ ] 冷启动问题：模型加载几十秒，扩容根本来不及——生产上怎么办

### ③ 落仓

- [ ] `deployment/` + `kubernetes/` + `monitoring/`
- [ ] `docs/phase6-llm-serving.md`
- [ ] `docs/phase6-mac-limitations.md`（诚实记录哪些没在真 GPU 上验证）

### 检查清单

- [ ] Pod 正常运行，自己设计的 readiness 探针有效
- [ ] Grafana 能看到 TTFT 和吞吐量
- [ ] 压测能触发 KEDA 自动扩容
- [ ] 能解释 PagedAttention 原理，并说清它和 Phase 0 里 KV cache 的关系
- [ ] `docs/` 里明确标注了哪些结论来自实测、哪些来自公开 benchmark

---

## 🎯 综合项目：AI SRE Assistant

整条路线的产出物，每个阶段往上长一层。

```
Prometheus 告警
     ↓  解析成结构化 JSON              [Phase 1]
     ↓  Agent 调 kubectl 查集群状态     [Phase 2]
     ↓  Agent 调 RAG 查 Runbook/历史故障 [Phase 3]
     ↓  LangGraph 多步推理 → 根因分析   [Phase 2]
     ↓  危险操作前 HITL 人工确认        [Phase 2]
     ↓  输出结构化 Postmortem 报告      [Phase 1]
     ↓  DeepEval 持续评测决策质量       [Phase 4]
     ↓  K8s 部署 + 全链路监控           [Phase 6]
```

| 阶段完成后 | 项目状态 |
|---|---|
| Phase 1 | 🌱 告警能解析成结构化数据 |
| Phase 2 | 🌿 能跑：ReAct Agent + kubectl + MCP Server |
| Phase 3 | 🌳 有用：接入 Runbook，有历史经验支撑 |
| Phase 4 | ✅ 工程化：决策质量有数字保证 |
| Phase 5 | ⭐ 加分：微调模型更懂自家运维规范 |
| Phase 6 | 🚀 完整：部署 + 监控 + 自动扩缩 |

---

## 📚 参考资源

**框架文档**

| 工具 | 地址 |
|---|---|
| MLX / mlx-examples | github.com/ml-explore/mlx-examples |
| nanoGPT（Phase 0 对照） | github.com/karpathy/nanoGPT |
| LangGraph | langchain-ai.github.io/langgraph |
| OpenAI Agents SDK | openai.github.io/openai-agents-python |
| MCP Python SDK | github.com/modelcontextprotocol/python-sdk |
| Ragas | docs.ragas.io |
| DeepEval | docs.confident-ai.com |
| vLLM | docs.vllm.ai |

**本机可用模型（M4 Pro 24GB）**

| 模型 | 用途 | 大小 |
|---|---|---|
| Qwen3-14B | 日常开发主力，中文强 | ~9GB Q4 |
| Qwen2.5-Coder-14B | 代码 / YAML 生成 | ~9GB Q4 |
| DeepSeek-R1-Distill-14B | 复杂推理、根因分析 | ~9GB Q4 |
| Qwen3-4B | Phase 5 微调练习 | ~2.5GB Q4 |
| nomic-embed-text | RAG Embedding | ~270MB |

> 💡 24GB 统一内存默认分给 GPU 的上限约 16GB。跑 14B + embedding + 应用同时吃紧时，
> 可用 `sudo sysctl iogpu.wired_limit_mb=20480` 抬高上限（重启失效，用前先确认当前值）。
> 更大的 MoE 模型（如 Qwen3-30B-A3B，Q4 约 17–18GB）理论上能跑但会很紧，不建议作为主力。

---

## 📝 学习日志

每个阶段结束追加一条。格式：日期 / 阶段 / 实际花了多久 / 最大的收获 / 踩的坑 / 还没搞懂的。

### 2026-07-28 · 路线制定
- 读完 v2 手册，确定四条修改：加 Phase 0、Phase 6 改架构演练、删提示词模板、LoRA 加厚
- 确认硬件约束：只有 M4 Pro 24GB，无外部 GPU
- 起点定为 Phase 0

### 2026-07-28 · Phase 0 跳 1 完成（同日）

**做了什么**
手写 GPT（零现成 Transformer 组件）→ char-level tokenizer → 训练循环 → KV cache →
2×2×2 LN/warmup 对照 → KV cache 基准 → 用第一性原理预测 14B 模型解码速度并验证。
10.7M 参数模型训练 3000 步 / 24 分钟，val 最低 1.4635。详见 `docs/phase0-why.md`。

**最大的收获**
从一个 10.7M 的玩具模型出发，预测出 14B 生产模型在本机的解码速度 22 tok/s，误差 10%。
路径：KV cache 只快 3.3x（理论 128x）→ 追查发现每步耗时几乎恒定 → 算带宽利用率
16%→68% 单调逼近 273 GB/s → 得出「解码是 memory-bandwidth-bound」→ 273÷9GB×效率 → 验证。
**Phase 0 不是"先玩玩小的"，是获得对大模型做定量预测的能力。**

**踩的坑（都是自己的代码）**
1. **对照实验改了两个变量，两次。** `--no-warmup` 连带改了整条 cosine 曲线；KV cache 规模
   实验同时改 `n_layer` 和 `n_embd`，得到非单调假象。两次都是重做才干净。
2. **训练没存 checkpoint。** val 在 step 1750 触底，跑到 2999 过拟合（val +9%，train −26%），
   最优权重没留住。已修：只存 val 最优。
3. **1.1M 字符喂 10.7M 参数 = 数据不够**，模型在背书。这是跳 2 的硬理由。
4. `tee` 的块缓冲吞掉后台训练日志，看不到进度。要 `PYTHONUNBUFFERED=1`。

**还没搞懂的**
追问 ②（QKV 为何合并）③（多头相比单头，从矩阵秩的角度）⑤（FFN 为何 4 倍）
⑦（RoPE 为何能外推）。还没对读 nanoGPT 源码。

### 2026-07-28 · Phase 1 开工（同日）

**做了什么**
读 chat template 看清 Function Calling 的真面目 → 手写 prompt 绕过 `tools` 参数做对照 →
在 Phase 0 的莎士比亚模型上自己实现约束解码 → 建 20 条告警测试集与目标 schema。
详见 `docs/phase1-why.md`。

**最大的收获**
**Function Calling 没有协议层魔法。** `tools` 数组被 chat template 序列化成纯文本塞进 System
Prompt，模型生成 `<tool_call>{...}</tool_call>` 文本，Ollama 在输出端做字符串解析。手写同样的
system prompt 能拿到完全相同的语义输出。由此推出三条会改变写 Agent 方式的结论，其中最重要的：
**`tool` 角色被渲染成 `user` 消息 —— 工具返回的不可信内容和用户指令处在同一信任级别。**

**踩的坑 / 意外**
1. **KV cache 跨窗口越界**（Phase 0 遗留 bug）。绝对位置编码烙进了缓存，没法滑窗丢最老的几个，
   只能整个缓存作废重算 —— 这是 RoPE 的动机之一。已修。
2. **约束解码下 deepseek-r1 的字符串字段被系统性污染**，5 个不同错误值，qwen3 完全正常。
   **我提的两个机制假设都被自己的实验否证了**（开 thinking 无效；换 enum 无效）。机制挂账，
   但「约束解码保证形式不保证内容」这条被三种方式独立证实。
3. 再次确认：`json.loads()` 成功 + schema 校验通过 = **什么都没保证**。这是 Phase 4 的存在理由。

**还没搞懂的**
约束解码污染的机制（需 token 级 logprobs，llama.cpp `--logits-all`）；
temperature/top-p 对 JSON 稳定性的具体影响；模型为何爱输出 ` ```json ` 包裹；CoT 是否真推理。

### 2026-07-28 · Phase 1 抽取跑分（同日）

**做了什么**
20 条告警 × 4 个配置 × 3 个温度 × 部分重复，共约 200 次模型调用。
三轮迭代把全对数从 16/20 推到 19/20，并量化了约束解码的真实收益。

**最大的收获（两条，都是反直觉的）**

1. **第一轮的 4 个失败项，0 个是模型的能力问题** —— 2 个是我的 Prompt 缺规则，
   1 个是 schema 把「现象」和「原因」挤进了同一个字段，1 个是我的答案键写错了
   （模型比我准确）。建评测集第一轮暴露的是**你自己的设计缺陷**。
2. **约束解码的收益 = 基线不合规率。** T=0 时 qwen3 已经 20/20 合法，收益为 0。
   「上生产就该开 structured output」这个默认建议在这个场景不成立。
   整个 Phase 1 里格式通过率从头到尾 100%，而"格式不稳定"恰恰是网上讲 Prompt
   Engineering 时篇幅最大的话题。

**踩的坑**
1. **把噪声当信号。** 看到 A/B 在高温下差 1~2 项，差点写下「约束解码保护内容质量」。
   同配置重复三次，噪声就是 ±2 项 —— 结论撤回。**先量噪声再解读差异。**
2. **枚举拍脑袋列。** v1 的 11 个类型有 40% 装不下实际数据。枚举要从数据分布反推。
3. **改 schema 语义 → 答案键必须同步重写。** v2c 拆分 symptom/cause 后 a17 的答案键失效。

**方法论沉淀**
v2a/v2b/v2c 的提升可信，因为每步都**预先预测了具体哪一条会被修好并精确命中**（机制归因）；
温度对比不可信，因为只看总分。**这两种证据强度差一个量级。**
今天在同一会话里踩了三次同类的坑（对照实验改两个变量 ×2、噪声当信号 ×1）。

<!-- 下一条从这里开始 -->
