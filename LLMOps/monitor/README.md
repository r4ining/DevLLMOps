## 监控模型

SGLang 面板：https://github.com/sgl-project/sglang/blob/main/examples/monitoring/grafana/dashboards/json/sglang-dashboard.json
vLLM 面板：https://github.com/vllm-project/vllm/tree/main/examples/online_serving/dashboards/grafana


```bash
.
├── generate-grafana-dashboard-crd.sh               # 根据 dashboard json 文件自动生成 k8s dashboard crd yaml 文件
├── grafana-dashboards
│   ├── llm-all.json                                # 由 merge-dashboard.py 生成
│   ├── merge-dashboard.py                          # 将 SGLang、vLLM 共 3 个面板合并到 1 个面板
│   ├── sglang.json                                 # SGLang 监控面板，基于 SGLang 提供的面板有修改
│   ├── vllm-performance_statistics.json            # vLLM 性能统计
│   └── vllm-query_statistics.json                  # vLLM 查询统计
├── README.md
└── servicemonitor.yaml                             # k8s ServiceMonitor
```

### 注意
使用 SGLang、vLLM 运行模型时需要启用相关的 prometheus 指标参数

SGLang: `

### 使用

将 SGLang、vLLM 共 3 个面板合并到 1 个面板 `llm-all.json`
```bash
cd grafana-dashboards
python merge-dashboard.py
```



