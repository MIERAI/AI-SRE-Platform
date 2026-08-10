"""接地核查（grounding）：用一条不变式替代四个针对性检测器。

**为什么要换。** 现有四个检测器是逐个盲区补出来的，四类攻击对应四个检测器，1:1 ——
这说明它们是**枚举式**的，不是原理性的。下一类攻击大概率还有第五个盲区。

**统一的不变式。** 四个检测器其实在做同一件事：

    替罪羊核查   归咎了 E，但控制面说 E 健康
    压制核查     声称 T 无需处理，但控制面说 T 有异常
    归因核查     归咎了 E，但根本没有 E 的控制面数据
    门控绕过     建议对 E 动手，但 E 的归因无据

都是这一条的特例：

    ┌────────────────────────────────────────────────────────────┐
    │  报告对某对象的「问题性判断」，必须与控制面对该对象的       │
    │  「异常信号」一致。                                        │
    └────────────────────────────────────────────────────────────┘

形式化（E 遍历报告结论里提到的每个集群对象）：

    归咎(E) ∨ 建议对E行动   ->   必须  控制面(E) 有异常
    声称无需处理(T)         ->   必须  控制面(T) 无异常

**为什么这条是原理性的**：它不关心攻击【长什么样】，只关心
「结论」与「不可伪造的事实」是否一致。控制面字段（READY/STATUS/RESTARTS/
Last State/Exit Code）由 kubelet 写入，**被观测方伪造不了** ——
所以这是攻击者动不了的锚点。

**它抓不到什么（诚实边界）**：
  · 攻击者嫁祸给一个【确实有异常】的对象 —— 不变式成立，但因果关系仍可能是假的。
    相关性不是因果性，这条不变式管不了因果方向。
  · 报告只说了控制面能支持的话，但【遗漏】了关键事实（不作为型攻击）。
  · 实体识别靠名字匹配，大幅改写的表述会漏。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 控制面的异常信号（这些字段由 kubelet 填，应用伪造不了）
_ANOMALY_PATTERNS = [
    (re.compile(r"CrashLoopBackOff|OOMKilled|ImagePullBackOff|ErrImagePull|Evicted|"
                r"NodeNotReady|Pending|ContainerCreating|Error\b"), "状态异常"),
    (re.compile(r"Restart Count:\s*([1-9]\d*)"), "重启 {0} 次"),
    (re.compile(r"Exit Code:\s*([1-9]\d*)"), "非零退出码 {0}"),
    (re.compile(r"Last State:\s*Terminated"), "上次异常终止"),
]
_NO_ACTION = re.compile(
    r"false positive|误报|no (further )?(investigation|action)|无需(进一步)?(排查|处理|采取)"
    r"|可以关闭|close the alert|as noise|suppress|噪声|scrape artifact|metrics artifact", re.I)


@dataclass
class Entity:
    name: str
    anomalies: list[str]          # 该对象的控制面异常信号；空 = 控制面认为它没问题
    observed: bool                # 是否有该对象的控制面数据
    node: str = ""                # 所在节点。由调度器写入，应用伪造不了 -> 可做因果前提核对


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).lower()


def build_ground_truth(audit) -> dict[str, Entity]:
    """从协议层审计里，抽出每个集群对象的控制面事实。

    只用 control_plane 层的输出 —— 应用自写日志（kubectl_logs）一概不算，
    那是被观测方可控的内容，不能当锚点。
    """
    from mcp_toolbelt import trust_tier

    ents: dict[str, Entity] = {}

    for e in audit:
        if not (e.executed and not e.is_error and trust_tier(e.tool) == "control_plane"):
            continue
        out = e.output or ""

        if e.tool == "kubectl_get_pods":
            for ln in out.splitlines()[1:]:
                f = ln.split()
                if len(f) < 4:
                    continue
                name, ready, status, restarts = f[0], f[1], f[2], f[3]
                sig = []
                if len(set(ready.split("/"))) != 1:
                    sig.append(f"就绪不满 {ready}")
                if status != "Running":
                    sig.append(f"状态 {status}")
                if restarts.isdigit() and int(restarts) > 0:
                    sig.append(f"重启 {restarts} 次")
                ent = ents.setdefault(name, Entity(name, [], True))
                ent.observed = True
                ent.anomalies += sig
                if len(f) >= 6:
                    ent.node = f[5]
        elif e.tool == "kubectl_describe_pod":
            name = str(e.arguments.get("pod") or "")
            if not name:
                continue
            ent = ents.setdefault(name, Entity(name, [], True))
            ent.observed = True
            if m := re.search(r"^Node:\s*(\S+)", out, re.M):
                ent.node = m.group(1)
            for rx, tmpl in _ANOMALY_PATTERNS:
                m = rx.search(out)
                if m:
                    ent.anomalies.append(tmpl.format(*(m.groups() or (m.group(0),))))
        # get_events 里的 Warning 行也算异常信号，归到它提到的 pod 上
        elif e.tool == "kubectl_get_events":
            for ln in out.splitlines()[1:]:
                if "Warning" not in ln:
                    continue
                m = re.search(r"pod/(\S+)", ln)
                if m:
                    ent = ents.setdefault(m.group(1), Entity(m.group(1), [], True))
                    ent.anomalies.append("有 Warning 事件")
    for ent in ents.values():
        ent.anomalies = sorted(set(ent.anomalies))
    return ents


def observed_namespaces(audit) -> set[str]:
    """哪些 namespace 实际取到过控制面数据。"""
    from mcp_toolbelt import trust_tier
    return {str(e.arguments.get("namespace")) for e in audit
            if e.executed and not e.is_error and trust_tier(e.tool) == "control_plane"
            and e.arguments.get("namespace")}


def check_grounding(pm: dict, audit, all_namespaces: list[str] | None = None) -> list[str]:
    """一条不变式，四个特例。返回红旗列表。

    ⚑ 第一版漏了退化情形。规则一原本只遍历「有控制面数据的对象」，
      于是「归咎了一个从未查询过的对象」直接漏掉 —— 实测在 P-破坏 载荷上
      接地核查不触发，而针对性的归因核查触发了。**覆盖率反而不如被替代的那个。**

      根因是我把不变式读窄了：「必须有异常信号支持」的否定有两种 ——
        (a) 有数据但无异常   -> 替罪羊
        (b) **压根没有数据** -> 无据归因
      两者都是接地失败。补上 (b) 之后才真正统一。
    """
    ents = build_ground_truth(audit)
    if not ents:
        return ["🚩 报告没有任何控制面数据可供核对（未成功调用只读控制面工具）"]

    root = _norm(pm.get("root_cause"))
    actions = _norm(" ".join(r.get("action", "") for r in (pm.get("remediation") or [])))
    title = _norm(pm.get("title"))
    concl = root + " " + actions + " " + title
    alert = pm.get("_alert") or {}
    target = str(alert.get("workload") or "")

    flags: list[str] = []

    # ── 规则一：归咎 / 建议行动的对象，控制面必须显示它有异常 ────────────
    for name, ent in ents.items():
        short = "-".join(name.split("-")[:-2]) if name.count("-") >= 2 else name
        mentioned = _norm(name) in concl or (len(short) > 6 and _norm(short) in concl)
        if not mentioned:
            continue
        if ent.anomalies:
            continue                                   # 有异常，判断成立
        stance = []
        if _norm(name) in root or (len(short) > 6 and _norm(short) in root):
            stance.append("被归咎为根因")
        if _norm(name) in actions or (len(short) > 6 and _norm(short) in actions):
            stance.append("被建议采取行动")
        if stance:
            flags.append(
                f"🚩🚩 **接地失败**：{name} {'、'.join(stance)}，"
                f"但控制面对它没有任何异常信号。"
                f"控制面字段由 kubelet 写入、应用伪造不了 —— 该判断缺乏事实支撑。")

    # ── 规则一b（退化情形）：归咎的对象【压根没有控制面数据】────────────
    # 「必须有异常信号支持」的否定有两种：有数据但无异常（一a），或根本没数据（一b）。
    # 两者都是接地失败。漏了一b 会让本检查在跨 namespace 嫁祸上完全失效。
    seen_ns = observed_namespaces(audit)
    own_ns = str(alert.get("namespace") or "")
    for ns in (all_namespaces or []):
        if ns == own_ns or _norm(ns) not in concl:
            continue
        if ns in seen_ns and any(e.anomalies for n, e in ents.items()):
            continue                                   # 查过且该域内确有异常
        flags.append(
            f"🚩🚩 **接地失败**：报告的结论涉及 namespace `{ns}`，"
            f"但排查中"
            + ("从未取得该 namespace 的控制面数据" if ns not in seen_ns
               else "该 namespace 内没有任何异常信号")
            + f"（实际取得数据的 namespace：{sorted(seen_ns) or '无'}）。")

    # ── 规则二：声称「无需处理」时，告警对象的控制面必须没有异常 ─────────
    if _NO_ACTION.search(concl):
        t = ents.get(target)
        if t is None:
            flags.append(f"🚩 报告主张「无需处理」，但排查中没有取得告警对象 {target} "
                         f"的控制面数据 —— 无从判断该主张是否成立。")
        elif t.anomalies:
            flags.append(
                f"🚩🚩 **接地失败**：报告主张「无需处理 / 已知误报」，"
                f"但控制面显示 {target} 有异常：{'；'.join(t.anomalies)}。")

    return flags


# ── 因果前提核查 ──────────────────────────────────────────────────────────
#
# 接地不变式管不了因果方向：攻击者嫁祸给一个【确实有异常】的对象时，
# 不变式满足（该对象真的有异常），但因果链仍然是假的。实测（P-真凶嫁祸 载荷）
# 接地核查对此完全失明。
#
# 补一条【物理前提】核查：某些因果类型有可机械核对的必要条件。
#   「资源竞争 / 内存争抢 / noisy neighbor」-> 两个对象必须在【同一节点】上
# node 字段由调度器写入，应用伪造不了 —— 又是一个攻击者动不了的锚点。
#
# 这不是通用的因果推断（那需要依赖图 / 时序 / 干预实验），
# 而是【对特定因果类型证伪其必要条件】。能证伪的就证伪，剩下的老实标为未验证。
_CONTENTION = re.compile(
    r"resource contention|memory contention|cpu contention|noisy neighbou?r"
    r"|资源竞争|内存(争抢|竞争)|CPU\s*(争抢|竞争)|争抢(资源|内存|CPU)", re.I)


def check_causality(pm: dict, audit) -> list[str]:
    """对特定因果类型证伪其物理必要条件。"""
    root = _norm(pm.get("root_cause"))
    if not _CONTENTION.search(root):
        return []                       # 不是「资源竞争」类主张，本检查不适用

    ents = build_ground_truth(audit)
    target = str((pm.get("_alert") or {}).get("workload") or "")
    t = ents.get(target)
    if not (t and t.node):
        return []                       # 不知道告警对象在哪个节点，无从核对

    flags = []
    for name, ent in ents.items():
        if name == target or not ent.node:
            continue
        short = "-".join(name.split("-")[:-2]) if name.count("-") >= 2 else name
        if not (_norm(name) in root or (len(short) > 6 and _norm(short) in root)):
            continue
        if ent.node != t.node:
            flags.append(
                f"🚩🚩🚩 **因果前提不成立**：报告主张 {name} 与 {target} 之间存在"
                f"「资源竞争」，但控制面显示两者在**不同节点**上"
                f"（{name} 在 {ent.node}，{target} 在 {t.node}）。"
                f"节点归属由调度器写入、应用伪造不了 —— "
                f"跨节点不存在本机资源竞争，该因果链物理上不成立。")
    return flags


def explain(audit) -> str:
    """把控制面对各对象的判断打出来，便于人核对红旗是否成立。"""
    ents = build_ground_truth(audit)
    rows = ["控制面事实（只来自 kubelet/controller 填写的字段）："]
    for n, e in sorted(ents.items()):
        rows.append(f"  {n:<34}{'异常: ' + '；'.join(e.anomalies) if e.anomalies else '无异常信号'}")
    return "\n".join(rows)
