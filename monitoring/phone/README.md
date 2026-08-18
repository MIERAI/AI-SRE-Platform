# 手机集群：真实设备的监控与服务

两台安卓手机（Termux，非 root）组成的小型自治系统。**这是本项目第一份不依赖模拟器的数据源** ——
在此之前，`agent/tools/cluster.py` 第一行就写着「明确是模拟器」，所有告警都是手写的 JSON 常量。

```
手机1（在家，常插电）                        手机2（随身）
  sshd  rclone(WebDAV)                        sshd
  aria2 + AriaNg（下载机）
  exporter → Prometheus → Grafana               tunnel ──┐
  File Browser                                  photopush │
  archive_photos（照片归档）                              │
        ▲                                                │
        └──────────── tar over ssh / SSH 隧道 ────────────┘
```

## 一键启停

```bash
~/services.sh start      # 启动所有未运行的（幂等）
~/services.sh stop       # 停止全部，但【保留 sshd】；15 分钟内会被 watchdog 拉回
~/services.sh stop --no-watchdog   # 连自愈一起停，不会自动恢复
~/services.sh stop --all # 连 sshd 一起停 —— 远程执行会失去连接
~/services.sh status     # 进程 + 端口 + 实际 HTTP 响应
```

`status` 不满足于「进程在」。今天踩了太多次「进程活着但没在服务」，所以它对每个
HTTP 服务实际发一次请求。

## 文件

| 文件 | 作用 |
|---|---|
| `services.sh` | 统一启停。**唯一定义「怎么启动」的地方** |
| `watchdog.sh` | 15 分钟自愈，委托给 `services.sh`（54 行 → 36 行） |
| `boot-10-sshd.sh` `boot-20-services-*.sh` | 开机自启，编号决定顺序 |
| `bashrc-hook.sh` | 打开 Termux 即自动拉起服务（→ `~/.bashrc`）|
| `phone_metrics.py` | 设备传感器 → Prometheus 格式 |
| `prometheus.yml` `rules.yml` | 抓取配置与 8 条告警 |
| `grafana.ini` `provisioning-*.yaml` `phone-*.json` | Grafana 与三块看板（桌面 / 移动 / 健康总览） |
| `datastats.sh` | 各目录体积与文件数，缓存给 exporter |
| `start-{prometheus,grafana,filebrowser}.sh` | 各服务的启动包装 |
| `aria2.conf` `start-aria2.sh` | 下载机：HTTP 多线程分片 / BT / 磁力 + AriaNg 界面 |
| `photopush.sh` `tun.sh` `tunwatch.sh` | 手机2 侧：照片推送、隧道、自愈 |
| `shortcuts-phone1/` `shortcuts-phone2/` | Termux:Widget 桌面快捷方式（点图标即执行） |
| `archive_photos.py` | 照片按 EXIF 日期归档 + 缩略图 |
| `diskguard.sh` | 磁盘保护：低于阈值自动暂停下载（带滞回） |
| `logrotate.sh` | 日志轮转。含白名单外的兜底 —— 失控日志往往是临时起的 |
| `selfrepair.sh` | 连续启动失败时**隔离**（不删除）损坏数据并重建 |
| `memprobe.py` | 内存压力探针：测出多少内存压力下 Termux 被杀 |
| `verify.py` | 部署自检：告警能否触发、面板有无数据 |

## 踩过的坑（都写在对应文件的注释里）

这些的共同点是**故障不报错**：

| 现象 | 真相 |
|---|---|
| CPU 频率图有一条正常曲线 | 标签解析错误，8 个核塌缩成一条 `{cpu=""}`。`up` 恒为 1，日志干净 |
| 缩略图计数器显示 5 | 写进了真实相册目录 —— `--dest` 只管了一半 |
| rsync 退出、无报错 | 接收端 `chdir` 拿 EACCES。**rsync 在此 Termux 上做不了接收端**，改用 tar over ssh |
| 相册里一张图打不开 | 传输中断留下截断文件（2.4 MB / 应 4.3 MB），非零字节，被正常归档 |
| 截断检测判出 11 张坏图 | 误报。Motion Photo 的 JPEG 后面追加了 MP4，本就不以 `FFD9` 结尾 |
| 每轮重传全部照片 | `grep -v` 过滤掉全部行时返回 1，触发了 `\|\| cp 完整清单` |
| transmission 重启后登录不上 | 密码抽取少了一位。探测返回 401 是「正常」的，看不出来 |
| 告警界面一直安详的 `inactive` | 裸 `and` 的 label 集不匹配，规则**永不触发** |
| AriaNg 页面打开是乱码 | release 的 AllInOne 资源是 `.zip` 不是 `.html`，直接改名当页面用了 |
| 完整性面板一直空着 | `offset 24h` 要等满 24 小时才有数据。改 `max_over_time` 立刻可用，且能识别「掉了又补回一部分」 |
| Termux 被杀后等 30 分钟也不恢复 | **安卓强杀会连带取消 JobScheduler 任务**，之后没有任何东西会触发。电池优化设成「不受限制」也无效——那管 Doze/App Standby，管不了低内存杀手 |
| 同一服务被连续重启两次 | `.bashrc` 钩子与 watchdog 并发调 `services.sh start`，都判定「没在跑」都去启动，后者抢到端口、前者绑定失败。加 mkdir 互斥锁（实测三个并发被串行化，只有一个真正执行） |
| aria2「已启动」但关掉窗口就死 | `nohup` 只挡 SIGHUP 的默认动作，而 aria2 主动把 SIGHUP 当关机信号（日志留 `Download Results:`）。改用 `--daemon=true` |
| 手机2 失联：ping 通但 8022 拒绝 | `tunwatch.sh` 只管隧道不管 sshd，而 sshd 才是入口。手机1 的 watchdog 一直调 `services.sh start`，两台逻辑不一致 |
| Termux 被杀的同时 Tailscale 也断，且不自动回来 | 安卓 VPN 只有开了「始终开启的 VPN」才会自启。watchdog 管不到它 |
| 磁盘保护「已暂停下载」，下载照跑 | `set -u` 下裸 `$2` 触发 unbound variable，脚本中途夭折 |
| 保护生效了，新任务仍全速下载 | aria2 拒绝 `max-concurrent-downloads=0`（最小 1），而响应被 `>/dev/null` 吞了 |

