# Phase 4 · 设计追问的答案

> 方法沿用前面：**先量，再决定**。这一阶段格外要紧 ——
> 评测工具产出的是「数字」，而数字自带权威感。不先验证工具本身，
> 拿到的只是把噪声换了个更可信的包装。
>
> 环境：qwen3:14b（Ollama 0.32.5）· ragas 0.4.3 · deepeval 4.1.5 · M4 Pro 24GB。

---

## ⚑ 为什么第一步不是跑 Ragas，而是验裁判

Ragas / DeepEval 的绝大多数指标底层都是 **LLM-as-judge**。
裁判不稳或有系统性偏置，所有下游指标都继承它。

而前三个阶段已经反复撞到这类问题：

| 阶段 | 撞到的方法论问题 |
|---|---|
| Phase 1 | 同配置重复三次，噪声 ±2/20，差点把噪声当信号 |
| Phase 2 | 模型加载状态改变输出（冷 3/3 与热 3/3 给出**不同的确定性答案**） |
| Phase 3 | 分类型子集只有 3 条，一条查询 = 33 个百分点 |

所以先量四件事：噪声底 · 位置偏置 · 冗长偏置 · 协议选择的影响。
夹具取自本仓库真实数据（`KubePodCrashLooping` runbook + 三个回答变体），
全程固定 `keep_alive` 并预热。

---

## ① 噪声底：同一会话内是确定性的 ✅

```
夹具            各次分数（重复 10 次，temperature=0）        不同取值  极差  标准差
忠实回答        [10,10,10,10,10,10,10,10,10,10]              1       0    0.00
含幻觉回答      [ 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]              1       0    0.00
```

**σ = 0。** 我原本在脚本里写死了「temperature=0 不保证同一输入得到同一分数」，
**这句在本数据上是错的**，已改。

但这不等于「评测可复现」—— 和 Phase 2 的发现并不矛盾，两者说的是不同的东西：

> **固定加载状态内：确定。跨加载状态：不确定。**
> （Phase 2 实测：同一输入，冷启动 3/3 选 `get_pods`，热缓存 3/3 选 `get_events`。）

**可操作的规矩：评测必须一口气跑完，中途不要重启 ollama、不要让模型被换出。**
否则前半段和后半段的数字来自两个不同的"确定性"世界。

---

## ② 位置偏置：本夹具未观察到 ⚠️（但不能推广）

```
好回答放 A 位：判它赢 6/6      好回答放 B 位：判它赢 6/6      一致率 6/6
```

**注意夹具太容易了** —— 忠实回答 vs 含幻觉回答的差距极大，任何裁判都不会摇摆。
位置偏置通常在**两个候选接近**时才显现。所以这条只能说「本夹具未观察到」，
**不能得出「这个裁判没有位置偏置」的结论**。（待补：用两个质量接近的回答重测。）

---

## ③ 冗长偏置：确凿存在，但**只在成对比较里显形** ✅

两个回答的**事实内容完全一样**（都是 `get pod` → `describe pod` → `logs` 三步），
唯一差别是 81 字 vs 269 字。

```
绝对打分   简洁版 [10×6] 均值 10.00     冗长版 [10×6] 均值 10.00     差值 +0.00
成对比较   ['B','B','B','B','B','B']    选冗长版 6/6
```

**打分完全看不出差别，成对比较 6/6 全选冗长版。**

我脚本第一版的判定只看分数差，因此输出了「本夹具上偏置不明显」——**结论下错了**，
成对比较的 6/6 是明确证据。已修正判定逻辑。

### 真正的发现在这两者的落差里

> **绝对打分（pointwise）与成对比较（pairwise）暴露的偏置不同。**
>
> · pointwise 容易**饱和**（两个都给满分）→ 分辨力为零 → **把偏置藏住了**
> · pairwise 强制做选择 → 有分辨力 → **偏置立刻显形**
>
> **选哪种评测协议，本身就是一个会改变结论的决定。**

这条有直接的工程含义：Ragas 的多数指标是 pointwise 的。
如果你的两个候选都落在「裁判给满分」的区间，Ragas 会告诉你「一样好」——
**那不是它们真的一样好，是这把尺子在这个区间没有刻度。**

天花板效应本身就是要检查的东西：**指标给出满分时，先确认它不是失去了分辨力。**

---

## Ragas 的指标到底怎么算的 ✅（读源码，不是读文档）

`.venv/.../ragas/metrics/` 下逐个文件读出来的。**四个核心指标没有一个是 0-10 打分，
全是二值判定 + 聚合。**

