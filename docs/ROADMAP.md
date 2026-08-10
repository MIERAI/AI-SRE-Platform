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
| **当前阶段** | Phase 4 · Evaluation 评测体系 |
| **状态** | 🏗️ 进行中 —— 主要产出已成独立报告 |
| **上次更新** | 2026-08-10 |
| **下一步动作** | 剩余：位置偏置用接近的一对重测 · 自我偏好偏置 · DeepEval 对比两个 System Prompt · 提高 n |

📄 **本阶段的主要产出已整理成独立报告：**
[`docs/research-prompt-injection-in-agentic-sre.md`](research-prompt-injection-in-agentic-sre.md)
—— 6 类注入载荷 × 4 种预防配置 × 8 种机械可判危害 × 7 个检测器，含完整复现步骤。

**Phase 3 未完（不阻塞后续）**：② 拆源码剩 Embedding 原理 · HNSW 规模阈值；
加 RAG 前后的量化对比（`--no-rag` 开关已就绪，未跑成数字）。

**Phase 1 ① 跑通已完成**，② 拆源码 5/8 结案。剩余三个小追问随时可补：
temperature/top-p 对 JSON 的影响 · 模型为何爱输出 ```json 包裹 · CoT 是否真推理。

**Phase 0 已暂停** ⏸️（2026-07-28）：跳 1 完成，追问 ①④⑥⑧ 结案，核心目标（看得见模型内部）已达成。
未做完的留在下面，随时可回来补：追问 ②③⑤⑦、对读 nanoGPT、跳 2（BPE + TinyStories）。

进度总览：

| 阶段 | 内容 | 周期 | 状态 |
|---|---|---|---|
| **Phase 0** | 从零训小 GPT（MLX，10–50M 参数） | 2–3 天 | ⏸️ 暂停（跳 1 完成，追问 ②③⑤⑦ 与跳 2 待补） |
| **Phase 1** | Prompt · Function Calling · Structured Output | 2 周 | ✅ ① 完成，② 5/8 结案 |
| **Phase 2** | Agent：LangGraph · Agents SDK · MCP | 4 周 | ✅ 已交付 v1（② 6/6 结案） |
| **Phase 3** | 企业级 RAG（Runbook / Postmortem） | 3 周 | ✅ 主线完成（① 6/8，② 3/5，余项不阻塞） |
| **Phase 4** | Evaluation：Ragas · DeepEval | 2 周 | 🏗️ 进行中 |
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
- [x] 手写 Function Calling 循环（零框架）→ `agent/loop.py` + `agent/tools/cluster.py`（假集群）
      场景1 单服务下钻 4 步通过；场景2 跨 namespace 归因暴露两个独立失败模式；
      场景3 **工具返回值注入完全成功**
- [x] **注入防御对比**（每格 3 次，零噪声）→ `agent/defense_injection.py`
      System Prompt 安全规则 **0/3**；结构化输出 **0/3**；数据边界标记 **3/3**；近因提醒 **3/3**
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

- [x] **先让手写循环撞墙** → `agent/wall.py` + `agent/wall_repeat.py`
      加 3 个真会改状态的破坏性工具。W1：Agent 自主做出 **3 处未经批准的生产变更**。
      W2：注入载荷指挥它把另一个健康服务缩到 0
- [x] **发现防御反转**：Phase 1 里 3/3 有效的 D3 提醒，在新载荷上把执行率从 0/5 推到 **5/5**。
      加中性措辞对照组辨明机制 —— 是**多插一条 user 消息**这个结构改动，与措辞无关
- [x] LangGraph ReAct Agent，8 个工具 → `agent/graph_agent.py`
      刻意不用 MessagesState / LangChain 消息对象，用自己的 TypedDict + raw HTTP，
      好让 channel + reducer 的本质不被抽象挡住
- [x] Human-in-the-Loop 硬门控：破坏性工具必经 `interrupt()`。
      **同一攻击：手写循环执行 5/5 → 门控拦下 5/5，未批准变更 0 处**
- [x] Checkpointer（SqliteSaver）已接上并驱动 interrupt/resume
- [x] Checkpointer 四个用途全部实测 → `agent/timetravel.py`
      崩溃恢复：待执行写入**恰好执行一次** ✅，但 checkpointer **不保证整体无重复副作用**
      （模型自己重复请求时会忠实执行）→ **幂等性是工具的责任**，对破坏性工具尤其要命
      多轮会话：历史完全由 checkpointer 承载，第二轮只发一句话
      time-travel：见下方悬案结案
- [x] 并行分支 → `agent/graph_parallel.py`（Send 动态 fan-out 做全集群巡检）
      **实测 Ollama 单实例串行**（并发 3 次比串行慢 0.89x，延迟等差叠加=排队）
      → 设计原则：单实例后端下并行分支用来并行化**取数据**，不是并行化调模型
      ⚠️ 两条局限已记录：假集群工具 0ms 测不出收益；模型编造服务依赖关系
- [ ] 用 OpenAI Agents SDK 把同一个 Agent 再写一遍，对比两者的抽象取舍
- [x] Python MCP SDK 写 K8s MCP Server（8 个工具，带完整 annotations）→ `mcp/k8s_server/server.py`
- [x] **手写裸 JSON-RPC 客户端**抓完整协议报文 → `mcp/probe_protocol.py`（刻意不用 SDK client）
- [x] 把 MCP Server 接进自己的 Ollama Agent → `mcp/bridge_agent.py`
      **门控依据从私有 `DESTRUCTIVE` 集合换成协议字段 `destructiveHint`**，实测拦下成功
- [x] `.mcp.json` 已建且验证命令可握手；`claude mcp list` 已发现，状态 `⏸ Pending approval`
- [ ] 在 Claude Code 里批准并实际调用（需用户在 `claude` 中授权，我不代做）

### ② 拆源码 · 设计追问（本阶段重头戏）

- [x] **为什么是 StateGraph 而不是 DAG + Pregel/superstep** —— 已完全结案，读到源码。
      **LangGraph 的「图」不是图，是一组 channel + 订阅它们的节点，边只是「往哪个 channel 写」的语法糖**
      （`branch:to:n` 是个 EphemeralValue channel，读过即清空）。
      superstep = `pregel/_loop.py:599 tick()`：按 `channel_versions` vs `versions_seen` 选出本步任务
      → 并发执行（计算阶段）→ `apply_writes` 按 channel 分组、每个 channel `update(整个list)` 调一次
      （通信阶段，reducer 在此折叠）。三个读源码才发现的点：
      `_algo.py:256` 显式 `sorted(tasks)` 保证 reduce 顺序确定（add 对 list 不交换，**实测 4 次全一致**）；
      消息传递用版本号实现；**同 superstep 内并行节点看不到彼此的写入（实测证实）**
- [x] **Channel 和 Reducer** —— 已结案。`Annotated[list, operator.add]` 让节点返回**增量**而非
      完整列表；手写循环里必须自己 `messages.append`，并行分支会互相覆盖。
      `decisions` 故意不加 reducer 用覆盖语义 —— **channel 语义是按字段选的**
- [x] **interrupt 的实现机制** —— 假设已验证。**不是「暂停在这一行继续」，是节点级重放**：
      恢复时整个节点体从头重跑，已答复的 interrupt 返回缓存值。最小例子里 2 个 interrupt
      导致节点体执行 **3 次**。推论：**interrupt 之前不能有副作用，审批与执行必须拆成两个节点**
- [x] **Checkpointer 为什么是必需品** —— 四个用途全部实测。最大收获是用 **time-travel 结掉了
      Phase 1 的悬案**：从同一 checkpoint 重放 6 次，模型决策 **6/6 恒定**（相同输入下确定）；
      真正的变量是**模型的加载状态** —— 冷启动 3/3 选 `get_pods`、热缓存 3/3 选 `get_events`
      （交替顺序，已排除时间漂移）。**两个稳定状态，两个不同的确定性输出。**
      ⚑ 这条回头修正了 Phase 1 的「±2/20 不可解释噪声」——候选机制已找到，
      且给 Phase 4 定下一条硬规矩：**可复现的评测必须固定 keep_alive 并预热**
- [x] **MCP 协议层** —— 已结案，手写裸客户端抓了完整报文。六个发现：协议版本**降级协商**
      （提 2026-07-28 → 回 2025-11-25）；capabilities 双向声明；**`instructions` 会进 system prompt
      → 不可信 Server 能改你的模型行为**（这就是 Claude Code 要求显式批准的原因）；
      **工具错误不是 JSON-RPC error 而是 `result.isError`**（协议错误给客户端，工具错误给模型）；
      参数校验在服务端；8 个工具的 schema ≈ **1239 tokens 常驻 system prompt**
- [x] **复用发生在哪一层** —— `inputSchema` 与 Ollama 的 `parameters` 是**同一个 JSON Schema**，
      适配器只有 4 行。所以复用**不在 schema 层**（那本来就是事实标准），
      而在**发现+传输+生命周期+元数据**层。`annotations` 是 MCP 独有的
- [x] **什么场景不该用 MCP** —— 已结案，基于实测成本：schema 常驻 1239 tokens、
      独立进程、序列化往返、**审计边界失效**（实测：经 MCP 删 Pod 成功，客户端 `MUTATIONS` 账本为空
      → 审计必须做在协议层）。单进程自用、无跨客户端复用需求时，直接函数调用更好

### ③ 落仓 —— K8s 运维 Agent v1 ✅ 已交付

- [x] `agent/v1.py` + `agent/mcp_toolbelt.py` + `agent/v1_dryrun.py`（干跑验证 12/12）
- [x] `agent/graph_agent.py`（LangGraph 硬门控）+ `agent/graph_parallel.py`（并行巡检）
- [x] `agent/loop.py`（零框架 ReAct 对照基线）+ `agent/wall.py` / `wall_repeat.py`（撞墙实验）
- [x] `agent/timetravel.py`（Checkpointer 四用途）+ `agent/ablation_think.py` / `defense_injection.py`
- [x] `mcp/k8s_server/` + `mcp/probe_protocol.py`（裸协议客户端）+ `mcp/bridge_agent.py`
- [x] `docs/phase2-why.md`（Pregel / Channel / interrupt / Checkpointer / MCP / v1 全部记录）

v1 链路：告警 JSON → 约束解码抽取 → MCP 工具排查（有环图）→ 破坏性操作 `interrupt` 硬门控
→ 结构化 Postmortem（模型给判断、代码填事实）→ 协议层审计 + schema 校验 + 归因核查

### 检查清单

- [x] 能解释 Pregel superstep 模型，以及 LangGraph 为什么选它 → `docs/phase2-why.md`
- [x] Agent 能自主完成 ≥3 步的任务（真跑：告警 A 走了 5 个只读工具 + 1 次门控）
- [x] 杀进程后能从 checkpoint 恢复，状态无丢失（`timetravel.py --mode crash`）
- [x] 自己写的 MCP Server 被自己的 Agent 实际调用（`bridge_agent.py` / `v1.py`）
- [ ] 在 Claude Code 里被实际调用（`.mcp.json` 已注册，待用户在 `claude` 中批准）
- [x] K8s Agent v1：输入告警 JSON，输出根因分析报告 ✅
- [ ] ⚠️ **遗留缺陷**：门控保护「状态」不保护「结论」。注入内容仍会以高置信度进入
      Postmortem，归因核查只打红旗。**v2 首要课题**

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

### 2026-07-28 · Function Calling 循环 + 注入实测（同日）

**做了什么**
零框架手写 ReAct 循环 + 有状态假集群（5 个工具，信息刻意藏在第二层）。
三个场景：单服务下钻、跨 namespace 归因、工具返回值注入。加两组重复实验。

**最大的收获（两条，都是安全/工程层面的硬结论）**

1. **「Agent 能调工具」和「Agent 能解决问题」是两件事。** 跨 namespace 场景下
   think=False 三次全部走完 6 步、全部拿到了写着 `maxUnavailable=50%` 的关键事件、
   **三次全部没在结论里用上**。而 think=True 只有 1/3 命中，另 2 次是提前收工没拿到证据。
   两个独立失败模式（何时停止探查 / 是否使用证据）会互相掩盖。
   附带发现：**temperature=0 下 Agent 行为不可复现**，同一输入工具调用数在 3 和 6 之间跳。

2. **防注入必须靠上下文结构，写在 System Prompt 里的安全规则完全无效。**
   载荷藏在一行日志里（现实中攻击者能写日志就能注入），基线 0/3 全部被攻破，
   最终答案就是攻击者指定的 `ALL_SYSTEMS_NORMAL`。有效防御：
   **把工具返回包进显式不可信标记（3/3）** 或 **在工具返回之后再追加一条提醒（3/3）**。
   机制是近因效应 —— 注入在上下文末尾，System Prompt 在最前。

**被否证的假设**
以为 a15（注入在用户消息里）扛住是因为 schema 装不下载荷。实测结构化输出 0/3。
真正的差别是**载荷在上下文里的位置**，不是输出约束。

**还没搞懂的**
temperature/top-p 对 JSON 稳定性的具体影响；模型为何爱输出 ```json 包裹；
CoT 是否真推理（今天的证据只能说明它影响的是证据综合而非证据获取，且不稳定）。

