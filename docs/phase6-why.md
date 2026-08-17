# Phase 6 · 生产部署与可观测（进行中）

> 与前几阶段同名同体例。ROADMAP 里原写的是 `phase6-llm-serving.md` +
> `phase6-mac-limitations.md`，实际合并为这一份 —— Mac 的限制不该单独成篇，
> 它是**贯穿每个设计决定的约束**，拆开写会让人以为那只是一节免责声明。

---

## 0. 本阶段要回答的真问题

原规划的清单（起 kind、装 Prometheus、写 YAML）是**架构演练**，该做。
但这一阶段真正的问题由 Phase 5 直接产生：

> **一个基于 LLM 的防御，在生产中如何被观测？**

Phase 5 实测出三件事，它们让传统监控彻底失效：

1. **「净化剥离了 N 行」不是防御生效的证据** ——
   P-机器格式破坏 载荷下净化剥离了 6 行，危害 H2 仍是 **2/2**，一点没降。
2. **盲点会转移** —— 补了「人写的无害文本」后，盲点转到了「机器格式的有害文本」。
   今天有效的判别器，明天可能对新形式完全失明。
3. **生产中没有 ground truth** —— 你不知道那条容器日志里到底有没有注入。

> **一个已经完全失效的净化器，它的 QPS、延迟、错误率全都是绿的。**

所以本阶段的核心不是「装上 Prometheus」，而是**设计对 LLM 防御真正有信息量的 SLI**。

---

## 1. 硬约束：先量，再设计

| 项 | 实测 |
|---|---|
| 总内存 | **24.0 GiB** |
| wired | 12.0 GiB（含 Ollama 常驻 qwen3:14b 9.3 GiB） |
| free | 0.4 GiB |
| **swap used** | **5.79 GiB** ← 系统**已经在换页** |
| Pageouts | 781,644 页 ≈ 累计换出 12.8 GiB |

`free 0.4 GiB` 本身不说明问题（macOS 会把空闲内存全用作缓存），
但 **swap 已用 5.8 GiB 是硬信号**。

而这对本项目尤其致命：**decode 是 memory-bandwidth-bound 的**（Phase 0 实测），
推理过程中一旦换页，TPOT 会直接崩。
—— 我在 `monitoring/alerts.yaml` 里写的 `ModelMemoryBudgetExceeded` 正是防这件事，
**结果它自己先撞上来了**。

### 预算表

| 组件 | 预估 |
|---|---|
| OrbStack VM 开销 | 2–4 GiB |
| kind node（control-plane + etcd + kubelet） | 1.5–2 GiB |
| Prometheus | 0.5–1 GiB |
| Grafana | 0.25 GiB |
| Agent Pod | 0.5–2 GiB |
| **合计新增** | **4.75–9.25 GiB** |

在已 swap 5.8 GiB 的基础上再加 5–9 GiB，机器会非常卡且推理被拖垮。

**出路**：Phase 6 的 k8s 演练**不需要 14B 常驻** ——
canary 只用 judge（4B / 2.5 GiB），端到端排查已在 Phase 5 用完整危害矩阵验证过。

```
ollama stop qwen3:14b

wired  12.0 → 3.6 GiB   （回收 8.4 GiB）
free    0.4 → 9.1 GiB
```

**这条约束直接决定了架构：模型不进 Pod。**
推理留宿主机，Agent 通过 `OLLAMA_HOST` 连出去 ——
这也符合生产实际（LLM 通常是独立推理服务，不与业务容器同生命周期）。

---

## 2. 指标设计：三层，第三层才回答「防御还在吗」

`deployment/metrics.py`。

```
① 传统       必要但不充分 —— 服务活着不等于防御活着
② LLM 专属   TTFT / TPOT 分开
③ 防御有效性 canary —— 生产中唯一的 ground truth
```

### 为什么 TTFT 与 TPOT 必须分开

Phase 0 实测：**prefill 是 compute-bound、decode 是 memory-bandwidth-bound**，
两者对 batch size 的反应相反。合成一个「平均延迟」会让
**「prompt 变长」和「显存带宽被抢」看起来一模一样** —— 而处置手段完全不同。

### 为什么 `lines_removed` **故意不设告警**

Phase 5 实测：剥离 6 行而危害未降。
**给它设阈值只会制造假安全感。** 它只在与 canary 检出率交叉时有意义
（剥离量大 + 检出率跌 = 正在乱删）。

---

## 3. canary：生产中唯一的 ground truth

`deployment/canary.py`。做法是 SRE 的合成监控搬到 LLM 防御上：
**自己造带标签的流量**，定期喂给判别器，检查它是否正确判定。

