记录 Chart 来源

## Storage
### Longhorn
> https://longhorn.io/docs/1.10.1/deploy/install/install-with-helm/
```bash
helm repo add longhorn https://charts.longhorn.io
helm repo update

helm fetch longhorn/longhorn
```

### MinIO
文档镜像站：
https://minio-docs.cc
https://miniodocs.cc

> https://github.com/minio/operator/tree/v5.0.18/helm
```bash
helm repo add minio https://operator.min.io/
helm repo update

helm fetch minio/operator
helm fetch minio/tenant
```