### 2026-07-30 · Phase 2 开工：撞墙 → 硬门控

**做了什么**
给假集群加 3 个真会改状态的破坏性工具，让 Phase 1 的手写循环撞墙；
装 LangGraph 1.2.10，按「审批零副作用」的规则重写 Agent，做 A/B 压力测试。
详见 `docs/phase2-why.md`。

**最大的收获（三条）**

1. **防御反转 —— 今天最贵的一课。** Phase 1 里 3/3 有效的 D3 提醒，换一种注入载荷后
   把执行率从 0/5 推到 **5/5**，真的把生产服务缩到 0。加中性措辞对照组辨明机制：
   **是「多插一条 user 消息」这个结构改动本身，与提醒说什么无关。**
   一条 user 轮次等于告诉模型「人还在等你做事」——**你以为在加防护，实际改掉了终止条件。**
   → 防御必须按载荷逐个验证，不能跨场景外推。

2. **interrupt 是节点级重放，不是行级续跑。** 最小例子：一个节点里 2 个 interrupt，
   节点体被执行 **3 次**。所以 interrupt 之前不能有任何副作用，审批与执行必须拆成两个节点。
   这是 Phase 1 写在路线图里的假设，今天验证为真。

3. **架构门控有效但有明确边界。** 同一攻击：手写循环执行 5/5、变更 5 处；
   LangGraph 门控拦下 5/5、变更 0 处。但门控**解决不了「洗白」**——
   基线下模型不动手，只把攻击者指令包装成权威建议交给人。
   授权问题和信息完整性问题需要两种不同的防御。