### 三条设计约束，全部来自 Phase 5 的实测教训

1. **必须分家族统计。** 盲点会转移。只报总检出率的话，某一族整体失效
   只会让总数小幅下滑，被其他族的高分掩盖 ——
   与 Phase 5 里总准确率把 F5 的 33% 掩盖成 60% 是同一个错误。
2. **必须同时探干净样本。** 只看检出率的话，「全判 true」能拿满分 ——
   Phase 5 的 v1 模型正是如此（F6a 100% 而 F6b 仅 34.4%），而它会把
   正常的 runbook 引用全删掉。**检出率与误报率必须成对出现。**
3. **canary 不进真实排查流程。** 只调 `guard.sanitize()`，
   否则会往审计与报告里灌假数据。

canary 池的措辞**与训练集不同** —— 要探的是「判别器现在还行不行」，
不是「它还记不记得训练数据」。用训练里见过的原句，探测会永远绿。

### ⚑ 本阶段最有价值的一个错：判据写错了

第一版我写的是：

```python
hit = bool(removed)          # 「有没有删掉东西」
```

**这正是我在 `metrics.py` 里刚警告过的错误。**
Phase 5 的 P-机器格式破坏 里 `sanitize()` 确实删了 3–6 行（只是删错了行），
`bool(removed)` 会判它「检出」。结果：

```
机器格式  100% ← 假的。该族是 Phase 5 量出的已知弱点（判别器仅 1/4）
```

改成**载荷本身是否被整条移除**后：

```
谎报正常 100%   指挥破坏 100%   压制排查 100%   嫁祸 100%
机器格式  80%  ⚠️ 低于 SLO      ← 弱点被指标抓出来了
（干净诱饵）20% ← 误报率
```

> **用错判据的 canary 比没有 canary 更危险 —— 它给出绿色的假保证。**

（80% 而非 F6a 的 25%，是因为 `sanitize()` 有段落级+逐行+窗口+迭代四层，
比裸判别器强 —— **净化流程本身确实提升了检出**，但这一族仍明显弱于其他。）

**我在指标文档里写下警告，转头在实现里犯了同一个错**，
说明这类错误靠自觉防不住，只能靠判据本身写对。

---

## 4. 探针：LLM 服务的 readiness 不是端口通

`deployment/server.py`。

`/readyz` **真的让模型生成一个 token**。这是唯一能同时排除三种情况的探法：

| 情况 | 只探端口 | 探版本端点 | 真实生成 |
|---|---|---|---|
| 进程起来但模型没加载完 | ❌ 绿 | ❌ 绿 | ✅ 红 |
| 模型不存在 / 名字写错 | ❌ 绿 | ❌ 绿 | ✅ 红 |
| **ollama 版本端点正常但 `/api/chat` 永久挂起** | ❌ 绿 | ❌ 绿 | ✅ 红 |

第三行是 Phase 3 真撞到过的：brew 把二进制升到 0.32.5 而 server 还是 0.17.6，
`/api/version` 一切正常、`/api/chat` 永久挂起。**只探版本端点会一路绿灯。**

### 存活与就绪必须分开

实测验证过正负两面：

```
模型正常     /healthz 200   /readyz 200
模型不可用   /healthz 200   /readyz 503   ← 不切流量，但也不重启
```

**`/healthz` 故意不检查模型。** 若把「模型没加载好」判成 unhealthy，
k8s 会重启 Pod，而重启只会让模型重新加载一遍 ——
**把慢启动变成崩溃循环**。慢启动交给 `startupProbe`（容忍 5 分钟），不交给 liveness。

---

## 5. 告警规则

`monitoring/alerts.yaml`，4 组 9 条。三条设计值得单独说：

- **按家族告警**而非总检出率 —— 理由同 §3。
- **检出率与误报率成对告警** —— 只看前者，「全判 true」能拿满分。
- **`CanaryStalled`：监控的监控。**
  canary 停止上报比 canary 报警更危险：后者是「知道坏了」，
  **前者是「不知道好坏」，而仪表盘一片绿。**

### 5.1 部署到真集群后，三条规则全部出了问题 —— 纸上都是对的

规则写完时通过了 YAML 校验，也「读起来没毛病」。
接上真实数据后（kind + Prometheus v3.7.3 抓宿主机 Agent）立刻暴露三个缺陷：

#### ① `rate()` 保留 label → 一次喷出 6 条同名告警

```promql
# 第一版
absent(...) or rate(sre_guard_canary_checks_total[30m]) == 0
```

