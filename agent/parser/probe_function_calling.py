"""Function Calling 到底是什么？—— 两组对照。

A 组：正规传 tools 参数，看 Ollama 返回结构化的 tool_calls
B 组：不传 tools，我们自己把 qwen3 模板里那段文本手写进 system prompt

如果 B 组能拿到同样的 <tool_call> 文本，就证明 Function Calling 没有协议层魔法：
它 = 特定格式的 prompt + 输出端的字符串解析。

    uv run agent/parser/probe_function_calling.py
"""

import json
import urllib.request

OLLAMA = "http://localhost:11434/api/chat"
MODEL = "qwen3:14b"

TOOL = {
    "type": "function",
    "function": {
        "name": "kubectl_get_pods",
        "description": "列出指定 namespace 下的所有 Pod 及其状态",
        "parameters": {
            "type": "object",
            "properties": {"namespace": {"type": "string", "description": "K8s namespace"}},
            "required": ["namespace"],
        },
    },
}

QUESTION = "payment 这个 namespace 里的 pod 现在什么状态？"


def chat(payload):
    req = urllib.request.Request(
        OLLAMA, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)


def main():
    base = {"model": MODEL, "stream": False, "think": False,
            "options": {"temperature": 0, "num_predict": 300}}

    print("=" * 74)
    print("A 组：正规传 tools 参数")
    print("=" * 74)
    a = chat({**base, "messages": [{"role": "user", "content": QUESTION}], "tools": [TOOL]})
    ma = a["message"]
    print(f"content    : {ma.get('content')!r}")
    print(f"tool_calls : {json.dumps(ma.get('tool_calls'), ensure_ascii=False)}")

    # 手抄 qwen3 模板里 .Tools 那一段。注意这里没传 tools 参数。
    manual_system = (
        "# Tools\n\n"
        "You may call one or more functions to assist with the user query.\n\n"
        "You are provided with function signatures within <tools></tools> XML tags:\n"
        "<tools>\n"
        + json.dumps(TOOL, ensure_ascii=False)
        + "\n</tools>\n\n"
        "For each function call, return a json object with function name and arguments "
        "within <tool_call></tool_call> XML tags:\n"
        "<tool_call>\n"
        '{"name": <function-name>, "arguments": <args-json-object>}\n'
        "</tool_call>"
    )

    print()
    print("=" * 74)
    print("B 组：不传 tools，手写同样的 system prompt")
    print("=" * 74)
    b = chat({**base, "messages": [
        {"role": "system", "content": manual_system},
        {"role": "user", "content": QUESTION},
    ]})
    mb = b["message"]
    print(f"content    : {mb.get('content')!r}")
    print(f"tool_calls : {json.dumps(mb.get('tool_calls'), ensure_ascii=False)}")

    print()
    print("=" * 74)
    print("结论")
    print("=" * 74)
    print("A 组的 tool_calls 是 Ollama 解析 B 组那种原始文本得来的。")
    print("模型两次都只是在生成文本 —— 区别只在于谁负责解析。")


if __name__ == "__main__":
    main()