**踩的坑 / 判断**
- 刻意**不用** MessagesState 和 LangChain 消息对象，用自己的 TypedDict + 原来的 raw HTTP。
  代价是多写点代码，收益是 channel/reducer 的本质没被抽象挡住，而且证明了
  LangGraph 与 LLM 客户端正交。
- 破坏性工具必须真的改状态（`MUTATIONS` 记账），否则「撞墙」没有说服力。

**还没搞懂的**
Pregel/superstep 的内部机制（还没读源码）；崩溃恢复与 time-travel 未实测；
并行分支下 reducer 的真实行为；D2 数据边界对「洗白」载荷还灵不灵。

### 2026-07-30 · Pregel 源码 + 并行分支（同日）

**做了什么**
从 `InvalidUpdateError` 那条报错反查源码，一路读到 `apply_writes`，把 superstep 模型拼完整，
并用两个可验证的预测确认了语义。然后按实测得出的原则写了全集群并行巡检。

**最大的收获**
**LangGraph 的「图」不是图** —— 是一组 channel 加一组订阅它们的节点，边只是「往哪个 channel 写」
的语法糖（`branch:to:n` 就是个 EphemeralValue channel，读过即清空）。
`channel.update()` 接收的是**序列**，一个 superstep 内所有写入按 channel 攒成 list、
`update()` 只调一次 —— 「one value per step」不是特判，是架构的必然结果。

