#!/data/data/com.termux/files/usr/bin/bash
# 手机2 → 手机1 的照片推送。只增不删，源端（你的相册）永不改动。
#
#     ~/storage/dcim/{Camera,Screenshots}  →  手机1:~/nas/inbox/<子目录>/
#     然后由手机1 的 archive_photos.py 按拍摄日期整理进 photos/YYYY/MM/
#
# ⚑ 为什么是 tar over ssh 而不是 rsync —— 实测踩出来的，不是偏好：
#     rsync -a ... host:任意目录/
#     → rsync: [Receiver] change_dir#1 "…/rsynctest/" failed: Permission denied (13)
#   同一条 SSH、同一个账号、同一个目录，`cd` 和 `scp` 都正常，只有 rsync 的
#   接收端 chdir() 拿 EACCES。换目录、去掉 --files-from、指定
#   --rsync-path=$PREFIX/bin/rsync 都无效。所以放弃 rsync。
#   tar over ssh 实测可用，而且对「大量小文件」只用一条连接，比 scp 逐个开连接快。
#   代价：没有断点续传、没有增量差分。对照片来说后者本就无意义（文件只新增不修改），
#   前者用分批来补 —— 见下面的 BATCH。
#
# ⚑ 增量用「已发送清单」而不是时间戳。
#   时间戳方案（find -newer）对时钟回拨、以及「旧照片后来才出现在相册里」
#   这两种情况都会漏传。清单是按文件名判断，跑多少次都不会漏也不会重。
#
# ⚑ 必须显式列出 Camera / Screenshots 这些真实子目录。
#   ~/storage/dcim 是【符号链接】，find 默认不跟随，
#   直接 find ~/storage/dcim 会返回 0 个文件 —— 脚本「成功」执行、传了个寂寞。
#
#     ~/photopush.sh              # 推送未发送过的
#     ~/photopush.sh --all        # 忽略清单重发全部（接收端按哈希去重，安全）
#     ~/photopush.sh --wifi-only  # 只在连着 WiFi 时推

set -u

DEST_HOST=100.80.225.15
DEST_PORT=8022
DEST_USER=u0_a506
KEY="$HOME/.ssh/id_ed25519"
SENT="$HOME/.photopush_sent"
LOG="$HOME/photopush.log"
SRC_DIRS="$HOME/storage/dcim/Camera $HOME/storage/dcim/Screenshots"
BATCH=20          # 每批文件数。批越小，中断后重传的浪费越少

MODE_ALL=0
WIFI_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --all) MODE_ALL=1 ;;
    --wifi-only) WIFI_ONLY=1 ;;
  esac
done

SSH_OPTS="-p $DEST_PORT -i $KEY -o StrictHostKeyChecking=accept-new -o ConnectTimeout=25 -o ServerAliveInterval=20"
log() { echo "$(date '+%F %T') $*" >> "$LOG"; }

if [ "$WIFI_ONLY" = "1" ]; then
  state=$(timeout 12 termux-wifi-connectioninfo 2>/dev/null \
          | grep -o '"supplicant_state"[^,]*' | grep -o '[A-Z]\{4,\}')
  if [ "$state" != "COMPLETED" ]; then
    log "跳过：不在 WiFi 上（$state）"
    exit 0
  fi
fi

touch "$SENT"
total=0
failed=0

for d in $SRC_DIRS; do
  [ -d "$d" ] || continue
  sub=$(basename "$d")
  cd "$d" || continue

  list="$HOME/.photopush.list.$$"
  # ⚑ 按行处理而不是 NUL：相机生成的文件名不含换行，换来的是可以用
  #   split 分批和 grep 过滤。若将来源目录可能有奇怪文件名，这里要改。
  find . -type f ! -name '.*' | sed "s#^\./#$sub/#" | sort > "$list"

  if [ "$MODE_ALL" = "0" ]; then
    pending="$list.pending"
    if [ -s "$SENT" ]; then
      # ⚑ 不能写成 `grep … || cp 完整清单`：grep -v 在【过滤掉全部行】时
      #   返回退出码 1（「没选中任何行」），于是「全部已发送」这个最该跳过的
      #   情况反而会把完整清单拷回去，每轮重传全部文件。
      #   实测就是这么发现的 —— 第二次跑又传了同样 3 个。
      grep -Fxv -f "$SENT" "$list" > "$pending"
      : # grep 无匹配返回 1，此处不视为错误
    else
      cp "$list" "$pending"
    fi
  else
    pending="$list"
  fi

  n=$(wc -l < "$pending" | tr -d ' ')
  if [ "$n" -eq 0 ]; then
    rm -f "$list" "$list.pending"
    continue
  fi
  log "$sub: 待发送 $n 个"

  split -l "$BATCH" "$pending" "$list.part."
  batch_no=0
  for part in "$list".part.*; do
    batch_no=$((batch_no + 1))
    cnt=$(wc -l < "$part" | tr -d ' ')
    # 清单里存的是 <sub>/<name>，tar 要的是相对当前目录的 ./<name>
    sed "s#^$sub/#./#" "$part" > "$part.tar"
    # ⚑ 先解到暂存目录，整批 tar 成功后才移进 inbox。
    #   实测教训：批次 4 传到一半 Tailscale 瞬断，tar 在 inbox 里留下一个
    #   【被截断的半个文件】（2.4 MB / 完整应为 4.3 MB）。它不是零字节，
    #   躲过了归档脚本的跳过逻辑，被当成正常照片归档；重传送来完整文件时
    #   同名不同内容，于是存成了 -1 副本 —— 相册里从此有一张打不开的图。
    #   暂存 + 整批移动让中断的传输根本进不了 inbox。
    stage="nas/inbox/.staging.$$.$batch_no"
    if tar -cf - -T "$part.tar" 2>>"$LOG" \
       | ssh $SSH_OPTS "$DEST_USER@$DEST_HOST" \
           "set -e
            mkdir -p '$stage' 'nas/inbox/$sub'
            tar -xf - -C '$stage'
            mv '$stage'/* 'nas/inbox/$sub/' 2>/dev/null || true
            rm -rf '$stage'" >>"$LOG" 2>&1
    then
      cat "$part" >> "$SENT"        # 只有整批成功才记账
      total=$((total + cnt))
      log "$sub: 批次 $batch_no 完成（$cnt 个，累计 $total）"
      echo "  批次 $batch_no: $cnt 个已送达（累计 $total）"
    else
      log "$sub: 批次 $batch_no 失败，$cnt 个未记账，下次重试"
      echo "  批次 $batch_no 失败，下次会重试这一批"
      failed=1
    fi
    rm -f "$part" "$part.tar"
  done
  rm -f "$list" "$list.pending"
done

# 清单去重（--all 模式会重复追加）
sort -u "$SENT" -o "$SENT"

if [ "$failed" = "0" ]; then
  log "本轮完成，共 $total 个文件"
  echo "推送完成：$total 个文件"
else
  log "本轮有批次失败，共成功 $total 个"
  echo "部分失败：成功 $total 个，其余下次重试"
  exit 1
fi
