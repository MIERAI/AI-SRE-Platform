#!/data/data/com.termux/files/usr/bin/bash
# 数据目录统计。由 watchdog 每 15 分钟调用，结果缓存给 exporter 读。
#
# ⚑ 为什么要缓存，不在 exporter 里现算：
#   实测 du + find 扫一遍 ~/nas 要 0.5 秒。exporter 每 15 秒被抓一次，
#   现算会让每次抓取都背上这个开销，而目录体积【本来就不需要 15 秒精度】。
#
# ⚑ 为什么同时记文件数和体积：
#   体积能看出"谁在涨"，文件数能看出"有没有静默丢失"。
#   照片从 18,421 掉到 17,900 —— 体积变化可能只有百分之几，看不出来；
#   文件数是直接的、离散的、一眼能发现的。误删和同步 bug 都是这样暴露的。

set -u
OUT="$HOME/datastats.json"
NAS="$HOME/nas"
DIRS="photos movies documents downloads media models share backup inbox"

python - "$NAS" "$OUT" $DIRS <<'PYEOF'
import json, os, sys, time

nas, out = sys.argv[1], sys.argv[2]
dirs = sys.argv[3:]
res = {"dirs": {}, "computed": int(time.time())}

for d in dirs:
    p = os.path.join(nas, d)
    if not os.path.isdir(p):
        continue
    n = 0
    size = 0
    for root, _sub, files in os.walk(p):
        # ⚑ 缩略图单独统计，不混进照片数 —— 否则「照片 136 张」会变成 272 张，
        #   而且缩略图丢失和原图丢失是两件严重程度完全不同的事。
        if ".thumbs" in root:
            continue
        for f in files:
            if f.startswith("."):
                continue
            try:
                size += os.path.getsize(os.path.join(root, f))
                n += 1
            except OSError:
                pass
    res["dirs"][d] = {"files": n, "bytes": size}

# 缩略图：数量应与照片数一致，差值本身就是信号
th = os.path.join(nas, "photos", ".thumbs")
tn = 0
for root, _sub, files in os.walk(th):
    tn += len([f for f in files if not f.startswith(".")])
res["thumbnails"] = tn

with open(out, "w") as f:
    json.dump(res, f)

if "-v" in os.environ.get("DG_ARGS", ""):
    pass
print("  " + "  ".join(f"{k}={v['files']}个/{v['bytes']/1048576:.0f}MB"
                       for k, v in res["dirs"].items() if v["files"]))
print(f"  缩略图 {tn} 张")
PYEOF