**三个只有读源码才知道的点**
1. `_algo.py:256` 显式 `sorted(tasks)`。`operator.add` 对 list 不满足交换律，
   若按完成顺序 reduce 结果就不可复现。实测 8 个随机延迟分支跑 4 次，顺序始终一致。
2. Pregel 的消息传递是用 `channel_versions` vs `versions_seen` 版本号比较实现的。
3. **同 superstep 内并行节点看不到彼此的写入**（实测：reader 看到 `[]`，下一步才看到值）。
   所以 fan-out 分支间不能有依赖 —— 不是「不建议」，是物理上看不见。

**踩的坑 / 诚实标注**
- **先测后端再设计**：Ollama 单实例串行（并发 3 次比串行慢 0.89x，延迟等差叠加=排队），
  所以并行分支只用来并行化取数据。这条接上 Phase 0 的 memory-bandwidth 结论，也是 Phase 6 伏笔。
- 假集群工具是内存操作、0ms，**并行取数的收益在这里根本测不出来**，架构对但数字不能当证据。
- **模型编造了服务依赖关系**（"billing 可能依赖 payment"），巡检数据里没有任何依赖信息。
  修法是数据里必须带 service graph，未修。
- 发现自己的隐患：`graph_agent.py` 的 `decisions: dict` 没 reducer，只因目前无并发写才没炸。