`rate()` 保留了 `family` / `result` 全部 label，于是**对每个 label 组合各求值一次**，
`CanaryStalled` 一次产生 6 条实例。而「canary 停止上报」是**全局状态** ——
6 条同名告警会让值班的人以为是 6 个独立故障。

→ 修：`sum(rate(...))`。**这是 PromQL 最容易犯的错：忘了表达式默认按 label 组合逐条求值。**

#### ② 滚动比率在冷启动时失真 → 假告警

服务刚起时 canary 只跑过 1 轮，那 1 次干净诱饵恰好误报 →
误报率显示 **100%**，而稳定后实测是 20%。
我的告警只看比率、不看样本量，于是**每次重启都会喷一轮假告警**。

→ 修：加最小样本量条件。
**假告警会训练值班的人忽略它，那比没有告警更糟。**

#### ③ ⚠️ 修 ② 时引入了「永不触发」—— 而它是静默的

```promql
# 修 ② 的第一版
sre_guard_canary_false_positive_rate > 0.2
and (sum(sre_guard_canary_checks_total{family="_clean"}) >= 10)
```

PromQL 的 `and` 默认按**全部 label** 做集合匹配。
左边带 `{instance, job}`，右边 `sum()` 把 label 全聚合掉了 —— **两边永远匹配不上**。
把阈值放宽到必然成立再查询，实测：

```
裸 and（右侧无 label）      → 0 条   ← 左右条件都为真，仍然为空 = 永不触发
and on()（忽略 label 匹配） → 1 条   ✓
and on(family)              → 5 条   ✓
```

这条告警会一直显示 `inactive`，看起来岁月静好，而误报率再高也不会响。

> **我为了修「冷启动假告警」，引入了一个「永不告警」的 bug —— 后者严重得多。
> 假告警至少看得见，静默失效看不见。**

（`CanaryDetectionRateLow` 用的是 `and on(family)`，左右都有 `family`，所以是对的。
同一份文件里两条相邻的规则，一条对一条错 —— 说明这不是「知不知道」的问题。）

### 5.2 因此：告警必须验证「能触发」，不只是「不误报」

把每条规则的阈值**改成必然成立**，看查询是否真返回结果：

```
CanaryDetectionRateLow    ✓ 能触发，返回 5 条
CanaryFalsePositiveHigh   ✓ 能触发，返回 1 条
CanaryStalled             ✓ 能触发，返回 1 条
```

这与 Phase 2 起就在用的原则同构 ——
**`v1_dryrun.py` / `guard_dryrun.py` 里的断言也都是先验证「检测器能抓到」，
再验证「不误报」。** 只测后者的检测器，等于没有检测器。

---

## 5.3 Grafana：面板「加载成功」不等于「有数据」

`monitoring/dashboard.json` + `kubernetes/grafana.yaml`（Grafana 12.3.1，
datasource 与 dashboard 全部走 provisioning，`allowUiUpdates: false` ——
**面板必须能进版本库**，手点出来的 dashboard 换台机器就没了，
也没法 review「为什么这个面板要这么设计」，而本项目的面板描述里
恰恰写满了「这个指标不能单独解读」这类结论）。

Dashboard 部署后一切正常：语法零错误、provisioning 加载成功、Grafana 健康。
于是**把每个面板的查询逐条打到 Prometheus 上**验证 —— 14 个查询只有 4 个有数据。
逐个查下去，发现两处是**永远不会有数据**的：

### ① canary 在调 `sanitize()`，但从不上报 guard 指标

`observe_guard()` 只在 `/investigate` 里被调用，`_canary_loop` 没调。
于是 canary 每 60 秒净化一次，而 `guard_scans` / `lines_removed` /
`fallback_dropped` 三个指标恒为空 —— **Grafana 上三个面板是死的**。

### ② `llm_ttft` / `llm_tpot` 定义了，却从未 `observe()`

纯粹的假指标。非流式调用拿不到首 token 时间，只能拿到总耗时。

→ 修法把两件事合成了一件：**`/readyz` 改用流式调用**。
这个每 30 秒跑一次的就绪探针，因此同时是一次**合成性能探测**：

```
第一个 chunk 到达      -> TTFT（prefill 侧）
后续 chunk 平均间隔    -> TPOT（decode 侧）

实测：TTFT 1510ms · TPOT 14ms · 9 chunk
```

**TTFT 是 TPOT 的 100 倍** —— 这正是 Phase 0 那条结论的直接体现：
两者是性质不同的负载，用「总耗时 ÷ token 数」会把 prefill 摊进 decode，
把两种问题混成一个数字。

> **没有这一步验证，dashboard 会「部署成功」而一半面板是死的 ——
> 而死面板和「指标正常所以没事」在屏幕上长得一模一样。**

