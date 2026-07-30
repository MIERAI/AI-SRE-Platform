"""手写裸 JSON-RPC 客户端，驱动我们自己的 MCP Server。

刻意【不用】SDK 的 ClientSession —— 那会把协议藏起来。这里每一个收发的帧都打出来，
目的是回答三个追问：

  1. initialize 握手到底协商了什么？
  2. tools/list 返回的 schema 和 Phase 1 里 Ollama 的 tools 字段是什么关系？
     「写一次工具所有模型复用」，复用具体发生在哪一层？
  3. 相比普通 Function Calling，MCP 多出来的成本是什么？

MCP over stdio 就是【按行分隔的 JSON-RPC 2.0】，没别的。

    uv run mcp/probe_protocol.py
"""

import json
import subprocess
import sys
import time
from pathlib import Path

from mcp.types import LATEST_PROTOCOL_VERSION

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "mcp" / "k8s_server" / "server.py"


class RawStdioClient:
    """够用的最小实现：写一行 JSON、读一行 JSON。"""

    def __init__(self, cmd: list[str], verbose: bool = True):
        self.p = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, cwd=str(ROOT),
        )
        self._id = 0
        self.verbose = verbose
        self.bytes_sent = self.bytes_recv = 0

    def _send(self, obj: dict, label: str):
        line = json.dumps(obj, ensure_ascii=False)
        self.bytes_sent += len(line.encode())
        if self.verbose:
            print(f"\n\033[36m→ {label}\033[0m")
            print(_pretty(obj, 1400))
        self.p.stdin.write(line + "\n")
        self.p.stdin.flush()

    def _recv(self, label: str) -> dict:
        line = self.p.stdout.readline()
        if not line:
            err = self.p.stderr.read()
            raise RuntimeError(f"服务端没有响应就退出了。stderr:\n{err}")
        self.bytes_recv += len(line.encode())
        obj = json.loads(line)
        if self.verbose:
            print(f"\n\033[32m← {label}\033[0m")
            print(_pretty(obj, 2200))
        return obj

    # ── 便捷封装，给 bridge_agent 用 ──────────────────────────────────────

    def handshake(self) -> dict:
        init = self.request("initialize", {
            "protocolVersion": LATEST_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "bridge-agent", "version": "0.0.1"},
        })
        self.notify("notifications/initialized")
        return init["result"]

    def list_tools(self) -> list[dict]:
        return self.request("tools/list")["result"]["tools"]

    def call_tool(self, name: str, args: dict) -> tuple[str, bool]:
        r = self.request("tools/call", {"name": name, "arguments": args})["result"]
        text = "\n".join(c.get("text", "") for c in r.get("content", []))
        return text, bool(r.get("isError"))

    def request(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        self._send({"jsonrpc": "2.0", "id": self._id, "method": method,
                    **({"params": params} if params is not None else {})}, f"请求 {method}")
        return self._recv(f"响应 {method}")

    def notify(self, method: str, params: dict | None = None):
        self._send({"jsonrpc": "2.0", "method": method,
                    **({"params": params} if params is not None else {})},
                   f"通知 {method}（无 id，不等响应）")

    def close(self):
        self.p.stdin.close()
        self.p.terminate()
        self.p.wait(timeout=5)


def _pretty(obj, limit: int) -> str:
    s = json.dumps(obj, ensure_ascii=False, indent=2)
    if len(s) > limit:
        s = s[:limit] + f"\n  … （截断，全长 {len(json.dumps(obj, ensure_ascii=False))} 字符）"
    return "\n".join("  " + ln for ln in s.splitlines())


def main():
    print("=" * 96)
    print(f"手写 JSON-RPC 客户端 → 我们自己的 MCP Server（stdio 传输）")
    print(f"客户端声明的协议版本：{LATEST_PROTOCOL_VERSION}")
    print("=" * 96)

    t0 = time.perf_counter()
    c = RawStdioClient([sys.executable, str(SERVER)])
    spawn = time.perf_counter() - t0

    try:
        # ① 握手：协商协议版本与双方能力
        init = c.request("initialize", {
            "protocolVersion": LATEST_PROTOCOL_VERSION,
            "capabilities": {},                       # 我们什么额外能力都不声明
            "clientInfo": {"name": "hand-written-probe", "version": "0.0.1"},
        })

        # ② 握手第二步：这是【通知】不是请求 —— 没有 id，服务端不回
        c.notify("notifications/initialized")

        # ③ 要工具清单
        tools = c.request("tools/list")

        # ④ 调一个只读工具
        c.request("tools/call", {"name": "kubectl_get_pods",
                                 "arguments": {"namespace": "payment"}})

        # ⑤ 调一个不存在的工具，看错误怎么回
        c.request("tools/call", {"name": "rm_minus_rf", "arguments": {}})

        # ⑥ 参数不对，看校验发生在哪一层
        c.request("tools/call", {"name": "kubectl_get_pods", "arguments": {"wrong_arg": 1}})

        # ── 汇总 ──────────────────────────────────────────────────────────
        r = init["result"]
        tl = tools["result"]["tools"]
        print("\n" + "=" * 96)
        print("汇总")
        print("=" * 96)
        print(f"协商结果      : 服务端协议版本 {r['protocolVersion']}"
              f"（客户端提的是 {LATEST_PROTOCOL_VERSION}）")
        print(f"服务端身份    : {r['serverInfo']}")
        print(f"服务端能力    : {json.dumps(r.get('capabilities'), ensure_ascii=False)}")
        print(f"instructions  : {len(r.get('instructions') or '')} 字符"
              f"  ← 会被客户端塞进 system prompt")
        print(f"\n工具数        : {len(tl)}")
        print(f"{'工具名':<28}{'read_only':<11}{'destructive':<13}{'idempotent':<12}")
        for t in tl:
            a = t.get("annotations") or {}
            print(f"{t['name']:<28}{str(a.get('readOnlyHint')):<11}"
                  f"{str(a.get('destructiveHint')):<13}{str(a.get('idempotentHint')):<12}")

        schema_bytes = len(json.dumps(tl, ensure_ascii=False).encode())
        print(f"\n【成本】")
        print(f"  进程启动        : {spawn*1000:.0f}ms（每个 MCP Server 一个独立进程）")
        print(f"  tools/list 体积 : {schema_bytes} 字节 ≈ {schema_bytes//4} tokens"
              f"（粗估）—— 每次对话都要进 system prompt")
        print(f"  本次会话收发    : 发 {c.bytes_sent} 字节 / 收 {c.bytes_recv} 字节")
    finally:
        c.close()


if __name__ == "__main__":
    main()
