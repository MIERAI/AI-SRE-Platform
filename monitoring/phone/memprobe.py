#!/data/data/com.termux/files/usr/bin/python
"""内存压力探针 —— 测出 Android 在多少内存压力下杀掉 Termux。

    python ~/memprobe.py                    # 512 MB 一步，最多 14 GB
    python ~/memprobe.py --step 256 --max 8000
    python ~/memprobe.py --mmap /path/model.gguf   # 用文件映射代替匿名内存

### 为什么用分配器而不是直接跑模型

跑模型只能得到一个二元结果（死了/没死），而且要先准备一个几 GB 的模型文件。
分配器给出的是**阈值**：到第几 GB 被杀。阈值可以反复测、能画曲线、
换参数就能重跑。

### 匿名内存 vs 文件映射：两者压力完全不同

    bytearray(n)        匿名页 —— 内核回收它必须写 swap，或者杀进程
    mmap(file)          文件背景的干净页 —— 直接丢弃即可，需要时从磁盘重读

llama.cpp 默认用 mmap 加载模型，所以它的压力比同等大小的匿名分配【温和得多】。

因此：
  · 匿名模式测出的阈值是**保守下界** —— 扛住 N GB 匿名分配，
    几乎肯定能扛住 N GB 的 mmap 加载
  · 反过来不成立 —— 匿名在 6 GB 被杀，不代表 9 GB 的模型也会被杀

⚑ 每一步都立刻写盘并 flush。这个进程随时会被 SIGKILL，
  而缓冲区里的最后几行恰恰是最关键的 —— 今天已经在另一个实验上栽过一次。
"""

from __future__ import annotations

import argparse
import mmap as mmod
import os
import sys
import time


def meminfo() -> dict:
    d = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                k, _, v = line.partition(":")
                d[k] = int(v.split()[0]) // 1024        # MB
    except OSError:
        pass
    return d


def own(pid: int) -> tuple[int, int]:
    rss = oom = 0
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    rss = int(line.split()[1]) // 1024
    except OSError:
        pass
    try:
        oom = int(open(f"/proc/{pid}/oom_score").read().strip())
    except OSError:
        pass
    return rss, oom


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", type=int, default=512, help="每步 MB")
    ap.add_argument("--max", type=int, default=14000, help="最多分配 MB")
    ap.add_argument("--hold", type=float, default=2.0, help="每步后停顿秒数，给内核反应时间")
    ap.add_argument("--log", default=os.path.expanduser("~/memprobe.log"))
    ap.add_argument("--mmap", default=None, help="改用文件映射（模拟 llama.cpp 的加载方式）")
    a = ap.parse_args()

    pid = os.getpid()
    mode = "mmap" if a.mmap else "anon"
    # ⚑ 每次 open/append/close，不保持句柄 —— 被 SIGKILL 时不会丢缓冲。
    def log(msg: str) -> None:
        with open(a.log, "a") as f:
            f.write(msg + "\n")
            f.flush()
            os.fsync(f.fileno())

    log(f"# {time.strftime('%F %T')} mode={mode} step={a.step}MB max={a.max}MB pid={pid}")
    log("alloc_mb memfree_mb memavail_mb swapfree_mb cached_mb rss_mb oom_score")

    held: list = []
    total = 0
    fd = None
    if a.mmap:
        fd = os.open(a.mmap, os.O_RDONLY)
        size = os.fstat(fd).st_size
        print(f"  文件映射模式：{a.mmap}  {size/2**30:.2f} GB")

    try:
        while total < a.max:
            if a.mmap:
                # ⚑ 只 mmap 不读的话页不会真正驻留，压力测不出来。
                #   必须逐页 touch —— 这里按 step 大小分段读，模拟权重被访问。
                off = (total * 1024 * 1024) % max(os.fstat(fd).st_size - 1, 1)
                length = min(a.step * 1024 * 1024, os.fstat(fd).st_size - off)
                if length <= 0:
                    break
                m = mmod.mmap(fd, length, offset=(off // mmod.PAGESIZE) * mmod.PAGESIZE,
                              access=mmod.ACCESS_READ)
                s = 0
                for i in range(0, len(m), 4096):
                    s += m[i]
                held.append(m)
            else:
                # bytearray 会零填充 → 页真正被提交，不是只预留地址空间
                held.append(bytearray(a.step * 1024 * 1024))
            total += a.step

            mi = meminfo()
            rss, oom = own(pid)
            log(f"{total} {mi.get('MemFree',0)} {mi.get('MemAvailable',0)} "
                f"{mi.get('SwapFree',0)} {mi.get('Cached',0)} {rss} {oom}")
            print(f"  已分配 {total/1024:5.1f} GB   MemFree {mi.get('MemFree',0):5d} MB   "
                  f"SwapFree {mi.get('SwapFree',0):5d} MB   RSS {rss:5d} MB   oom {oom}")
            sys.stdout.flush()
            time.sleep(a.hold)
    except MemoryError:
        # ⚑ 走到这里说明【进程自己先撑不住】，而不是被系统杀 ——
        #   这是两种完全不同的结局，日志里必须能分清。
        log(f"# MemoryError at {total}MB —— 分配失败，进程未被杀")
        print(f"  ✗ MemoryError at {total} MB（分配失败，不是被杀）")
    except KeyboardInterrupt:
        log(f"# interrupted at {total}MB")
    log(f"# reached {total}MB and exited normally")
    print(f"  到 {total} MB 正常结束（未被杀）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
