# gen-kubeconfig.sh

为指定用户生成/删除 K8s kubeconfig，支持只读/完全权限 × 集群级/ns 级。

## 用法

```bash
./gen-kubeconfig.sh <user> [权限选项] [范围选项] [其他选项]   # 生成 kubeconfig
./gen-kubeconfig.sh delete <user> [权限选项]                  # 删除该用户的资源
```

## 选项

| 选项 | 等价 | 说明 |
|---|---|---|
| `--readonly` | `--ro` | (默认) 只读，SA 前缀 `ro-` |
| `--readwrite` | `--rw` | 完全权限，SA 前缀 `rw-` |
| `--namespace <ns[,ns...]>` | `--ns` | 指定 ns 级，可逗号分隔或多次指定 |
| `--cluster-name <name>` | `--cn` | kubeconfig 中的集群名（默认: `kubernetes`） |
| `--output <file>` | `-o` | 写入指定文件（不指定则输出到 stdout） |

不指定 `--namespace` 即为集群级。

## 4 种组合

| 命令 | 权限 | 范围 | Role |
|---|---|---|---|
| `--ro` | 只读 | 集群 | `readonly-all` (ClusterRole) |
| `--rw` | 全权 | 集群 | `cluster-admin` (ClusterRole) |
| `--ro --ns prod` | 只读 | ns | `view` (Role) |
| `--rw --ns prod` | 全权 | ns | `admin` (Role) |

## 示例

```bash
# 集群只读
./gen-kubeconfig.sh zhangsan

# 集群全权
./gen-kubeconfig.sh zhangsan --rw

# prod ns 只读
./gen-kubeconfig.sh zhangsan --ro --ns prod

# prod + staging ns 全权
./gen-kubeconfig.sh zhangsan --rw --ns prod,staging

# 指定集群名（默认为 kubernetes）
./gen-kubeconfig.sh zhangsan --rw --cn my-cluster

# 保存到文件（两种方式）
./gen-kubeconfig.sh zhangsan --rw -o ~/.kube/kc-zhangsan
./gen-kubeconfig.sh zhangsan --rw > ~/.kube/kc-zhangsan

# 验证
KUBECONFIG=~/.kube/kc-zhangsan kubectl get pods -A
```

## 删除

同一用户可以同时拥有 ro 和 rw（SA 名不同，互不影响）。

```bash
./gen-kubeconfig.sh delete zhangsan        # 删除该用户所有资源(ro+rw)
./gen-kubeconfig.sh delete zhangsan --ro   # 只删除只读权限
./gen-kubeconfig.sh delete zhangsan --rw   # 只删除完全权限
```

> delete 只删除用户专属的 SA/Secret/Binding，不会删除共享的 ClusterRole `readonly-all`。
