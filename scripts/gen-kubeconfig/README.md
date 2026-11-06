# gen-kubeconfig.sh 说明

为指定用户生成 / 删除 kubeconfig：创建 ServiceAccount + token Secret + RBAC binding，生成后自动验证权限，kubeconfig 保存到 `-o` 指定文件或打印到终端。

## 用法

```bash
./gen-kubeconfig.sh <user> [权限选项] [范围选项] [其他选项]   # 生成
./gen-kubeconfig.sh delete <user> [--ro|--rw]                  # 删除该用户的资源
```

## 选项

| 选项 | 等价 | 说明 |
|------|------|------|
| `--readonly` | `--ro` | (默认) 只读，SA 前缀 `ro-` |
| `--readwrite` | `--rw` | 读写，SA 前缀 `rw-` |
| `--namespace <ns[,ns...]>` | `--ns` | 指定 ns 级，可逗号分隔或多次指定 |
| `--readonly-ns <ns[,ns...]>` | | 额外指定只读 ns，可多次指定（仅用于 `--rw --ns`） |
| `--all-ns-readonly` | | 集群只读：ClusterRoleBinding → `global-readonly` |
| `--all-ns-readwrite` | | 集群读写：ClusterRoleBinding → `cluster-admin`（高权限） |
| `--cluster-name <name>` | `--cn` | kubeconfig 中的集群名（默认 `token-prod`） |
| `--output <file>` | `-o` | 写入指定文件；不指定则打印到终端（用分隔线区分） |

两个 `--all-ns-*` 选项不能同时使用；额外权限选项仅支持与 `--rw --ns` 组合。

## 权限模型

只读统一使用共享 ClusterRole `global-readonly`（缺失时脚本自动创建，幂等；已存在则不改动集群中的定义），读写统一使用内置 ClusterRole `cluster-admin`：

| 命令 | 权限 | 范围 | 绑定 |
|------|------|------|------|
| `--ro` | 只读 | 集群 | ClusterRoleBinding → `global-readonly` |
| `--rw` | 读写 | 集群 | ClusterRoleBinding → `cluster-admin` |
| `--ro --ns prod` | 只读 | ns | RoleBinding → `global-readonly`（限定在 ns） |
| `--rw --ns prod` | 读写 | ns | RoleBinding → `cluster-admin`（限定在 ns） |
| `--readonly-ns staging` | 只读 | 指定 ns | RoleBinding → `global-readonly`（限定在 ns） |
| `--all-ns-readonly` | 只读 | 集群 | ClusterRoleBinding → `global-readonly` |
| `--all-ns-readwrite` | 读写 | 集群 | ClusterRoleBinding → `cluster-admin` |

RoleBinding 引用 ClusterRole 时权限仍限定在该 RoleBinding 所在 ns。`cluster-admin` 为全通配规则，因此 `--rw --ns` 对该 ns 内**所有资源（内置 + 全部 CRD，含 LWS 等）**有读写权限，且仅限该 ns；不授予 CRD 定义等集群级资源的写权限。`global-readonly` 为全通配只读（可读 Secret、CRD 实例与 CRD 定义，允许 port-forward），实际规则以集群中已有定义为准。

同一用户可同时拥有 ro 和 rw（SA 名不同：`ro-<user>` / `rw-<user>`，互不影响）。

## 典型场景：指定 ns 读写，其他所有 ns 只读

```bash
./gen-kubeconfig.sh zhangsan --rw --ns dev-rw --all-ns-readonly -o ./kc-zhangsan
```

脚本自动创建（无需手工 RBAC）：

- RoleBinding `rw-zhangsan-binding`@dev-rw → `cluster-admin`：dev-rw 内所有资源（内置 + CRD）读写
- ClusterRoleBinding `rw-zhangsan-all-global-readonly-binding` → `global-readonly`：其他所有 ns 只读 + 集群级资源（CRD 定义等）只读
- ClusterRole `global-readonly`：缺失时自动创建（幂等，已存在不改动）

## 自动验证

生成后，脚本使用临时 kubeconfig（验证完删除）执行 `kubectl auth can-i`：检查指定 ns、`default` 样例、所有 ns 范围的 Pod 读取 / ConfigMap 创建权限；`--all-ns-readonly` 或集群级只读时还检查 CRD 定义读取权限。如需额外验证某个具体 CRD（如 LWS），可在脚本顶部配置 `VERIFY_CRD`（默认为空，跳过）。结果不符合预期或无法查询时显示警告，但不阻止输出 kubeconfig（可能受已有授权或 RBAC 生效延迟影响）。验证不会创建资源，也不依赖集群中实际存在对应 CRD。

不指定 `-o` 时 kubeconfig 与日志均打印到终端并用分隔线区分；请用 `-o` 保存文件，不要用 stdout 重定向。打印内容包含凭据，注意终端与日志安全。

## 资源与安全

- 用户专属资源（`gen` 创建 / `delete` 清理，均带 label `managed-by=gen-kubeconfig,user=<user>`）：ServiceAccount 和 token Secret 位于 `kube-system`；ClusterRoleBinding 为集群级，RoleBinding 位于目标 ns
- 共享/内置资源不动：ClusterRole `global-readonly`（缺失时自动创建）、`cluster-admin`（内置）、Namespace `kube-system`
- 重新生成同一用户同一权限时，脚本先按 label 清理旧 binding 再创建，期间可能短暂中断权限；此前**手工**创建的绑定（如 `rw-*-all-ns-view`、`crd-definition-reader` 相关）不会被清理，会继续叠加权限，请按需用管理员手动删除
- 需要管理员 kubeconfig 才能执行；不会修改当前环境的 kubeconfig / current-context
