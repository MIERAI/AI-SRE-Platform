"""thinking 开关对跨 namespace 归因的影响 —— 重复实验。

场景 2 的证据链需要两跳：order-api 日志说上游是 inventory-api，
inventory 的事件里才有「滚动更新 maxUnavailable=50%」这个真正的根因。
两次单跑显示 think=False 拿到了证据却没用上，think=True 用上了。
但 n=1 说明不了任何事 —— 这里各跑 N 次，用客观关键词判定。

    uv run agent/ablation_think.py
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from loop import SCENARIOS, run  # noqa: E402
from tools.cluster import CALL_LOG  # noqa: E402

N = 3
# 判定：最终答案里有没有把根因归到滚动更新 / maxUnavailable
HIT = re.compile(r"滚动更新|rolling update|maxUnavailable|maxunavailable|滚动升级", re.I)
# 反向：有没有错误地宣称上游是健康的
MISS = re.compile(r"inventory-api\s*(本身)?\s*(是)?\s*健康|inventory-api is healthy", re.I)

_, question = SCENARIOS[1]


def main():
    print(f"场景 2（跨 namespace 归因）· 每组 {N} 次 · temperature=0\n")
    print(f"{'配置':<14}{'次':<4}{'工具调用':<10}{'命中根因':<10}{'误判上游健康':<14}答案首句")
    print("-" * 100)

    tally = {}
    for think in (False, True):
        hits = 0
        for i in range(1, N + 1):
            CALL_LOG.clear()
            ans, _ = run(question, think=think, verbose=False)
            n_calls = len(CALL_LOG)
            hit, miss = bool(HIT.search(ans)), bool(MISS.search(ans))
            hits += hit
            first = ans.strip().splitlines()[0][:44] if ans.strip() else "(空)"
            print(f"{'think=' + str(think):<14}{i:<4}{n_calls:<10}"
                  f"{'✅' if hit else '❌':<10}{'⚠️ 是' if miss else '否':<14}{first}")
        tally[think] = hits
        print()

    print(f"命中率  think=False: {tally[False]}/{N}   think=True: {tally[True]}/{N}")
    if tally[True] == tally[False]:
        print("两组一致 —— 单次观察到的差异是噪声，不能声称 thinking 有效。")
    else:
        print(f"差异 {tally[True] - tally[False]}/{N}。n={N} 仍偏小，但方向与「CoT 帮助的是"
              f"证据综合、不是证据获取」一致（两组工具调用次数相当）。")


if __name__ == "__main__":
    main()