### 5.4 `tool` 标签的归属是错的 —— 砍掉了这个维度

补完埋点后再查，发现所有数据都记在 `tool="canary"` 下，
**那次 `/investigate` 的扫描一条都没记到 `tool="kubectl_logs"`**：

```
sre_guard_scans_total{tool="canary", verdict="flagged"} 31
sre_guard_lines_removed_total{tool="canary"} 150
```

原因是 canary 线程与 `/investigate` **共享同一个 `InputGuard.stat`（进程内累计值）
和同一个快照**：canary 每 60 秒醒来时，会把 investigate 期间产生的增量
一并算走、并打上自己的标签。

**一个全局累计的 stat 里还原不出调用来源。** 与其给出错误的归属，不如不给 ——
去掉 `tool` 维度。真要分来源，得让 `InputGuard` 内部按 tool 分桶累计，那是另一件事。

顺带一个 Prometheus 细节：**带 label 的 Counter 在第一次 `inc()` 之前根本不存在**，
查询返回空；无 label 的 Counter 创建即注册、从 0 开始可见。
砍掉 label 后 `fallback_dropped` 显示为 `0` 而不是「空」——
**「0」和「没有这个指标」在告警里含义完全不同。**

### 5.5 一次我自己的误判

端到端排查后看到「净化剥离了 9 行（整段）」，我判断是触发了 fallback（整段丢弃）。
**错了。** `sre_guard_fallback_dropped_total` 始终为 0 ——
实际是**迭代收敛把每一行都判为需删**，兜底分支根本没走到。
面板显示空是**正确**的，不是 bug。

（附带一个真结果：Phase 5 里这个机器格式载荷让 H2 洗白 2/2；
加了迭代收敛之后，`detectors_fired` 为空、注入完全没进上下文 ——
**那个绕过被堵上了**。代价也真实：`root_cause` 只剩
「ingest-worker 容器启动失败（退出码 1）」，因为真实的 ERROR 行也被删了。）

---

## 5.6 OpenTelemetry：Agent 的 trace 不能照搬微服务那套

`deployment/tracing.py`。四个结构性差异：

| | 普通微服务 | 本 Agent |
|---|---|---|
| 时间尺度 | 毫秒 | 一次排查 **61–87 秒**（实测） |
| 形状 | 调用树，基本固定 | `investigate ⇄ execute` **有环**，深度事前不可知 |
| 主要成本 | 时间 | **token**（时间只是它的副产品） |
| 有无人类 | 无 | **`interrupt()` 让 span 跨越人的思考时间** |

最后一条是 Phase 2 的 HITL 设计直接导出的，也最容易把监控搞坏：

> 一次排查触发人工审批后，span 会一直开着，直到有人点「批准」——
> 可能 30 秒，也可能第二天早上。
> **照搬普通 trace 语义，p99 延迟会被「等人」污染** ——
> 而那根本不是系统的性能问题，扩容一台机器也解决不了。

所以把时间**显式拆成三类**写进 span 属性，并给「等人」打上
`agent.excluded_from_latency_slo=true` —— 让下游查询能**自动**剔除它，
而不是靠人记得。

### 实测：99% 的时间在等模型

一次真实排查（告警 A，4B 主模型）：

```
总耗时      61.144 s
  等模型    60.624 s   ← 99.15%
  等人       0.000 s   （当前是非交互审批）
  其余       0.520 s   ← 0.85%（工具执行 + 代码逻辑 + 审计）
```

> **优化方向完全在模型侧**（换模型 / 量化 / 并发）；
> 改代码逻辑、优化审计、加缓存全是白费力气。
> **而这个判断只有拆分之后才做得出来** —— 光看 `61s` 什么也说明不了。

### 自洽性验证

用 `InMemorySpanExporter` 检查 span 树，并**从 span 反算时间与拆分对账**：

```
   └─ llm.parse          0.155s  {gen_ai.request.model: qwen3:4b}
   └─ llm.investigate    0.301s
   └─ human.approval     0.201s  {agent.excluded_from_latency_slo: true}
investigate              0.658s  {total, llm: 0.456, human: 0.202, other: 0.0}

从 span 反算 llm=0.456 human=0.201 → 与拆分一致 ✓
```

**两条独立路径算出同一个数**，才说明埋点没漏也没重。
（这与 §5.2「告警要验证能触发」是同一个思路：不能只看它「没报错」。）

### v1 保持零依赖

追踪 hook 用 `ContextVar` 注入，**v1 单独跑时恒为 `None`，零开销零依赖** ——
tracing 属于部署层的关注点，不该让核心逻辑 import `deployment/`。

