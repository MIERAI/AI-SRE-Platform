# 手机集群：真实设备的监控与服务

两台安卓手机（Termux，非 root）组成的小型自治系统。**这是本项目第一份不依赖模拟器的数据源** ——
在此之前，`agent/tools/cluster.py` 第一行就写着「明确是模拟器」，所有告警都是手写的 JSON 常量。

```
手机1（在家，常插电）                        手机2（随身）
  sshd  rclone(WebDAV)  transmission            sshd
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
~/services.sh stop       # 停止全部，但【保留 sshd】
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
| `phone_metrics.py` | 设备传感器 → Prometheus 格式 |
| `prometheus.yml` `rules.yml` | 抓取配置与 8 条告警 |
| `grafana.ini` `provisioning-*.yaml` `phone-*.json` | Grafana 与两块看板 |
| `start-{prometheus,grafana,filebrowser}.sh` | 各服务的启动包装 |
| `aria2.conf` `start-aria2.sh` | 下载机：HTTP 多线程分片 / BT / 磁力 + AriaNg 界面 |
| `photopush.sh` `tun.sh` | 手机2 侧：照片推送与隧道 |
| `archive_photos.py` | 照片按 EXIF 日期归档 + 缩略图 |
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

## 已知缺口

**告警送不出去。** 8 条规则会写成 `ALERTS{...}` 序列存进 TSDB，可以事后取证，
但没有任何东西会通知人。设备彻底失联时更糟 —— 连「我死了」都发不出来。