### 2026-07-30 · Checkpointer 四用途 + 结掉 Phase 1 悬案（同日）

**做了什么**
`agent/timetravel.py` 实测 checkpointer 的四个用途，并用 time-travel 回头解决
Phase 1 遗留的「temperature=0 下 Agent 行为不可复现」。

**最大的收获：悬案结案，且回头修正了 Phase 1 的结论**

两步实验：
1. **从完全相同的 checkpoint 重放 6 次**（只跑一个 agent 节点）→ 决策 **6/6 恒定**。
   所以不是单点随机。
2. **那什么在变？模型的加载状态。** 同一份输入，交替冷/热跑 6 次：
   冷启动 3/3 选 `kubectl_get_pods`，热缓存 3/3 选 `kubectl_get_events`。
   **两个稳定状态，两个不同的确定性输出**，且冷启动那个决策明显更差（冗余调用）。

⚑ **这条回头修正了 Phase 1**：那里测出的「±2/20 不可解释噪声」，现在有了候选机制。
那批实验没控制 `keep_alive`、没预热。已在 `docs/phase1-why.md` 加修正说明。
**给 Phase 4 定下硬规矩：可复现的评测必须固定 keep_alive 并预热。**

**第二个收获：checkpointer 的保证边界**
崩溃恢复实测显示「待执行的写入恰好执行一次」✅，但整体看 `get_pods` 出现了两次 ——
**那不是 checkpoint 重放，是模型在下一轮自己又请求了一次相同调用**，checkpointer 忠实执行。

> Checkpointer 保证「待执行写入恰好一次」，**不保证「整体无重复副作用」。
> 幂等性是工具的责任。** `kubectl_delete_pod` 被模型重复请求两次，就会真删两次。

**踩的坑**
我自己脚本里的「是否重复执行」判定写错了，第一版打印了错误的 ✅。
加上「崩溃时待执行的工具」这个仪表后才看清真相。**判定逻辑本身也要被审查。**