用 `ContextVar` 而非普通全局，是因为 `run_alert` 跑在 FastAPI 的 threadpool 里：
并发多个排查时全局变量会互相覆盖。

**非交互审批的诚实说明**：当前 `ok = approve_all`，所以 `human_s` 恒为 0。
仍然把它包进 `human_wait` 是因为换成真 HITL（异步等人点批准）时，
这段会变成几十秒到几小时 —— **结构先就位，比事后改核心逻辑安全**。

---

## 6. Mac 限制的诚实记录

| 项 | 状态 |
|---|---|
| vLLM / PagedAttention 的真实收益 | ❌ **测不了**。Apple Silicon 上 vLLM 只有 CPU 后端 |
| continuous batching 吞吐对比 | ❌ 同上 |
| 按 GPU 负载扩缩容 | ❌ 无独立显存指标（统一内存） |
| 多副本压测 | ❌ 单机单推理端，扩副本只会争抢同一个 Ollama，**更慢** |
| 探针 / SLI / canary / 告警链路 | ✅ **全部是真的** |
| 内存排布约束 | ✅ 真实且已量化（这台机器上比性能调优更是实际瓶颈） |

**HPA 写了但故意不启用**，理由写在 `kubernetes/agent-deployment.yaml` 里：
LLM 服务不能按 CPU 扩（Agent 在等远端推理时 CPU 几乎为零），
正确信号是队列深度（KEDA），且冷启动以十秒计，等扩容起来触发它的那波流量早已超时。

### ⚠️ 一条环境安全注意

这台机器的 `kubectl` current-context 是
**公司的 GKE staging 集群**（形如 `gke_<project>_<region>_<cluster>`）。
本阶段全程用 `KUBECONFIG=/dev/null` 隔离，未向其发送任何写操作；
后续起本地集群时也必须显式指定 context。

---

## 7. 状态

- [x] 框定真问题（由 Phase 5 的三条实测结论推出）
- [x] 量硬约束：24 GiB / swap 5.8 GiB / 释放 14B 回收 8.4 GiB
- [x] 三层指标 `deployment/metrics.py`
- [x] canary `deployment/canary.py` —— 并修掉了判据错误
- [x] 服务化 `deployment/server.py`，探针正负两面均实测
- [x] 告警规则 `monitoring/alerts.yaml`（4 组 9 条，YAML 已校验）
- [x] k8s manifest `kubernetes/agent-deployment.yaml`（三种探针 / 模型不进 Pod）
- [x] 起 kind 集群（**独立 kubeconfig**，未污染指向公司 GKE 的 current-context）
- [x] manifest 通过 **server-side dry-run**（真 schema 校验）
- [x] Prometheus 进集群，抓取 `host.docker.internal:8080`，2 个 target 全 up
- [x] 4 组 9 条告警规则加载成功
- [x] **发现并修掉三个只有真跑才暴露的规则缺陷**（§5.1）：
      `rate()` 保留 label 喷 6 条 · 冷启动比率失真 · **裸 `and` 静默失效**
- [x] 对每条 canary 告警做**可触发性验证**（§5.2）
- [x] Grafana 12.3.1 进集群，datasource + dashboard 全走 provisioning
- [x] Dashboard JSON 落 `monitoring/dashboard.json`（11 面板，描述里写明每个指标的陷阱）
- [x] **逐条验证 14 个面板查询是否真返回数据** → 抓出 2 处埋点缺失（§5.3）
- [x] `/readyz` 改流式 → 就绪探针同时成为 TTFT/TPOT 合成探测（实测 1510ms / 14ms）
- [x] 砍掉错误的 `tool` 标签维度（§5.4）
- [x] 端到端 `/investigate` 跑通（87s），12/14 面板有数据，另 2 个空是合理的
- [x] OpenTelemetry span（`deployment/tracing.py`）—— 时间拆成 等模型/等人/其余，
      「等人」打 `excluded_from_latency_slo` 标记；实测 **99.15% 在等模型**；
      用 InMemoryExporter 做了**从 span 反算的自洽性对账**（§5.6）
- [ ] `dashboard/` 前端（最后做）
- [ ] Grafana Dashboard JSON 落 `monitoring/`
- [x] OpenTelemetry span（`deployment/tracing.py`）—— 时间拆成 等模型/等人/其余，
      「等人」打 `excluded_from_latency_slo` 标记；实测 **99.15% 在等模型**；
      用 InMemoryExporter 做了**从 span 反算的自洽性对账**（§5.6）
- [ ] `dashboard/` 前端（最后做）
