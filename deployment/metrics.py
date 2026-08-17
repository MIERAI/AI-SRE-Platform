"""SLI 定义 —— **为 LLM 防御设计的指标，不是把 Web 服务那套搬过来**。

### 为什么不能照搬

Phase 5 实测出三件事，它们让传统监控对本系统彻底失效：

1. **「净化剥离了 N 行」不是防御生效的证据** ——
   P-机器格式破坏 剥离了 6 行，H2 危害一点没降（2/2 → 2/2）。
2. **盲点会转移** —— 补了「人写的无害文本」后，盲点转到了「机器格式的有害文本」。
   今天有效的判别器，明天可能对新形式完全失明。
3. **生产中没有 ground truth** —— 你不知道那条容器日志里到底有没有注入。

**一个已经完全失效的净化器，它的 QPS、延迟、错误率全都是绿的。**
所以这里的指标分三层，第三层才是真正回答「防御还有效吗」的。

### 三层

    ① 传统       —— 必要但不充分。服务活着不等于防御活着。
    ② LLM 专属   —— TTFT / TPOT 分开，因为 prefill 是 compute-bound、
                    decode 是 memory-bandwidth-bound（Phase 0 实测），
                    把它们平均成一个「延迟」会同时掩盖两种问题。
    ③ 防御有效性 —— canary：**唯一能在生产中拿到 ground truth 的办法**。

### ③ 为什么必须**分家族**统计

Phase 5 的核心教训是盲点会转移。如果只报一个总的 canary 检出率，
某一类形式（比如机器格式）整体失效时，总数只会小幅下滑，被其他家族的高分掩盖。
**必须按家族出指标并分别设 SLO**，任一家族跌破就告警。

这与 Phase 5 的 `eval_detect.py` 按家族分组报告是同一个道理 ——
在那里，总准确率把 F5 的 33% 掩盖成了 60%。
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

NS = "sre_agent"

# ── ① 传统：必要但不充分 ──────────────────────────────────────────────────
investigations = Counter(
    f"{NS}_investigations_total", "完成的排查次数", ["alert", "outcome"])

investigation_seconds = Histogram(
    f"{NS}_investigation_duration_seconds", "单次排查耗时",
    ["alert"],
    # LLM 排查是几十秒级，Web 服务那套 (5ms..10s) 的默认分桶全部落在最后一桶里
    buckets=(5, 10, 20, 30, 45, 60, 90, 120, 180, 300))

tool_calls = Counter(
    f"{NS}_tool_calls_total", "MCP 工具调用", ["tool", "tier", "outcome"])

# 被人工审批拦下的破坏性操作。**这个数不是越低越好** ——
# 归零可能意味着门控失效，也可能意味着 Agent 不再尝试修复（Phase 5 见过后者）。
gated_calls = Counter(
    f"{NS}_gated_calls_total", "触发人工审批的调用", ["tool", "approved"])

# ── ② LLM 专属 ───────────────────────────────────────────────────────────
#
# ⚑ TTFT 与 TPOT 必须分开。Phase 0 实测：prefill 是 compute-bound、
#   decode 是 memory-bandwidth-bound，两者对 batch size 的反应相反。
#   合成一个「平均延迟」会让「prompt 变长」和「显存带宽被抢」看起来一模一样。
llm_ttft = Histogram(
    f"{NS}_llm_ttft_seconds", "首 token 时间（prefill 侧）", ["model"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30))

llm_tpot = Histogram(
    f"{NS}_llm_tpot_seconds", "每输出 token 时间（decode 侧）", ["model"],
    buckets=(0.005, 0.01, 0.02, 0.05, 0.1, 0.25, 0.5))

llm_tokens = Counter(
    f"{NS}_llm_tokens_total", "token 数", ["model", "kind"])   # kind: prompt|completion

# 模型常驻内存 —— 24GB 机器上这是**排布约束**，不是好奇心：
# 14B(9.3G) + judge 4B(2.5G) 已占去一半，Phase 5 实测。
llm_resident_bytes = Gauge(
    f"{NS}_llm_resident_bytes", "模型常驻内存", ["model"])

# ── ③ 防御有效性：核心 ───────────────────────────────────────────────────
# ⚑ **没有 `tool` 维度**，这是实测后砍掉的。
#   原本按 tool 分标签（canary / kubectl_logs），跑起来发现全部记到了 tool="canary" 下：
#   canary 线程与 /investigate 共享同一个 `InputGuard.stat`（进程内累计值）
#   和同一个快照，canary 每 60s 醒来时会把 investigate 期间产生的增量
#   一并算走并打上自己的标签。
#   **一个全局累计的 stat 里还原不出调用来源** —— 与其给出错误归属，不如不给。
#   真要分来源，得让 InputGuard 内部按 tool 分桶累计，那是另一件事。
guard_scans = Counter(
    "sre_guard_scans_total", "输入净化扫描", ["verdict"])  # verdict: clean|flagged

# ⚠️ 这个指标**单独看没有意义**（Phase 5：剥离 6 行而危害未降）。
#    放在这里只为与 canary 检出率交叉看：剥离量大 + canary 检出率跌 = 正在乱删。
guard_lines_removed = Counter(
    "sre_guard_lines_removed_total", "被剥离的行数（勿单独解读）", [])

# 整段丢弃 —— 直接反映**排查质量的损失**。定位不到就丢整段是明确的取舍，
# 但丢得太多说明判别器对当前日志分布失去了定位能力。
guard_fallback_dropped = Counter(
    "sre_guard_fallback_dropped_total", "定位失败导致整段丢弃", [])

guard_seconds = Histogram(
    "sre_guard_duration_seconds", "净化耗时", ["backend"],
    buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10, 30))

# ── canary：生产中唯一的 ground truth ────────────────────────────────────
#
# **必须分家族**。若只报总检出率，某一类形式整体失效时总数只小幅下滑，
# 会被其他家族的高分掩盖 —— 与 Phase 5 里总准确率把 F5 的 33% 掩盖成 60% 同理。
canary_checks = Counter(
    "sre_guard_canary_checks_total", "canary 探测", ["family", "result"])

# 分家族的滚动检出率，直接作为 SLI。任一家族跌破阈值即告警。
canary_detection_rate = Gauge(
    "sre_guard_canary_detection_rate", "canary 检出率（按家族）", ["family"])

# 干净样本被误判的比例。**必须与检出率一起看** ——
# 只看检出率的话，「把一切都判为注入」能拿满分（Phase 5 的 v1 模型就是这样，
# F6a 100% 而 F6b 只有 34.4%）。
canary_false_positive_rate = Gauge(
    "sre_guard_canary_false_positive_rate", "canary 干净样本误报率")

# ── ④ 纵深防御的最后一道：下游机械检测器 ─────────────────────────────────
#
# 这些判据锚在**应用伪造不了的控制面字段**上（READY/STATUS/RESTARTS/Exit Code/Node），
# 是 Phase 4 找到的唯一站得住的地基。它们触发说明净化漏了，但系统还没沦陷。
harm_detectors = Counter(
    f"{NS}_harm_detector_fired_total", "下游机械检测器触发", ["detector"])


def snapshot(stat) -> tuple:
    """取 InputGuard 累计统计的快照，用于算增量。"""
    return (stat.scanned, stat.flagged, stat.lines_removed,
            stat.fallback_dropped, stat.seconds)


def observe_guard(stat, backend: str, since: tuple | None = None) -> tuple:
    """把 InputGuard 的统计打进指标，返回新快照。

    ⚑ `since` 不能省。`InputGuard.stat` 是**进程内累计**的，
      而 Counter 也是累计的 —— 直接把累计值 `inc()` 进去会重复计数（O(n²) 式膨胀）。
      必须传上次快照、只加增量。

    ⚑ 这个函数原本只在 `/investigate` 里被调用，**canary 循环没调** ——
      于是 canary 每 120s 在调 `sanitize()`，而 guard_scans / lines_removed /
      fallback_dropped 三个指标永远是空的，Grafana 上对应面板一片空白。
      是「验证每个面板的查询是否真返回数据」这一步把它抓出来的，
      否则 dashboard 部署成功、语法零错误、一半面板是死的。
    """
    cur = snapshot(stat)
    if since is None:
        since = (0, 0, 0, 0, 0.0)
    d_scanned, d_flagged, d_lines, d_drop, d_sec = (a - b for a, b in zip(cur, since))

    clean = max(d_scanned - d_flagged, 0)
    if clean:
        guard_scans.labels(verdict="clean").inc(clean)
    if d_flagged > 0:
        guard_scans.labels(verdict="flagged").inc(d_flagged)
    if d_lines > 0:
        guard_lines_removed.inc(d_lines)
    if d_drop > 0:
        guard_fallback_dropped.inc(d_drop)
    if d_sec > 0:
        guard_seconds.labels(backend=backend).observe(d_sec)
    return cur
