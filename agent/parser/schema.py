"""告警解析的目标 schema。

写成标准 JSON Schema 而不是 pydantic 模型，因为它要一物三用：
  1. 塞进 System Prompt 告诉模型输出格式（路线一：prompt 约束）
  2. 直接传给 Ollama 的 format 参数做约束解码（路线二：确定性保证）
  3. 校验模型的实际输出
"""

SEVERITIES = ["critical", "warning", "info"]

# v1：凭 SRE 常识拍的 11 个类型。实测 20 条告警有 40% 落到 Unknown，其中只有 2 条
# 是「真的信息不足」，6 条是枚举压根没这个类目。保留它作为对照基线。
ERROR_TYPES_V1 = [
    "OOMKilled",
    "CrashLoopBackOff",
    "ImagePullBackOff",
    "Evicted",
    "NodeNotReady",
    "DiskPressure",
    "ProbeFailure",
    "ResourceQuotaExceeded",
    "NetworkUnavailable",   # 误设计：这是 Node condition，装不了 Pod 沙箱/CNI 错误
    "CertificateExpiry",
    "Unknown",
]

# v2：从 v1 的实测 Unknown 分布反推补齐。每个新类目都对应一条具体的失败用例。
ERROR_TYPES_V2 = [
    "OOMKilled",
    "CrashLoopBackOff",
    "ImagePullBackOff",
    "ContainerStartError",        # a16 容器启动失败（exec/权限/入口点）
    "Evicted",
    "NodeNotReady",
    "DiskPressure",               # 节点存储压力
    "VolumeFillingUp",            # a18 PVC 将满，和节点压力不是一回事
    "ProbeFailure",
    "ResourceQuotaExceeded",
    "ResourceOvercommit",         # a06 集群超额申请，是隐患不是故障
    "FailedScheduling",           # a20 调度失败（亲和性/资源不足）
    "PodSandboxError",            # a17 CNI / 沙箱创建失败
    "UpstreamDependencyFailure",  # a05 a19 根因在上游服务
    "CertificateExpiry",
    "Unknown",                    # 收窄语义：只在真的信息不足时使用
]

ERROR_TYPES = ERROR_TYPES_V2      # 默认用 v2

def build_schema(error_types=None, split_cause=False) -> dict:
    """构造 schema。

    error_types  用 V1 还是 V2 枚举（对照实验用）
    split_cause  True 时把 error_type 拆成 symptom + cause 两个字段。
                 起因：a02 的输入里 `State: CrashLoopBackOff`（现象）和
                 `Last State: OOMKilled`（原因）同时存在，一个字段装不下。
    """
    ets = error_types or ERROR_TYPES
    props = {
        "severity": {"type": "string", "enum": SEVERITIES},
        "namespace": {"type": "string"},
        "workload": {"type": "string", "description": "Pod / Deployment / Node 名称"},
    }
    if split_cause:
        props["symptom"] = {"type": "string", "enum": ets,
                            "description": "原文直接写出来的当前状态"}
        props["cause"] = {"type": "string", "enum": ets,
                          "description": "推断的根因类型，可以和 symptom 相同"}
    else:
        props["error_type"] = {"type": "string", "enum": ets}
    props |= {
        "root_cause": {"type": "string", "description": "一句话根因假设"},
        "suggested_action": {"type": "string", "description": "具体到命令或配置项的建议"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    }
    return {"type": "object", "properties": props,
            "required": list(props), "additionalProperties": False}


ALERT_SCHEMA = build_schema()


def validate(obj, schema=None) -> list[str]:
    """轻量校验，返回问题列表。不引第三方库，因为这里要能看清每一条规则。"""
    schema = schema or ALERT_SCHEMA
    errs = []
    if not isinstance(obj, dict):
        return [f"顶层不是 object，是 {type(obj).__name__}"]

    props = schema["properties"]
    for k in schema["required"]:
        if k not in obj:
            errs.append(f"缺字段 {k}")
    for k in obj:
        if k not in props:
            errs.append(f"多余字段 {k}")

    if (s := obj.get("severity")) is not None and s not in SEVERITIES:
        errs.append(f"severity 非法值 {s!r}")
    for f in ("error_type", "symptom", "cause"):
        if f in props and (e := obj.get(f)) is not None and e not in props[f]["enum"]:
            errs.append(f"{f} 非法值 {e!r}")
    c = obj.get("confidence")
    if c is not None:
        if not isinstance(c, (int, float)) or isinstance(c, bool):
            errs.append(f"confidence 不是数字：{c!r}")
        elif not 0 <= c <= 1:
            errs.append(f"confidence 越界 {c}")
    for k in ("namespace", "workload", "root_cause", "suggested_action"):
        if (v := obj.get(k)) is not None and not isinstance(v, str):
            errs.append(f"{k} 不是字符串：{type(v).__name__}")
    return errs