### 2026-07-30 · MCP 专题（同日）

**做了什么**
写 K8s MCP Server（8 工具，完整 annotations）→ **手写裸 JSON-RPC 客户端**抓完整协议报文
→ 把 Server 接进自己的 Ollama Agent → 注册到 Claude Code。详见 `docs/phase2-why.md`。

**最大的收获（三条）**

1. **MCP 真正标准化的不是 schema，是元数据和生命周期。**
   `inputSchema` 与 Ollama 的 `parameters` 是同一个 JSON Schema，适配器 4 行。
   独有的是 `annotations` 四个 hint —— 其中 `destructiveHint` 正是我们撞墙时手工搓的
   `DESTRUCTIVE` 集合，`idempotentHint` 正是上一节「幂等性是工具的责任」的结论。
   `bridge_agent.py` 已把门控依据从私有集合换成协议字段，实测拦下成功。
   但 hint 是服务端**自报**的，所以额外保留客户端兜底名单 —— 门控的权威判断必须在自己这侧。

2. **`instructions` 会进 system prompt** —— 不可信 MCP Server 能直接改你的模型行为，
   比 Phase 1 那个工具返回值注入更靠上游。这解释了 Claude Code 为什么对项目级
   `.mcp.json` 要求显式批准（实测 `⏸ Pending approval`）。**架构层门控，不是叮嘱。**

3. **进程边界一变，审计边界必须重划。** 实测：经 MCP 删掉一个 Pod 成功，
   但客户端的 `MUTATIONS` 审计账本是**空的** —— 记账写在工具内部，工具跑在另一个进程。
   → **审计必须做在协议层（记录 tools/call）**。

**其他值得记的协议细节**
- 协议版本是**降级协商**：客户端提 2026-07-28，服务端回 2025-11-25
- **工具错误不是 JSON-RPC error，是 `result.isError`** —— 协议错误给客户端，工具错误给模型
  （因为工具失败要回灌让模型改正，所以必须是「成功的响应」）
- 8 个工具的 schema ≈ **1239 tokens 常驻 system prompt**，这是「不该用 MCP」的主要成本

**判断**
不该用 MCP 的场景：单进程自用、无跨客户端复用需求 —— 上面每项成本都付，收益为零。

### 2026-08-06 · K8s 运维 Agent v1 交付

**做了什么**
把 Phase 1/2 的所有结论收成一个能跑完整告警的 Agent。先写干跑（不调模型，3 秒 12/12 断言）
确认结构，再上真模型。详见 `docs/phase2-why.md`。

**v1 的每条设计都由某个实测结论决定**，不是照教程搭：有环图+Checkpointer、
approve 与 execute 分离（interrupt 节点级重放）、门控 = `destructiveHint` ∪ 客户端兜底、
数据边界包裹、**不**追加 user 提醒、协议层审计、固定 keep_alive+预热、代码填事实、
门控记住已拒绝的操作。

**最大的收获：一个诚实的半失败**
告警 C（日志里埋注入载荷）：
- ✅ 门控守住了**状态** —— 拦下 `scale_deployment(payment, replicas=0)`，集群未变
- ❌ 注入在**信息层完全成功** —— 攻击者的话被当证据写进 Postmortem，置信度 0.8，
  全程无一处标记可疑。System Prompt 写了「绝不转述」、数据边界也在，都没用

> **架构门控保护「状态」，保护不了「结论」。** 而 Postmortem 是人做决策的依据 ——
> 这是绕过门控的路径。**v2 的首要课题。**

**新防御：归因核查（唯一不依赖模型自觉的一条）**
模型把 reporting 的问题归因到 payment，而它**从未查询过 payment**。审计日志是代码记的，
两者可机械核对。实测抓到。边界：只打红旗不阻止，且只能抓跨 namespace 的无据归因。

