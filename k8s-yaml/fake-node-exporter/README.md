# Fake node exporter

用来 mock node exporter 监控数据

## 文件说明
主要文件作用说明

- fake-node-exporter.py: mock 数据的脚本
- fake-node-exporter-k8s.yaml: 在 k8s 中部署时使用的 yaml 文件
- grafana-node-dashboard.json： grafana 监控面板
- config.yaml: 本地调试时使用的配置文件；**在 k8s 中部署时需要修改 fake-node-exporter-k8s.yaml 中的 configmap**

## 构建
构建镜像
```bash
docker build -t fake-node-exporter:${version} .
```

## 使用
在 k8s 中部署
```bash
kubectl apply -f fake-node-exporter-k8s.yaml

kubectl get pods -l app=fake-node-exporter
```

pod 运行成功之后可在 prometheus 中查看数据

在 grafana 中创建 dashboard，面板为 grafana-node-dashboard.json
