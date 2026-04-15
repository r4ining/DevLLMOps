## LLM 监控资源说明

本目录用于聚合 LLM 推理服务（SGLang / vLLM）的监控配置，包含：

- Grafana Dashboard JSON
- Grafana Operator 的 `GrafanaDashboard` CRD 生成脚本
- Prometheus Operator 的 `ServiceMonitor`
- VictoriaMetrics Operator 的 `VMRule`

上游面板参考：

- SGLang: https://github.com/sgl-project/sglang/blob/main/examples/monitoring/grafana/dashboards/json/sglang-dashboard.json
- vLLM: https://github.com/vllm-project/vllm/tree/main/examples/online_serving/dashboards/grafana

## 目录结构

```bash
.
├── README.md
├── generate-grafana-dashboard-crd.sh              # 将 grafana-dashboards/*.json 生成 GrafanaDashboard CRD
├── grafana-dashboards/
│   ├── merge-dashboards.py                        # 合并 SGLang + vLLM 两类面板
│   ├── sglang-dashboard-grafana.json
│   ├── vllm-performance-statistics.json
│   ├── vllm-query-statistics.json
│   └── llm-all.json
├── grafana-dashboards-crd/
│   ├── grafana-dashboard-crd-tmpl.yaml            # CRD 模板
│   ├── sglang-dashboard-grafana.yaml
│   ├── vllm-performance-statistics.yaml
│   ├── vllm-query-statistics.yaml
│   └── llm-all.yaml
├── llm-servicemonitor.yaml                        # Service + Endpoints + ServiceMonitor
└── llm-vmrules.yaml                               # VMRule 告警规则
```

## 使用流程

### 1. 准备监控面板 JSON

将面板 JSON 放入 `grafana-dashboards/`。

### 2. （可选）合并多个面板

`merge-dashboards.py` 用于把 3 个面板合并成一个总览面板。

```bash
cd grafana-dashboards
python3 merge-dashboards.py
```

说明：

- 脚本当前会把合并结果写到上一级目录的 `llm-all.json`。
- 若希望输出到 `grafana-dashboards/llm-all.json`，请按需调整脚本中的输出路径。

### 3. 生成 GrafanaDashboard CRD YAML

在 `monitor/` 目录执行：

```bash
bash generate-grafana-dashboard-crd.sh
```

执行后会在 `grafana-dashboards-crd/` 下生成每个 JSON 对应的 `*.yaml` 文件。

### 4. 应用监控资源

```bash
# Service + Endpoints + ServiceMonitor
kubectl apply -f llm-servicemonitor.yaml

# VMRule
kubectl apply -f llm-vmrules.yaml

# Grafana Dashboard CRDs
kubectl apply -f grafana-dashboards-crd/
```

## 配置项说明

### ServiceMonitor

`llm-servicemonitor.yaml` 中包含：

- `Service`（Headless，`clusterIP: None`）
- `Endpoints`（外部 LLM 服务 IP）
- `ServiceMonitor`（抓取 `/metrics`）

落地时至少需要修改：

- `subsets.addresses.ip`：你的 LLM 服务地址
- `ports`：与实际导出指标端口一致
- `relabelings`：按你的实例命名规则调整 `instance`、`llm_engine`

### VMRule

`llm-vmrules.yaml` 当前启用了可用性告警：

- `LLMServiceDown`

其余 vLLM / SGLang 规则以注释形式提供，可按需打开并调整阈值。

### GrafanaDashboard CRD 模板

`grafana-dashboards-crd/grafana-dashboard-crd-tmpl.yaml` 需要按实际环境校准：

- `spec.instanceSelector.matchLabels`
- `spec.folder`

## 注意事项

1. 使用 SGLang / vLLM 时，需要在服务启动参数中显式开启 Prometheus 指标导出。
2. `generate-grafana-dashboard-crd.sh` 会将 dashboard 文件名转换为合法的 Kubernetes `metadata.name`（小写、`-`、长度不超过 63）。
3. `merge-dashboards.py` 读取的输入文件名使用下划线风格（如 `vllm-performance_statistics.json`）。如果你的文件名是连字符风格（如 `vllm-performance-statistics.json`），需先统一命名或修改脚本。



