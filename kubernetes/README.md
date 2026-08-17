# 本地监控栈：启停

## ⚠️ 先看这条

这台机器的 `kubectl` current-context 是**公司的 GKE staging 集群**
（形如 `gke_<project>_<region>_<cluster>`）。
`kind create cluster` 默认会改写 `~/.kube/config` 并把 context 切走 ——
之后很容易在以为是本地的情况下操作生产环境。

**所以本地集群一律用独立的 kubeconfig：**

```bash
export KUBECONFIG=~/.kube/kind-sre.config
```

下面所有命令都假设已 export。忘了 export 时 `kubectl` 会连到公司集群，
`kubectl get pods` 看到一堆陌生 Pod 就是这个原因。

---

## 启动

```bash
# 0) 前提：OrbStack（GUI 应用，需自己启动一次）
orb start

# 1) 腾内存 —— 24GiB 单机放不下「集群 + 14B + judge」
#    演练监控链路只需要 4B judge；端到端排查已在 Phase 5 用完整危害矩阵验证过
ollama stop qwen3:14b

# 2) 集群
export KUBECONFIG=~/.kube/kind-sre.config
kind create cluster --config kubernetes/kind-cluster.yaml

# 3) Prometheus（规则从 monitoring/ 挂进去）
kubectl create configmap prometheus-rules \
  --from-file=alerts.yaml=monitoring/alerts.yaml \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f kubernetes/prometheus.yaml

# 4) Grafana（dashboard 走 provisioning，UI 改不动，改面板要改仓库里的 JSON）
kubectl create configmap grafana-dashboards \
  --from-file=dashboard.json=monitoring/dashboard.json \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f kubernetes/grafana.yaml

# 5) Agent 跑在【宿主机】上，不在集群里 —— 模型不进 Pod 的直接后果
MAIN_MODEL=qwen3:4b GUARD=mlx CANARY_INTERVAL=120 \
  uv run uvicorn deployment.server:app --host 0.0.0.0 --port 8080
```

访问：Grafana <http://localhost:30030> · Prometheus <http://localhost:30090>
· Agent <http://localhost:8080/canary>

## 改了规则或面板之后

```bash
kubectl create configmap prometheus-rules \
  --from-file=alerts.yaml=monitoring/alerts.yaml \
  --dry-run=client -o yaml | kubectl apply -f -
sleep 12                                    # ConfigMap 挂载同步有延迟
curl -XPOST localhost:30090/-/reload
```

## 停止 / 释放内存

```bash
pkill -f "uvicorn deployment.server"        # Agent（宿主机）
kind delete cluster --name sre              # 集群（重建约 1 分钟，配置都在版本库）
orb stop                                    # OrbStack VM（占用最大的一块）
ollama stop qwen3:4b                        # 判别器 / 主模型
```

---

## 验证清单（部署完请依次跑，别只看「Running」）

这三条都是**实测踩出来的**，不是形式主义：

```bash
# ① 抓取目标是否真的 up
curl -s localhost:30090/api/v1/targets | grep -o '"health":"[a-z]*"'

# ② 告警规则「能不能触发」—— 不只是「没报错」。
#    实测踩过：裸 `and` 因 label 匹配失败而【永不触发】，
#    界面上一直显示 inactive，看起来岁月静好。
#    做法：把阈值改成必然成立，看查询是否真返回结果。
curl -s --get localhost:30090/api/v1/query \
  --data-urlencode 'query=sre_guard_canary_detection_rate < 1.5 and on(family) (sum by(family)(sre_guard_canary_checks_total) >= 1)'

# ③ 面板查询是否真有数据 —— 「加载成功」不等于「有数据」。
#    实测踩过：14 个面板查询只有 4 个有数据，两处是【永远不会有数据】的埋点缺失。
python3 - <<'EOF'
import json, subprocess, urllib.parse
d = json.load(open('monitoring/dashboard.json'))
for p in d['panels']:
    for t in p.get('targets', []):
        u = "http://localhost:30090/api/v1/query?query=" + urllib.parse.quote(t['expr'])
        r = json.loads(subprocess.run(["curl","-s","-m","10",u],capture_output=True,text=True).stdout)
        n = len(r['data']['result']) if r.get('status')=='success' else -1
        print(f"{'✓' if n>0 else '·'} {p['title'][:30]:<32}{t.get('legendFormat','')[:20]}")
EOF
```

完整的设计理由与踩坑记录见 [`docs/phase6-why.md`](../docs/phase6-why.md)。