共同的教训：**计数器对，不代表事情做对了。** 每一处都是去数目标端的实际文件、
实际序列数、实际能否认证才发现的。

## 部署后必做

```bash
python ~/verify.py     # 告警能否触发 + 每个面板当前是否真有数据
```

## 设备上需要、但不在版本库里的

```bash
~/.services.env        # rclone / transmission 的账号密码（600）
~/grafana/ADMIN_PASSWORD.txt
~/fb/ADMIN_PASSWORD.txt
```

## 桌面一键操作

装 Termux:Widget 后，`~/.shortcuts/` 下的脚本可以放到桌面：
长按桌面 → 小组件 → Termux widget（列表）或 Termux shortcut（单个图标）。

    手机1              手机2
    1-启动全部          1-启动全部（含 Tailscale 检测）
    2-状态              2-状态
    3-自检              3-推送照片
    4-重启全部          4-重连隧道

⚑ 手机1 那组刻意做成【不懂技术的人也能用】：托人去房间时点「1-启动全部」，
  它会启动服务、重新注册定时任务、最后打印 `✅ 全部正常（8/8）`。
  不需要敲任何命令。

## 能让 Termux 崩掉的手段（实测清单）

| 手段 | 状态 |
|---|---|
| 内存分配尖峰 | 实测会杀整组。llama.cpp 不设 `-c` 时 RSS 10 GB → 必死 |
| **phantom process 上限** | Android 12+ 机制，**上限 32 个子进程**。实测 Android 16/realme 上生效。服务空载只占 8 个，压力主要来自累积的 SSH 会话（每条 +2）和忘了停的调试脚本。上限从 Termux 里读不到也改不了（要 adb）。已加 `phone_process_count` 指标 + >24 告警 |
| **失控日志填满磁盘** | 实测见过 378 MB / 3 分钟（约 2 MB/s）→ 638 GB 在 88 小时内可被填满。已加 `logrotate.sh` |
| **硬杀导致数据损坏** | Prometheus WAL / Grafana sqlite / filebrowser bolt 损坏会让服务**拒绝启动**，而 watchdog 每 15 分钟重试、日志一直有记录，看着像在工作。已加 `selfrepair.sh`（连续 3 次失败→隔离数据重建）|
| 磁盘被下载吃满 | `diskguard.sh` 已防 |
| 拔电 / 断电 | 有告警但**送不出去**，实质无防御 |
| 持续满载导致热杀 | 未测。安卓有 thermal mitigation 会杀后台应用 |
| realme UI 的后台冻结 | 独立于标准安卓设置，需在手机上单独关 |

## 恢复路径的真实状态（实测）

| 路径 | 状态 |
|---|---|
| 单个服务挂了 → watchdog 15 分钟拉起 | ✓ 有效 |
| Termux 被强杀 → JobScheduler 恢复 | ✗ **任务被一起取消**，等 30 分钟无效 |
| 手机重启 → Termux:Boot | ✗ 2.5 分钟内未触发（本该近乎立即）|
| 手机重启 → JobScheduler 持久化任务 | ? **未测到** —— 在 15 分钟前就停止观察了 |
| 有人打开 Termux App | ✓ `.bashrc` 钩子自动拉起全部，零命令 |

⚑ 开机脚本与 watchdog 都会往 `~/boot_trace.log` 留痕，
  下次重启后看它就能区分是哪条路走通的 —— 之前无法区分
  「Boot 没触发」和「触发了但脚本失败」，而两者修法完全不同。

## 在这台设备上跑模型

能跑，但有两个参数不能省。完整实测见
[`docs/phone-inference-limits.md`](../../docs/phone-inference-limits.md)。

```bash
llama-completion -m ~/nas/models/qwen3-4b.gguf -p "..." -n 96 -c 2048 -t 2
```

| | 默认 `-c` | `-c 2048` |
|---|---|---|
| RSS | 9~10 GB | **2.67 GB** |
| 后果 | Termux 整组被杀 | 服务全程 8/8 |

⚑ 模型文件只有 2.5 GB，差出来的 7 GB 是**默认上下文（32k~40k）的 KV cache**。
⚑ `llama-cli` 即使加 `-no-cnv`、stdin 给 `/dev/null` 也会进交互模式空转刷 `> `
  （实测 378 MB 日志里 499,488 次），改用 `llama-completion`。

## 已知缺口

**File Browser 上游要归档了。** 启动日志里的公告：项目于 **2026-09-01 归档**，
之后不再有版本发布和安全修复。它只绑 127.0.0.1、经 SSH 隧道访问，
暴露面很小，但长期要考虑替代（或接受不再更新）。


**告警送不出去。** 8 条规则会写成 `ALERTS{...}` 序列存进 TSDB，可以事后取证，
但没有任何东西会通知人。设备彻底失联时更糟 —— 连「我死了」都发不出来。
