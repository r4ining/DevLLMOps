
# 
```bash
# 获取helm应用中的镜像
helmfile -f ./helmfile/releases/fake-gpu-operator.yaml template | grep "image:" | awk '{print $NF}' | tr -d '\"' | sort -u
```
