#!/data/data/com.termux/files/usr/bin/python
"""照片归档：~/nas/inbox → ~/nas/photos/YYYY/MM/，并生成缩略图。

    inbox/IMG_20260818_121314.jpg
      ↓
    photos/2026/08/IMG_20260818_121314.jpg
    photos/.thumbs/2026/08/IMG_20260818_121314.jpg   （最长边 400px）

### 日期从哪来，以及为什么是这个顺序

    ① EXIF DateTimeOriginal   相机写的拍摄时间，唯一真正可靠的来源
    ② 文件名里的日期           IMG_20260818_… / PXL_… / Screenshot_2026-08-18…
    ③ exiftool                 兜底给 HEIC/RAW —— Pillow 读不了它们
    ④ 文件 mtime               最后手段

⚑ mtime 排在最后是有原因的：**传输会改写它**。rsync 不带 -t、或经过某些
  云盘中转后，mtime 会变成「传过来的时间」而不是「拍摄的时间」。
  用它排序的结果是所有照片都堆在同一个月份里 —— 而且这个错误很隐蔽，
  因为目录结构看上去完全正常。

⚑ 文件名排在 exiftool 前面，是因为 exiftool 是 Perl 写的，每次启动约 200ms。
  几千张照片就是十几分钟。文件名匹配是纯字符串操作，几乎免费，
  而现代手机的相机命名里基本都带日期。

### 同名怎么办

不是简单加后缀。先比哈希：

    同名 + 内容相同  →  这是重复导入，删掉源文件（不产生副本）
    同名 + 内容不同  →  加 -1 -2 后缀

⚑ 少了前一条，每跑一次 rsync 就会多出一批 IMG_xxx-1.jpg、IMG_xxx-2.jpg。
  照片归档最常见的失败不是丢文件，是**同一张照片存了五份**。

    python ~/archive_photos.py            # 正常归档
    python ~/archive_photos.py --dry-run  # 只看会怎么动，不实际移动
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime

HOME = os.path.expanduser("~")
INBOX = os.path.join(HOME, "nas", "inbox")
PHOTOS = os.path.join(HOME, "nas", "photos")
STATS = os.path.join(HOME, "photo_archive_stats.json")

# ⚑ 缩略图目录【必须由 --dest 推导】，不能写成模块级常量。
#   第一版就是常量，结果拿 --dest ~/nastest 做测试时，缩略图全写进了
#   真实的 ~/nas/photos/.thumbs —— 而统计计数器显示「缩略图 5」，完全正常。
#   发现它只是因为去数了目标目录里的实际文件数（0）。
#   教训与 cpu 标签那个 bug 同源：**计数器对，不代表事情做对了。**

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".dng", ".webp", ".gif"}
VIDEO_EXT = {".mp4", ".mov", ".3gp", ".mkv", ".avi"}
MEDIA_EXT = IMAGE_EXT | VIDEO_EXT
THUMB_MAX = 400

# 文件名里的日期：IMG_20260818_… / PXL_20260818… / Screenshot_2026-08-18…
NAME_DATE = re.compile(r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})")


def plausible(dt: datetime) -> bool:
    """2000 年之前、或明天之后的日期一律不信。

    ⚑ 没有这道检查的话，EXIF 里的 0000:00:00 会被解析成 1 年，
      于是生成 photos/0001/01/ —— 目录结构照样「正常」，只是错了 2000 年。
    """
    return datetime(2000, 1, 1) <= dt <= datetime.now().replace(hour=23, minute=59)


def date_from_exif(path: str) -> datetime | None:
    try:
        from PIL import Image
        with Image.open(path) as im:
            ex = im.getexif()
            if not ex:
                return None
            # 36867 = DateTimeOriginal, 306 = DateTime
            for tag in (36867, 306):
                v = ex.get(tag)
                if v:
                    dt = datetime.strptime(str(v)[:19], "%Y:%m:%d %H:%M:%S")
                    if plausible(dt):
                        return dt
    except Exception:                                   # noqa: BLE001
        pass
    return None


def date_from_name(path: str) -> datetime | None:
    m = NAME_DATE.search(os.path.basename(path))
    if not m:
        return None
    try:
        dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return dt if plausible(dt) else None
    except ValueError:
        return None


def date_from_exiftool(path: str) -> datetime | None:
    """给 HEIC / RAW / 视频兜底。慢（Perl 启动约 200ms），所以放在最后。"""
    try:
        r = subprocess.run(
            ["exiftool", "-s3", "-DateTimeOriginal", "-CreateDate", path],
            capture_output=True, text=True, timeout=25)
        for line in r.stdout.splitlines():
            line = line.strip()
            if len(line) >= 19:
                try:
                    dt = datetime.strptime(line[:19], "%Y:%m:%d %H:%M:%S")
                    if plausible(dt):
                        return dt
                except ValueError:
                    continue
    except Exception:                                   # noqa: BLE001
        pass
    return None


def shot_date(path: str) -> tuple[datetime, str]:
    ext = os.path.splitext(path)[1].lower()
    if ext in {".jpg", ".jpeg", ".png", ".webp"}:
        d = date_from_exif(path)
        if d:
            return d, "exif"
    d = date_from_name(path)
    if d:
        return d, "name"
    d = date_from_exiftool(path)
    if d:
        return d, "exiftool"
    return datetime.fromtimestamp(os.path.getmtime(path)), "mtime"


def truncated(path: str) -> bool:
    """图片文件是否被截断。

    ⚑ 这是第二道防线。传输中断会留下【非零字节但不完整】的文件，
      它长得像正常照片，会被归档进相册，直到某天你点开发现打不开。
      实测发生过一次：4.3 MB 的照片只到了 2.4 MB。

    ⚑ 两段式：尾部魔数只用来【筛出可疑的】，判定损坏必须靠完整解码。
      只做尾部检查会误杀 —— 实测 136 张里误报 11 张：

          MVIMG_20260816_094022.jpg          Motion Photo，JPEG 之后追加了 MP4
          IMG_20260815_204802_…edit.jpg      编辑过的图，尾部有附加数据

      这类文件本来就不以 FFD9 结尾。全量 PIL 解码给出的真实答案是【只坏 1 张】。
      所以快检负责让绝大多数文件走 O(1) 路径，可疑的那少数再花时间真解码。
    """
    ext = os.path.splitext(path)[1].lower()
    if ext not in {".jpg", ".jpeg", ".png"}:
        return False                                      # 其余格式不判断
    try:
        with open(path, "rb") as f:
            if ext == ".png":
                f.seek(-8, os.SEEK_END)
                suspicious = f.read(8) != b"IEND\xaeB`\x82"
            else:
                f.seek(-2, os.SEEK_END)
                suspicious = f.read(2) != b"\xff\xd9"
    except OSError:
        return True
    if not suspicious:
        return False
    # 尾部不对 —— 可能是 Motion Photo/编辑数据，也可能真被截断。解码确认。
    try:
        from PIL import Image
        with Image.open(path) as im:
            im.load()
        return False
    except Exception:                                     # noqa: BLE001
        return True


def sha256(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def make_thumb(src: str, dst: str) -> bool:
    try:
        from PIL import Image
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with Image.open(src) as im:
            im.draft("RGB", (THUMB_MAX * 2, THUMB_MAX * 2))   # JPEG 快速降采样
            im = im.convert("RGB")
            im.thumbnail((THUMB_MAX, THUMB_MAX))
            tmp = dst + ".tmp"
            im.save(tmp, "JPEG", quality=80)
            os.replace(tmp, dst)
        return True
    except Exception:                                   # noqa: BLE001
        # HEIC / RAW / 视频会走到这里 —— 预期内，不算错误
        return False


def unique_target(dest: str, src: str) -> tuple[str | None, bool]:
    """返回 (目标路径, 是否为重复文件)。重复时目标为 None。"""
    if not os.path.exists(dest):
        return dest, False
    # ⚑ 先比哈希再决定加后缀，否则每次重跑都会堆出 -1 -2 -3 的副本
    if os.path.getsize(dest) == os.path.getsize(src) and sha256(dest) == sha256(src):
        return None, True
    stem, ext = os.path.splitext(dest)
    for i in range(1, 1000):
        cand = f"{stem}-{i}{ext}"
        if not os.path.exists(cand):
            return cand, False
        if os.path.getsize(cand) == os.path.getsize(src) and sha256(cand) == sha256(src):
            return None, True
    return None, False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inbox", default=INBOX)
    ap.add_argument("--dest", default=PHOTOS)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--backfill-thumbs", action="store_true",
                    help="只补缺失的缩略图，不做归档")
    a = ap.parse_args()

    os.makedirs(a.inbox, exist_ok=True)
    os.makedirs(a.dest, exist_ok=True)
    thumbs_root = os.path.join(a.dest, ".thumbs")

    if a.backfill_thumbs:
        # ⚑ 缩略图原本只在归档那一刻生成。经 File Browser 直接上传的照片、
        #   或人工放进去的文件都不会有缩略图 —— 而且这件事没有任何提示。
        thumbs_root = os.path.join(a.dest, ".thumbs")
        made = skipped = 0
        for root, _d, files in os.walk(a.dest):
            if ".thumbs" in root:
                continue
            for name in files:
                if name.startswith("."):
                    continue
                rel = os.path.relpath(os.path.join(root, name), a.dest)
                t = os.path.join(thumbs_root, rel)
                if os.path.exists(t):
                    continue
                if make_thumb(os.path.join(root, name), t):
                    made += 1
                    print(f"  ✓ {rel}")
                else:
                    skipped += 1          # HEIC / 视频，预期内
        print(f"\n补生成 {made} 张，跳过 {skipped} 张（HEIC/视频无法生成）")
        return 0

    st = {"scanned": 0, "archived": 0, "duplicate": 0, "thumbs": 0,
          "errors": 0, "skipped": 0, "truncated": 0, "by_source": {}}
    quarantine = os.path.join(os.path.dirname(a.dest), "quarantine")
    t0 = time.time()

    for root, _dirs, files in os.walk(a.inbox):
        for name in sorted(files):
            src = os.path.join(root, name)
            if name.startswith("."):
                continue
            if os.path.splitext(name)[1].lower() not in MEDIA_EXT:
                st["skipped"] += 1
                continue
            # ⚑ 跳过还在传输中的文件：rsync 的临时文件以 . 开头（上面已滤），
            #   但有些客户端用 .part / .filepart。大小为 0 的也跳过。
            if name.endswith((".part", ".filepart", ".tmp")) or os.path.getsize(src) == 0:
                st["skipped"] += 1
                continue
            st["scanned"] += 1
            # ⚑ 截断的文件【不进相册】，隔离到 quarantine/ 等人工判断。
            #   直接删掉不行：万一判断有误就是照片丢失，而源端相册里可能已经没有了。
            if truncated(src):
                st["truncated"] += 1
                if not a.dry_run:
                    os.makedirs(quarantine, exist_ok=True)
                    shutil.move(src, os.path.join(quarantine, name))
                print(f"  ⚠ 截断，已隔离  {name}", file=sys.stderr)
                continue
            try:
                dt, source = shot_date(src)
                st["by_source"][source] = st["by_source"].get(source, 0) + 1
                sub = os.path.join(f"{dt.year:04d}", f"{dt.month:02d}")
                dest_dir = os.path.join(a.dest, sub)
                dest = os.path.join(dest_dir, name)

                target, dup = unique_target(dest, src)
                if dup:
                    st["duplicate"] += 1
                    if not a.dry_run:
                        os.remove(src)          # 内容一致，源可安全删除
                    if not a.quiet:
                        print(f"  重复  {name}  →  已在 {sub}/")
                    continue
                if target is None:
                    st["errors"] += 1
                    continue

                if a.dry_run:
                    print(f"  [dry] {name}  →  {sub}/  （日期来自 {source}）")
                    continue

                os.makedirs(dest_dir, exist_ok=True)
                shutil.move(src, target)
                st["archived"] += 1

                thumb = os.path.join(thumbs_root, sub, os.path.basename(target))
                if make_thumb(target, thumb):
                    st["thumbs"] += 1
                if not a.quiet:
                    print(f"  ✓ {os.path.basename(target)}  →  {sub}/  ({source})")
            except Exception as e:                      # noqa: BLE001
                st["errors"] += 1
                print(f"  ✗ {name}: {type(e).__name__}: {str(e)[:60]}", file=sys.stderr)

    st["seconds"] = round(time.time() - t0, 1)
    st["last_run"] = int(time.time())
    st["total_photos"] = sum(
        len([f for f in fs if not f.startswith(".")])
        for r, _d, fs in os.walk(a.dest) if ".thumbs" not in r)

    if not a.dry_run:
        # ⚑ 落一份统计给 exporter 读 —— 归档是否还在正常工作必须可观测，
        #   否则它悄悄停掉，人两个月后才发现照片全堆在 inbox 里。
        with open(STATS, "w") as f:
            json.dump(st, f)

    print(f"\n扫描 {st['scanned']} · 归档 {st['archived']} · 重复 {st['duplicate']} "
          f"· 缩略图 {st['thumbs']} · 截断隔离 {st['truncated']} "
          f"· 错误 {st['errors']} · {st['seconds']}s")
    if st["by_source"]:
        print("日期来源：" + "  ".join(f"{k}={v}" for k, v in st["by_source"].items()))
    return 1 if st["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