| 指标 | 裁判被问什么 | 输入 | 需标注 | 算分方式 |
|---|---|---|---|---|
| **Faithfulness** | ① 把 response 拆成原子陈述 ② 每条能否从 context 直接推出 (1/0) | question, **response**, context | ❌ | 命中数 / 总数 |
| **Context Recall** | **reference** 逐句能否归因到 context (Yes/No) | question, context, **reference** | ✅ | 命中数 / 总数 |
| **Context Precision** | 每个 context 对得出 answer 有没有用 (1/0) | question, answer, contexts | ❌ | **Average Precision**（含排名） |
| **Answer Relevancy** | 从 response **反向生成 question** + 判 noncommittal | question, response | ❌ | 生成 question 与原 question 的 **embedding 余弦** |

### 原文 instruction（`_faithfulness.py`，两次 LLM 调用）

```
第一次（拆解）
  "Given a question and an answer, analyze the complexity of each sentence in the answer.
   Break down each sentence into one or more fully understandable statements.
   Ensure that no pronouns are used in any statement. Format the outputs in JSON."

第二次（逐条判定）
  "Your task is to judge the faithfulness of a series of statements based on a given context.
   For each statement you must return verdict as 1 if the statement can be directly inferred
   based on the context or 0 if the statement can not be directly inferred based on the context."
```

### ⚑ 这修正了我上一节的推断

我在噪声实验后写过「Ragas 多为 pointwise，会有天花板效应」——**不准确**。

> 它确实逐项判定，但**分辨力来自「把回答拆成 N 条原子陈述」，不是分数刻度**。
> N 条原子陈述的二值判定 = N+1 档的分数。**这恰恰是绕开天花板效应的设计。**
> 有天花板的是我那个 0-10 单分裁判。

### 为什么 Context Recall 需要 ground truth 而 Faithfulness 不需要 ✅

`_context_recall.py:141` 直接写着 `answer=row["reference"]` —— 它把**参考答案**
喂进那个「逐句判断能否归因到 context」的 prompt。

```
Faithfulness    问「回答里的话，context 里有依据吗」
                -> 内部一致性检查，response ↔ context 对照即可，不需要知道正确答案

Context Recall  问「【应该】被检索到的信息，实际检索到了多少」
                -> 要定义「应该」，必须有一个已知完整的参考答案
```

**最实用的推论：**

> **线上能监控幻觉，监控不了漏检。**
>
> · Faithfulness / Answer Relevancy / Context Precision 只用运行时就有的东西
>   （query + retrieved contexts + response）-> **可无标注在线上跑**
> · Context Recall 必须有人工标注 -> **只能离线在测试集上跑**

### 三个读源码才能发现的坑

**① few-shot 示例是通用领域的。** 四个指标都带 `examples`，内容是
Einstein / T20 World Cup / Andes。用在 K8s 运维语料上，最好情况是无用，
也可能把裁判往通识方向带。这是接自有语料时要评估的第一件事。

**② Answer Relevancy 靠 embedding 余弦，不是 LLM 打分。**
`_answer_relevance.py:96-126`：LLM 只负责「从 answer 反推 question」和「判 noncommittal」，
最终分数是 `cosine(embed(生成的question), embed(原question))`。
**因此它继承 Phase 3 发现的全部 embedding 局限** —— 包括跨语言：
中文/日文提问 + 英文语料的组合，这个指标会失真。

**③ Context Precision 算的是 Average Precision，奖励「相关的排在前面」。**
所以它对**检索顺序**敏感。Phase 3 里 reranker 把 R@1 从 76% 提到 90%（R@3 不变），
这个指标会明显上升，而 Context Recall 不会动。
**两个指标测的是检索的不同侧面，不能只看一个。**

### ⚠️ 当前无法直接运行

`import ragas` 报 `ModuleNotFoundError: No module named 'langchain_community.chat_models.vertexai'`。
读源码不受影响；要实际跑需要补装 `langchain-community`（未装）。

---

## 尚未回答

- ~~Ragas 的指标怎么算的~~ ✅ 已结案（见上）
- ~~Context Recall 为何需要 ground truth~~ ✅ 已结案（见上）
- 自我偏好偏置：qwen3 会不会偏袒自己生成的答案（可用 deepseek-r1 做对照）
- 补装 `langchain-community` 让 ragas 可运行，并评估通用领域 few-shot 对运维语料的影响
- 位置偏置用**接近的一对**重测
- 评测本身的 token / 时间成本，以及在 CI 里跑的可行性
- 把 Phase 1（20 条告警）与 Phase 3（29 条查询）两套测试集接进 Ragas/DeepEval
- 用评测量化 Phase 2/3 那套安全防御矩阵
