"""告警解析的目标 schema。

写成标准 JSON Schema 而不是 pydantic 模型，因为它要一物三用：
  1. 塞进 System Prompt 告诉模型输出格式（路线一：prompt 约束）
  2. 直接传给 Ollama 的 format 参数做约束解码（路线二：确定性保证）
  3. 校验模型的实际输出
"""

SEVERITIES = ["critical", "warning", "info"]

ERROR_TYPES = [
    "OOMKilled",
    "CrashLoopBackOff",
    "ImagePullBackOff",
    "Evicted",
    "NodeNotReady",
    "DiskPressure",
    "ProbeFailure",
    "ResourceQuotaExceeded",
    "NetworkUnavailable",
    "CertificateExpiry",
    "Unknown",          # 兜底：宁可让模型说不知道，也不要让它硬套一个类型
]

ALERT_SCHEMA = {
    "type": "object",
    "properties": {
        "severity": {"type": "string", "enum": SEVERITIES},
        "namespace": {"type": "string"},
        "workload": {"type": "string", "description": "Pod / Deployment / Node 名称"},
        "error_type": {"type": "string", "enum": ERROR_TYPES},
        "root_cause": {"type": "string", "description": "一句话根因假设"},
        "suggested_action": {"type": "string", "description": "具体到命令或配置项的建议"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": [
        "severity", "namespace", "workload",
        "error_type", "root_cause", "suggested_action", "confidence",
    ],
    "additionalProperties": False,
}


def validate(obj) -> list[str]:
    """轻量校验，返回问题列表。不引第三方库，因为这里要能看清每一条规则。"""
    errs = []
    if not isinstance(obj, dict):
        return [f"顶层不是 object，是 {type(obj).__name__}"]

    props = ALERT_SCHEMA["properties"]
    for k in ALERT_SCHEMA["required"]:
        if k not in obj:
            errs.append(f"缺字段 {k}")
    for k in obj:
        if k not in props:
            errs.append(f"多余字段 {k}")

    if (s := obj.get("severity")) is not None and s not in SEVERITIES:
        errs.append(f"severity 非法值 {s!r}")
    if (e := obj.get("error_type")) is not None and e not in ERROR_TYPES:
        errs.append(f"error_type 非法值 {e!r}")
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
