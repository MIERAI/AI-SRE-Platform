"""AI-SRE Agent 的服务化入口。

    uv run uvicorn deployment.server:app --port 8080
    curl localhost:8080/readyz | jq
    curl -s localhost:8080/metrics | grep canary

### 就绪探针为什么不能只探端口

原始规划里有一条：**「LLM 服务的 readiness 不是端口通，而是模型加载完且能返回一个
token」**。这条在本项目里有具体的量化依据：

- Phase 5 实测模型加载耗时以**十秒计**（4B 首次加载 ~4 分钟含下载，热态仍需数秒）；
- 端口在进程起来的瞬间就通了，此时把流量切过来会全部超时；
- 更隐蔽的一种：Phase 3 撞到过 **ollama server 是旧版、`/api/version` 正常
  但 `/api/chat` 永久挂起**。只探版本端点会一路绿灯。

→ `/readyz` **真的生成一个 token**。这是唯一能同时排除上述三种情况的探法。

### 存活与就绪必须分开

`/healthz` 只表示进程没死。若把「模型没加载好」也判成 unhealthy，
k8s 会重启 Pod —— 而重启只会让模型重新加载一遍，**把慢启动变成崩溃循环**。
慢启动用 `startupProbe` 兜，不用 liveness。
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import requests
from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "deployment"))

import metrics as M           # noqa: E402
import tracing as T           # noqa: E402
from canary import CanaryRunner  # noqa: E402

OLLAMA = os.getenv("OLLAMA_HOST", "http://localhost:11434")
MAIN_MODEL = os.getenv("MAIN_MODEL", "qwen3:14b")
GUARD_SPEC = os.getenv("GUARD", "none")          # none | mlx | ollama
CANARY_INTERVAL = int(os.getenv("CANARY_INTERVAL", "0"))   # 秒；0=关闭

STATE: dict = {"guard": None, "ready": False, "started": time.time(),
               "canary": CanaryRunner(), "last_canary": None,
               "guard_snap": None}   # 上次上报的 guard 统计快照，用于算增量


def _probe_generation() -> tuple[bool, str]:
    """真的让模型吐 token。这是就绪的唯一可信判据。

    ⚑ 用**流式**，因为它顺便解决了另一个问题：
      `llm_ttft` / `llm_tpot` 两个指标原本定义了却**从未被 observe** ——
      Grafana 上那两个面板永远空白，而 dashboard「部署成功」、语法零错误。
      非流式调用拿不到首 token 时间（只能拿到总耗时），
      改成流式后，这个每 30 秒跑一次的就绪探针**同时是一次合成性能探测**：

          第一个 chunk 到达      -> TTFT（prefill 侧，compute-bound）
          后续 chunk 的平均间隔  -> TPOT（decode 侧，memory-bandwidth-bound）

      Phase 0 实测两者是不同性质的负载，所以必须分开量，不能用总耗时除以 token 数。
    """
    t0 = time.perf_counter()
    try:
        r = requests.post(f"{OLLAMA}/api/chat", json={
            "model": MAIN_MODEL, "messages": [{"role": "user", "content": "ok"}],
            "stream": True, "think": False,
            "options": {"num_predict": 8, "temperature": 0},
            "keep_alive": "30m"}, timeout=90, stream=True)
        r.raise_for_status()
        ttft = None
        stamps: list[float] = []
        chars = 0
        for line in r.iter_lines():
            if not line:
                continue
            now = time.perf_counter()
            if ttft is None:
                ttft = now - t0
                M.llm_ttft.labels(model=MAIN_MODEL).observe(ttft)
            stamps.append(now)
            try:
                chars += len(json.loads(line).get("message", {}).get("content", ""))
            except Exception:                    # noqa: BLE001
                pass
        # TPOT = 相邻 token 的平均间隔。**不能用总耗时/token 数** ——
        # 那样会把 prefill 的时间摊进 decode，两种负载被混成一个数字。
        if len(stamps) >= 2:
            tpot = (stamps[-1] - stamps[0]) / (len(stamps) - 1)
            M.llm_tpot.labels(model=MAIN_MODEL).observe(tpot)
            M.llm_tokens.labels(model=MAIN_MODEL, kind="completion").inc(len(stamps))
            return True, (f"TTFT {ttft*1000:.0f}ms · TPOT {tpot*1000:.0f}ms · "
                          f"{len(stamps)} chunk / {chars} 字符")
        return True, f"生成 {chars} 字符（chunk 不足，未测 TPOT）"
    except Exception as e:                       # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def _canary_loop():
    """后台 canary。**这是生产中唯一的 ground truth 来源。**"""
    while True:
        time.sleep(CANARY_INTERVAL)
        g = STATE.get("guard")
        if g is None:
            continue
        try:
            STATE["last_canary"] = STATE["canary"].probe(g, metrics=M)
            # ⚑ canary 也要记 guard 指标。漏掉这一句的后果是：
            #   canary 每 120s 在调 sanitize()，而 guard_scans / lines_removed /
            #   fallback_dropped 永远为空，Grafana 上三个面板一片空白 ——
            #   而 dashboard「部署成功」、语法零错误，没人会发现。
            STATE["guard_snap"] = M.observe_guard(
                g.stat, GUARD_SPEC, since=STATE.get("guard_snap"))
        except Exception:                        # noqa: BLE001
            pass                                  # 探测失败不能拖垮主服务


@asynccontextmanager
async def lifespan(app: FastAPI):
    if GUARD_SPEC != "none":
        import input_guard
        STATE["guard"] = input_guard.build(GUARD_SPEC)
        # Phase 5 实测：微调 4B judge 常驻 2.5 GB、14B 主模型 9.3 GB。
        # 26 GB 的机器上这是排布约束，所以把它做成指标而不是注释。
        M.llm_resident_bytes.labels(model=f"guard:{GUARD_SPEC}").set(2.5e9)
    M.llm_resident_bytes.labels(model=MAIN_MODEL).set(9.3e9)
    T.init(console=os.getenv("OTEL_CONSOLE", "") == "1")
    if CANARY_INTERVAL > 0:
        threading.Thread(target=_canary_loop, daemon=True).start()
    yield


app = FastAPI(title="AI-SRE Agent", lifespan=lifespan)


class InvestigateReq(BaseModel):
    alert: str = "A"
    use_guard: bool = True
    use_gate: bool = True
    use_boundary: bool = True


@app.get("/healthz")
def healthz():
    """存活：进程没死。**不检查模型** —— 否则慢启动会被 k8s 判成崩溃并重启。"""
    return {"status": "alive", "uptime_s": round(time.time() - STATE["started"], 1)}


@app.get("/readyz")
def readyz():
    ok, detail = _probe_generation()
    STATE["ready"] = ok
    body = {"ready": ok, "model": MAIN_MODEL, "detail": detail,
            "guard": GUARD_SPEC}
    if not ok:
        raise HTTPException(status_code=503, detail=body)
    return body


@app.get("/metrics")
def prom():
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/canary")
def canary_status():
    """人读的 canary 视图。**检出率与误报率必须一起看** ——
    只看检出率的话，「全判 true」能拿满分（Phase 5 的 v1 模型正是如此）。"""
    r: CanaryRunner = STATE["canary"]
    return {
        "detection_rate": {f: round(sum(h) / len(h), 3)
                           for f, h in r.history.items() if h},
        "false_positive_rate": (round(sum(r.clean_history) / len(r.clean_history), 3)
                                if r.clean_history else None),
        "samples": {f: len(h) for f, h in r.history.items()},
        "last": STATE["last_canary"],
    }


@app.post("/investigate")
async def investigate(req: InvestigateReq):
    import v1
    t0 = time.perf_counter()

    ts = T.TimeSplit()

    def _run():
        v1.TRACE.set(ts)          # ContextVar 在 threadpool 线程里生效
        try:
            return v1.run_alert(req.alert, approve_all=False, verbose=False, use_rag=False,
                                use_boundary=req.use_boundary, use_gate=req.use_gate,
                                guard=STATE["guard"] if req.use_guard else None)
        finally:
            v1.TRACE.set(None)

    # run_alert 是同步阻塞且以【几十秒】计，必须挪出事件循环，
    # 否则 /healthz 和 /metrics 在排查期间全部超时 —— 监控恰好在最需要时失明。
    with T.tracer().start_as_current_span("investigate") as root:
        root.set_attribute("sre.alert", req.alert)
        root.set_attribute("sre.use_guard", req.use_guard)
        root.set_attribute("sre.use_gate", req.use_gate)
        rep = await run_in_threadpool(_run)
        split = ts.finish(root)
    dt = time.perf_counter() - t0

    M.investigations.labels(alert=req.alert,
                            outcome="ok" if rep.get("root_cause") else "empty").inc()
    M.investigation_seconds.labels(alert=req.alert).observe(dt)
    for e in (rep.get("_audit") or {}).get("executed", []):
        M.tool_calls.labels(tool=e, tier="-", outcome="ok").inc()
    for d in ("_grounding_flags", "_causality_flags", "_provenance_flags",
              "_suppression_flags", "_scapegoat_flags", "_attribution_flags",
              "_relay_flags"):
        if rep.get(d):
            M.harm_detectors.labels(detector=d.strip("_")).inc()
    if STATE["guard"] is not None and req.use_guard:
        # since= 不能省：stat 是进程内累计值，直接 inc 会重复计数
        STATE["guard_snap"] = M.observe_guard(
            STATE["guard"].stat, GUARD_SPEC, since=STATE.get("guard_snap"))

    return {"elapsed_s": round(dt, 1),
            # 时间拆分：**「等模型」和「等人」必须分开** ——
            # 前者要改架构，后者要改流程，混成一个 p99 两者都看不见。
            "time_split": split,
            "root_cause": rep.get("root_cause"),
            "severity": rep.get("severity"),
            "guard": rep.get("_guard", {}),
            "detectors_fired": [d.strip("_") for d in rep if d.startswith("_")
                                and d.endswith("_flags") and rep[d]]}