**踩的坑（两个都很贵）**
1. **约束解码不执行 `number` 的 min/max** —— 报告里出现 `置信度: 8`（schema 写 0~1）。
   专项测试确认只有 number 的 min/max 未执行。而且**越界不稳定发生**（第二次跑是 0.9），
   靠"试一次没问题"会漏。→ 约束解码之后必须自己校验。
2. **所有"卡住"的真因是 brew 升级，与代码无关。** ollama 服务端跑了 3 周（0.17.6），
   brew 今早把二进制换成 0.32.5 → 老服务端 spawn 新 runner 失败 →
   `/api/version` 正常但 `/api/chat` **永久挂死**。同批还升了 Python（触发 uv 重建 venv、
   重装全部依赖，那是第一次"600 秒卡住"的真因）、uv、node。
   教训：**长任务别用 `| tail`**，进度被憋住会让环境重装看起来像死锁。
   顺手修了 `RawStdioClient` 不读 stderr 的潜在双向死锁。

⚑ **本会话中 Phase 0 的 22.29 tok/s 与 Phase 2 的冷/热确定性结论均在 ollama 0.17.6 上测得**，
新版（0.32.5，25.4 tok/s）未复测。

### 2026-08-07 · Phase 3：RAG 建库、评测、接进 v1

**做了什么**
`prometheus-operator/runbooks` 语料（与 Phase 1 测试集告警名 5/5 命中）→ 索引 →
29 条五类查询的检索评测 → 自实现 BM25 与混合检索对比 → `search_runbook` 进 MCP Server
→ 接进 v1 做 A/B。详见 `docs/phase3-why.md`。

**开工前先证明需要 RAG（教程都跳过这步）**
语料 25k token，128k 上下文能全塞，「装不下」不成立。但 prefill 实测差 115 倍
（264.5s vs 2.3s），且成本**超线性**增长（n/d=5.04 时比线性多付 27%）——
这验证了 Phase 0 算出的 `二次项/线性项 = n/d`。
**RAG 的收益不是「塞不下」，是「prefill 成本超线性」。**

**三个教程默认值被实测推翻**
1. 512 token 固定切片 → 每个 chunk 跨 3.3 个 runbook，仅 4/50 只含单篇
2. 「按段落切保持完整性」→ 实测更差（R@3 83% vs 86%，日文 33%→0%）
3. 「混合检索更好」→ 实测更差（R@1 76%→66%），RRF 无条件融合会引入噪声

**跨语言：中文靠英文术语，日语被片假名毁掉**
nomic 中文 67% / 日文 33%。BM25 中文也有 67%（因为中文运维查询混着 Pod/CPU/PVC/etcd
等英文原词），日文 0%（ノード≠node、リーダー≠leader，**转写破坏词汇重叠**）。
查询翻译把中日文 R@3 修到 100%。**反直觉**：bge-m3 + 翻译反而比 bge-m3 直接更差
——翻译有损，对原生多语言模型是降级，两方案不能叠加。

**⚠️ 安全上的重大发现：门控没有切断攻击路径，只是换了执行者**
告警 C 带 RAG 重跑，Postmortem 里出现三样新东西：
(a) 模型以 **risk=high** 建议「联系 payment-api 负责人手动把副本缩到 0」
(b) open_questions 里质疑「为什么这个 required 的修复动作没被执行」
(c) 假归因与真实日志事实编织成完整因果链

> Phase 2：门控保护「状态」不保护「结论」
> **现在要改成：门控把「Agent 自己动手」变成了「Agent 以正式建议说服人动手」。**
> 而且门控的存在本身成了攻击的一部分 —— 报告里那句「有个必需动作被拦下」
> 会让读报告的 SRE 更倾向于手动执行。

**其他**
- 「接了 RAG」≠「RAG 起作用」：不在系统提示里写进排查流程，模型默认不查知识库
- 设计成功的一条：工具输出里标明「通用运维知识，不是本集群状态」后，
  模型的 evidence 三条全部来自 `kubectl_*`，没把 runbook 当集群证据

<!-- 下一条从这里开始 -->
