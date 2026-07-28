# Phase 1 · 设计追问的答案

> 记录格式：结论 + **实验证据**。假设未被证实的明确标注。
> 环境：无 API key，全程本地 Ollama（`qwen3:14b` / `deepseek-r1:14b`），M4 Pro 24GB。

---

## Function Calling 在 API 层到底传了什么 ✅

### 结论：它就是 prompt 工程 + 输出端字符串解析。没有协议层魔法。

证据一 —— **读 `qwen3:14b` 的 chat template**（`ollama show qwen3:14b --template`）：

```gotemplate
{{- if .Tools }}
# Tools
You may call one or more functions to assist with the user query.
You are provided with function signatures within <tools></tools> XML tags:
<tools>
{{- range .Tools }}
{"type": "function", "function": {{ .Function }}}
{{- end }}
</tools>
For each function call, return a json object with function name and arguments
within <tool_call></tool_call> XML tags:
<tool_call>
{"name": <function-name>, "arguments": <args-json-object>}
</tool_call>
{{- end -}}
```

`tools` 数组被 Go 模板序列化成**纯文本**，塞进 System Prompt。

证据二 —— **手写同样的 system prompt，绕过 `tools` 参数**（`agent/parser/probe_function_calling.py`）：

```
A 组（正规传 tools）
  content    : ''
  tool_calls : [{"name":"kubectl_get_pods","arguments":{"namespace":"payment"}}]

B 组（不传 tools，手写 system prompt）
  content    : '<tool_call>\n{"name": "kubectl_get_pods", "arguments": {"namespace": "payment"}}\n</tool_call>'
  tool_calls : null
```

**语义完全相同。** A 组那个结构化字段就是 Ollama 拿 B 组这种原始文本做字符串解析得来的。

### 三个直接影响写 Agent 方式的推论

1. **工具定义占 System Prompt 的 token，每次请求都带。** 工具越多，prompt 越长，注意力越分散。这是 Agent 工具数量的真实约束，不是"想加多少加多少"。
2. **`tool_calls` 是解析产物，解析会失败。** 模型可能生成畸形的 `<tool_call>`，或在标签外加解释文字。
3. **`tool` 角色被渲染成 `user` 消息**（模板末尾：`{{- else if eq .Role "tool" }}<|im_start|>user\n<tool_response>`）。模型看到的不是"工具返回了"，而是"用户又说了一句话"。**这是提示词注入的攻击面** —— 工具返回的不可信内容和用户指令在同一个信任级别。测试用例 `a15` 专打这一点。

---

## "支持 Function Calling" 是模型能力还是模板能力 ✅

`deepseek-r1:14b` 的 template 里 **0 处**提及 tool。传 `tools` 参数，Ollama 在 API 层直接拒绝：

```json
{"error": "registry.ollama.ai/library/deepseek-r1:14b does not support tools"}
```

手写 system prompt 绕过后，它**语义正确、格式错误**：

```
期望: <tool_call>{"name":...,"arguments":...}</tool_call>
实际: ```json\n{"name": "kubectl_get_pods", "arguments": {"namespace": "payment"}}\n```
```

**所以是两件事的组合：**
- **模板**提供槽位（把 JSON 渲染成 token）
- **训练**让模型输出解析器认识的确切语法

能力在（它知道调哪个工具、参数填什么），格式不在（没被训练过 `<tool_call>`，自己发明了一个）。
Ollama 的拒绝不是无理设卡，是在拦住解析不了的输出。

---

## Structured Output 的两条技术路线 ✅

| | 路线一：Prompt 约束 | 路线二：约束解码 |
|---|---|---|
| 机制 | 在 System Prompt 里要求输出 JSON | 在 softmax 前把非法 token 压成 `-inf` |
| 保证 | 概率性 | **确定性——数学上不可能违规** |
| 实现 | 写文字 | llama.cpp GBNF / Outlines / Ollama 的 `format` 参数 |

### 路线二的机制：自己实现一遍（`labs/00-nano-gpt/constrained.py`）

用 Phase 0 训的**莎士比亚字符模型**，强制它输出 `severity: {critical|warning|info}`：

```
 步    合法 token 数    模型给合法集的概率    选中
  1             1          0.297168%     's'
 ...
 11             3         15.844916%     'w'      <- 全程唯一有选择权的一步
 ...
 18             1          0.359839%    '\n'

输出       : 'severity: warning\n'
格式合法   : True
模型自发产出这个字符串的概率 : 7.4e-19
```

**18 步里 17 步的合法 token 数是 1** —— 模型根本没得选，采样器直接把答案喂给它。
一个对告警严重度一无所知的模型，输出了 100% 合法的结构。**保证来自采样器，不来自模型。**

### 副产品：一个能上生产的监控指标

"模型给合法集的概率质量"这一列。如果在真实模型上这个数长期很低，说明模型不理解任务
—— **输出合法，内容不可信**。这是约束解码最危险的地方：它能完美掩盖模型的无能。

### 还有一层代价

强制某个 token 会改变它之后所有 token 的条件分布。模型被推上一条它本不想走的路径，
后续输出是以这条错误路径为条件生成的。**过强的格式约束会让模型变笨。**

---

## ⚠️ 实测发现：约束解码修结构，但内容质量取决于模型（机制未明）

严格对照，唯一变量是 `format` 参数（= 约束解码）开关，`temperature=0`：

| 模型 | format=False | format=True |
|---|---|---|
| deepseek-r1:14b | schema 完全不对（编了 `{"pods":{"data":[...]}}`） | schema 正确，`namespace`=`gppayment` ❌ |
| qwen3:14b | 内容对但 schema 不对（扁平、键名 `action`） | 完全正确 ✅ |

`deepseek-r1:14b` 在同一问题上给出过 **5 个不同的错误值**：
`ingpayout` / `gingpayment` / `gppayment` / `ingestion` / `batch`（正确答案是 `payment`）。
qwen3 在 4 次固定种子重复下 4/4 正确。

### 两个机制假设，都被自己的实验否证

| 假设 | 检验方式 | 结果 |
|---|---|---|
| 推理模型关掉 thinking → off-distribution | 开 `think:true` 重测（591 字符思考） | ❌ 照样错（`gingpayment`） |
| token 边界对齐 / token healing（垃圾全在字符串开头） | `namespace` 改成 enum 锁定整个值 | ❌ 照样错（选了 `batch`） |

**机制未解决。** 往下查需要 token 级 logprobs，Ollama 不暴露，得换 llama.cpp 带 `--logits-all`。
挂在这里，别编解释。

### 不依赖机制也成立的三条

1. **约束解码保证形式，不保证内容。** 今天被三种方式独立证实：莎士比亚模型的 7.4e-19、
   deepseek 的合法垃圾、enum 下的错误选项。
2. **模型 × 约束方式 的组合必须在自己的测试集上验证。** 同 schema 同 prompt，qwen3 全对
   deepseek 全错。换模型不是无痛的。
3. **`json.loads()` 成功 + schema 校验通过 = 什么都没保证。** 这是 Phase 4 Evaluation
   存在的全部理由 —— 靠眼看永远发现不了这类问题。

---

## 尚未回答

- temperature / top-p 具体如何影响 JSON 稳定性（接 Phase 0 自己写的 `_sample()` 解释）
- 为什么模型爱输出 ` ```json ` 包裹？和训练数据分布的关系
- CoT 为什么有效 —— 真推理还是给了更多计算步（读质疑论文，别只信厂商说法）
- 20 条测试告警的实际抽取跑分（`agent/parser/testdata/alerts.jsonl` 已就绪，含 8 条难例）
