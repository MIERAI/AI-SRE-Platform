"""OpenTelemetry —— **Agent 的 trace 不能照搬微服务那套**。

### 四个结构性差异

| | 普通微服务 | 本 Agent |
|---|---|---|
| 时间尺度 | 毫秒 | 一次排查 **87 秒**（实测） |
| 形状 | 调用树，基本固定 | `investigate ⇄ execute` **有环**，深度事前不可知 |
| 主要成本 | 时间 | **token**（时间只是它的副产品） |
| 有无人类 | 无 | **`interrupt()` 会让 span 跨越人的思考时间** |

最后一条是 Phase 2 的 HITL 设计直接导出的，也是最容易把监控搞坏的一条：

> 一次排查触发人工审批后，`run_alert` 的 span 会一直开着，
> 直到有人点了「批准」。这段时间可能是 30 秒，也可能是第二天早上。
> **照搬普通 trace 语义的话，p99 延迟会被「等人」污染** ——
> 而那根本不是系统的性能问题，扩容一台机器也解决不了。

所以这里把时间**显式拆成三类**，写进 span 属性：

    agent.time.llm_s      等模型（真·系统性能）
    agent.time.human_s    等人（HITL 固有成本，不该进性能 SLO）
    agent.time.other_s    其余（工具执行、代码逻辑）

### 为什么不用现成的 LangChain/LangGraph auto-instrumentation

那些库会把每个 chain/节点自动包成 span，看着很全。但它们
**不知道哪段是在等人** —— 在它们眼里 interrupt 只是一次慢调用。
而「等人」和「等模型」在运维上是完全不同的两件事：
前者要改流程（谁值班、怎么通知），后者要改架构（换模型、加并发）。

### 采样

**不采样。** 普通服务 QPS 高、必须采样；这里一次排查几十秒，
一天的 trace 量比微服务一秒还少 —— 采样只会让本就稀少的样本更难分析。
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

OTLP_ENDPOINT = os.getenv("OTLP_ENDPOINT", "")     # 空 = 不导出到后端
SERVICE = os.getenv("OTEL_SERVICE_NAME", "sre-agent")

_tracer: trace.Tracer | None = None


def init(console: bool = False) -> trace.Tracer:
    """初始化。OTLP_ENDPOINT 为空时只在进程内建 span（仍可用于计时统计）。"""
    global _tracer
    if _tracer is not None:
        return _tracer
    provider = TracerProvider(resource=Resource.create({
        "service.name": SERVICE,
        # 把模型写进 resource 而不是每个 span —— 换模型时整条 trace 都要能区分
        "sre.main_model": os.getenv("MAIN_MODEL", "unknown"),
        "sre.guard": os.getenv("GUARD", "none"),
    }))
    if OTLP_ENDPOINT:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        provider.add_span_processor(BatchSpanProcessor(
            OTLPSpanExporter(endpoint=f"{OTLP_ENDPOINT}/v1/traces")))
    if console:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer("ai-sre-platform")
    return _tracer


def tracer() -> trace.Tracer:
    return _tracer or init()


class TimeSplit:
    """把一次排查的墙钟时间拆成 等模型 / 等人 / 其余。

    ⚑ 这是本模块存在的主要理由。没有这个拆分，
      「模型变慢了」和「值班的人去吃饭了」在 p99 上完全一样。
    """

    def __init__(self):
        self.llm = 0.0
        self.human = 0.0
        self.t0 = time.perf_counter()

    @contextmanager
    def llm_call(self, model: str, kind: str = "chat"):
        t = time.perf_counter()
        with tracer().start_as_current_span(f"llm.{kind}") as sp:
            sp.set_attribute("gen_ai.request.model", model)
            try:
                yield sp
            finally:
                dt = time.perf_counter() - t
                self.llm += dt
                sp.set_attribute("agent.time.llm_s", round(dt, 3))

    @contextmanager
    def human_wait(self, tool: str):
        """人工审批等待。**独立计时，且明确标注它不属于系统性能。**"""
        t = time.perf_counter()
        with tracer().start_as_current_span("human.approval") as sp:
            sp.set_attribute("agent.gated_tool", tool)
            sp.set_attribute("agent.excluded_from_latency_slo", True)
            try:
                yield sp
            finally:
                dt = time.perf_counter() - t
                self.human += dt
                sp.set_attribute("agent.time.human_s", round(dt, 3))

    def finish(self, span) -> dict:
        total = time.perf_counter() - self.t0
        other = max(total - self.llm - self.human, 0.0)
        attrs = {
            "agent.time.total_s": round(total, 3),
            "agent.time.llm_s": round(self.llm, 3),
            "agent.time.human_s": round(self.human, 3),
            "agent.time.other_s": round(other, 3),
        }
        for k, v in attrs.items():
            span.set_attribute(k, v)
        return attrs
