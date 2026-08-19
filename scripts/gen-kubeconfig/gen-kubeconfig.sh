#!/usr/bin/env bash
#
# gen-kubeconfig.sh - 为指定用户生成/删除 kubeconfig
#
# 用法:
#   ./gen-kubeconfig.sh <user> [权限选项] [范围选项] [--cluster-name|--cn <name>] [--output|-o <file>]
#       生成 kubeconfig，输出到 stdout 或指定文件
#   ./gen-kubeconfig.sh delete <user> [--readonly|--ro|--readwrite|--rw]
#       删除该用户的资源（不指定权限则删除该用户所有资源）
#
# 两个正交维度:
#   权限:  --readonly / --ro  (默认) 只读  /  --readwrite / --rw  完全权限
#   范围:  不指定 = 集群级     /  --namespace / --ns <ns...> = 指定 ns 级
#
# 注意: 同一用户可以同时拥有 ro 和 rw 权限（SA 名不同: ro-<user> / rw-<user>，互不影响）
#
# 组合:
#   --readonly                                  集群只读   (ClusterRole: readonly-all)
#   --readwrite                                 集群全权   (ClusterRole: cluster-admin)
#   --readonly  --namespace prod[,staging]       ns 只读    (Role: view)
#   --readwrite --namespace prod[,staging]       ns 全权    (Role: admin)
#
# SA 命名:
#   readonly  -> ro-<user>    (read-only)
#   readwrite -> rw-<user>    (read-write)
#
# 共享资源（不会删除）:
#   - ClusterRole: readonly-all
#   - Namespace:   kube-system (SA 所在)
#
# 用户专属资源（gen 创建 / delete 清理，均带 label: managed-by=gen-kubeconfig,user=<user>）:
#   - ServiceAccount:      <prefix>-<user>          (namespace: kube-system)
#   - Secret (token):      <prefix>-<user>-token    (namespace: kube-system)
#   - ClusterRoleBinding:  <prefix>-<user>-binding  (集群级模式)
#   - RoleBinding:         <prefix>-<user>-binding  (ns 级模式, 每个目标 ns 一个)
#   - kubeconfig:          直接输出到 stdout（不落盘）
#
# 安全保证:
#   - 脚本不会修改当前环境的 kubeconfig 文件或 current-context
#   - 所有 kubectl config 写操作都指向临时文件，输出后删除
#   - 读取集群连接信息时显式使用脚本启动时的 KUBECONFIG（只读）
#   - kubeconfig 只输出到 stdout，由调用方决定保存位置
#
set -euo pipefail

# ============== 可配置项 ==============
NS="kube-system"                       # SA 所在命名空间（共享，不删除）
CLUSTER_ROLE_READONLY="readonly-all"   # 共享的只读 ClusterRole（不删除）
CLUSTER_NAME="kubernetes"             # kubeconfig 中的集群名（默认，可被 --cluster-name 覆盖）
# ====================================

# ---- 环境隔离保护 ----
ORIG_KUBECONFIG="${KUBECONFIG:-}"
CURRENT_KUBECONFIG_FILE=""
if [[ -n "${ORIG_KUBECONFIG}" ]]; then
  CURRENT_KUBECONFIG_FILE="${ORIG_KUBECONFIG%%:*}"
else
  CURRENT_KUBECONFIG_FILE="${HOME}/.kube/config"
fi

# 共享 ClusterRole 定义（首次执行时创建，已存在则跳过）
readonly_CLUSTERROLE=$(cat <<'EOF'
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: readonly-all
rules:
- apiGroups: ["*"]
  resources: ["*"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["*"]
  resources: ["*/proxy"]
  verbs: ["get"]
- nonResourceURLs: ["*"]
  verbs: ["get"]
EOF
)

err()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [ERROR] $*" >&2; exit 1; }
info() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO]  $*" >&2; }

# 根据权限返回 SA 前缀
sa_prefix() {
  case "$1" in
    readonly)  echo "ro" ;;
    readwrite) echo "rw" ;;
    *) err "内部错误: 未知权限 '${1}'" ;;
  esac
}

# 校验用户名：只允许 [a-z0-9-]，避免非法 K8s 资源名/label value
validate_user() {
  local u="$1"
  [[ -n "${u}" ]] || err "用户名不能为空"
  [[ "${u}" =~ ^[a-z]([a-z0-9-]*[a-z0-9])?$ ]] \
    || err "用户名只能包含小写字母/数字/连字符，且以字母开头、以字母或数字结尾: ${u}"
  [[ ${#u} -le 63 ]] || err "用户名过长(>63): ${u}"
}

# 校验 namespace 名
validate_ns() {
  local n="$1"
  [[ -n "${n}" ]] || err "namespace 不能为空"
  [[ "${n}" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]] \
    || err "namespace 名非法: ${n}"
  [[ ${#n} -le 63 ]] || err "namespace 名过长(>63): ${n}"
}

# 确保共享 ClusterRole 存在（幂等）—— 集群只读模式需要
ensure_clusterrole() {
  if kubectl get clusterrole "${CLUSTER_ROLE_READONLY}" >/dev/null 2>&1; then
    info "共享 ClusterRole '${CLUSTER_ROLE_READONLY}' 已存在，跳过创建"
  else
    info "创建共享 ClusterRole '${CLUSTER_ROLE_READONLY}'"
    echo "${readonly_CLUSTERROLE}" | kubectl apply -f -
  fi
}

# 确保命名空间存在（幂等）
ensure_namespace() {
  local target_ns="$1"
  if kubectl get ns "${target_ns}" >/dev/null 2>&1; then
    return 0
  fi
  info "创建命名空间 '${target_ns}'"
  kubectl create namespace "${target_ns}"
}

# 查找该用户某权限下已有的 SA 名（基于 label），返回 SA 名或空
find_user_sa() {
  local user="$1" perm="$2"
  kubectl -n "${NS}" get serviceaccount \
    -l managed-by=gen-kubeconfig,user="${user}",perm="${perm}" \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true
}

# 清理该用户某权限下的所有 binding（基于 label selector）
# 参数: user perm  —— perm 为空时清理该用户所有权限的 binding
cleanup_old_bindings() {
  local user="$1" perm="${2:-}"
  local label="managed-by=gen-kubeconfig,user=${user}"
  [[ -n "${perm}" ]] && label="${label},perm=${perm}"

  # ClusterRoleBinding
  kubectl delete clusterrolebinding \
    -l "${label}" \
    --ignore-not-found=true 2>/dev/null || true

  # RoleBinding（跨所有 ns 查找）
  local rbs
  rbs=$(kubectl get rolebinding -A \
    -l "${label}" \
    -o jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name}{"\n"}{end}' 2>/dev/null || true)
  if [[ -n "${rbs}" ]]; then
    while IFS= read -r rb; do
      [[ -z "${rb}" ]] && continue
      local rb_ns="${rb%%/*}"
      local rb_name="${rb##*/}"
      kubectl -n "${rb_ns}" delete rolebinding "${rb_name}" --ignore-not-found=true 2>/dev/null || true
    done <<< "${rbs}"
  fi
}

# 清理该用户的 SA 和 Secret（基于 label）
# 参数: user perm  —— perm 为空时清理该用户所有权限的 SA/Secret
cleanup_user_sa_secret() {
  local user="$1" perm="${2:-}"
  local label="managed-by=gen-kubeconfig,user=${user}"
  [[ -n "${perm}" ]] && label="${label},perm=${perm}"

  kubectl -n "${NS}" delete secret \
    -l "${label}" \
    --ignore-not-found=true 2>/dev/null || true
  kubectl -n "${NS}" delete serviceaccount \
    -l "${label}" \
    --ignore-not-found=true 2>/dev/null || true
}

# 创建 binding
# 参数: user perm scope sa namespaces...
create_binding() {
  local user="$1" perm="$2" scope="$3" sa="$4"
  shift 4
  local namespaces=()
  [[ $# -gt 0 ]] && namespaces=("$@")
  local binding="${sa}-binding"

  cleanup_old_bindings "${user}" "${perm}"

  if [[ "${scope}" == "cluster" ]]; then
    # ---- 集群级 ----
    local role_name
    if [[ "${perm}" == "readonly" ]]; then
      role_name="${CLUSTER_ROLE_READONLY}"
      info "创建 ClusterRoleBinding (集群只读, role=${role_name}) -> ${binding}"
    else
      role_name="cluster-admin"
      info "创建 ClusterRoleBinding (集群全权, role=${role_name}) -> ${binding}"
    fi
    kubectl apply -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: ${binding}
  labels:
    managed-by: gen-kubeconfig
    user: ${user}
    perm: ${perm}
    scope: cluster
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: ${role_name}
subjects:
- kind: ServiceAccount
  name: ${sa}
  namespace: ${NS}
EOF
  else
    # ---- namespace 级 ----
    local role_name
    if [[ "${perm}" == "readonly" ]]; then
      role_name="view"
    else
      role_name="admin"
    fi
    local target_ns
    for target_ns in ${namespaces[@]+"${namespaces[@]}"}; do
      info "创建 RoleBinding (ns只读/全权=${perm}, role=${role_name}@${target_ns}) -> ${binding}"
      kubectl apply -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: ${binding}
  namespace: ${target_ns}
  labels:
    managed-by: gen-kubeconfig
    user: ${user}
    perm: ${perm}
    scope: namespace
    target-namespace: ${target_ns}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: ${role_name}
subjects:
- kind: ServiceAccount
  name: ${sa}
  namespace: ${NS}
EOF
    done
  fi
}

# 生成/刷新某用户的 kubeconfig
# 参数: user perm scope cluster_name output_file namespaces...
#   output_file 为空时输出到 stdout
do_gen() {
  local user="$1" perm="$2" scope="$3" cluster_name="$4" output_file="$5"
  shift 5
  local namespaces=()
  [[ $# -gt 0 ]] && namespaces=("$@")
  local prefix
  prefix=$(sa_prefix "${perm}")
  local sa="${prefix}-${user}"
  local secret="${sa}-token"
  local user_ctx="${sa}@${cluster_name}"
  local out ca_file
  out=$(mktemp -t kubeconfig-"${user}".XXXXXX)
  ca_file=""
  trap 'rm -f "${out}" "${ca_file}"' EXIT

  validate_user "${user}"

  # 准备与校验
  ensure_namespace "${NS}"
  if [[ "${scope}" == "cluster" ]]; then
    if [[ "${perm}" == "readonly" ]]; then
      ensure_clusterrole
      info "权限: 集群只读 (readonly)  范围: 集群级  SA=${sa}"
    else
      info "权限: 集群全权 (readwrite)  范围: 集群级  SA=${sa}"
    fi
  else
    [[ ${#namespaces[@]:-0} -gt 0 ]] || err "namespace 模式需要至少指定一个 ns"
    local n
    for n in ${namespaces[@]+"${namespaces[@]}"}; do
      validate_ns "${n}"
      ensure_namespace "${n}"
    done
    if [[ "${perm}" == "readonly" ]]; then
      info "权限: ns 只读 (readonly)  范围: ns=${namespaces[*]:-}  SA=${sa}"
    else
      info "权限: ns 全权 (readwrite)  范围: ns=${namespaces[*]:-}  SA=${sa}"
    fi
  fi

  # 检查同权限下是否已有旧 SA（scope 切换时需要清理旧 binding）
  # 注意：ro 和 rw 可以共存，不互删；只清理同 perm 的旧 binding
  local old_sa
  old_sa=$(find_user_sa "${user}" "${perm}")
  if [[ -n "${old_sa}" && "${old_sa}" != "${sa}" ]]; then
    info "检测到同权限下 SA 名变更 (旧: ${old_sa} -> 新: ${sa})，清理旧资源"
    cleanup_old_bindings "${user}" "${perm}"
    cleanup_user_sa_secret "${user}" "${perm}"
  fi

  info "为用户 '${user}' 准备资源: SA=${sa}, Secret=${secret}"

  # 1) ServiceAccount（幂等：apply，带 label）
  kubectl -n "${NS}" apply -f - <<EOF
apiVersion: v1
kind: ServiceAccount
metadata:
  name: ${sa}
  namespace: ${NS}
  labels:
    managed-by: gen-kubeconfig
    user: ${user}
    perm: ${perm}
    scope: ${scope}
EOF

  # 2) Token Secret（幂等：apply；如已存在会保留旧 token）
  kubectl -n "${NS}" apply -f - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: ${secret}
  namespace: ${NS}
  labels:
    managed-by: gen-kubeconfig
    user: ${user}
  annotations:
    kubernetes.io/service-account.name: ${sa}
type: kubernetes.io/service-account-token
EOF

  # 3) Binding
  create_binding "${user}" "${perm}" "${scope}" "${sa}" ${namespaces[@]+"${namespaces[@]}"}

  # 4) 等待 token 写入 Secret
  info "等待 token 写入 Secret '${secret}'..."
  local token=""
  for _ in $(seq 1 30); do
    token=$(kubectl -n "${NS}" get secret "${secret}" \
              -o jsonpath='{.data.token}' 2>/dev/null | base64 -d 2>/dev/null || true)
    [[ -n "${token}" ]] && break
    sleep 1
  done
  [[ -n "${token}" ]] || err "获取 token 失败，请检查 Secret '${secret}'"

  # 5) 从当前 kubeconfig 取集群连接信息（只读，显式使用原始 KUBECONFIG）
  local server ca
  server=$(KUBECONFIG="${ORIG_KUBECONFIG}" kubectl config view --raw -o jsonpath='{.clusters[0].cluster.server}')
  ca=$(KUBECONFIG="${ORIG_KUBECONFIG}" kubectl config view --raw -o jsonpath='{.clusters[0].cluster.certificate-authority-data}')
  [[ -n "${server}" ]] || err "无法从当前 kubeconfig 获取 server 地址"
  [[ -n "${ca}" ]]     || err "无法从当前 kubeconfig 获取 CA 证书"

  # kubectl config set-cluster 不支持 --certificate-authority-data，
  # 需要先把 base64 的 CA 解码写入临时文件，再用 --certificate-authority + --embed-certs
  ca_file=$(mktemp -t ca.XXXXXX)
  echo "${ca}" | base64 -d > "${ca_file}"

  # 6) 组装该用户的 kubeconfig 到临时文件
  kubectl config set-cluster "${cluster_name}" \
    --server="${server}" \
    --certificate-authority="${ca_file}" \
    --kubeconfig="${out}" --embed-certs=true >/dev/null

  kubectl config set-credentials "${user_ctx}" \
    --token="${token}" \
    --kubeconfig="${out}" >/dev/null

  # ns 级模式时，context 默认指向第一个 ns
  if [[ "${scope}" == "namespace" ]]; then
    kubectl config set-context "${user_ctx}" \
      --cluster="${cluster_name}" \
      --user="${user_ctx}" \
      --namespace="${namespaces[0]:-}" \
      --kubeconfig="${out}" >/dev/null
  else
    kubectl config set-context "${user_ctx}" \
      --cluster="${cluster_name}" \
      --user="${user_ctx}" \
      --kubeconfig="${out}" >/dev/null
  fi

  kubectl config use-context "${user_ctx}" --kubeconfig="${out}" >/dev/null
  chmod 600 "${out}"

  rm -f "${ca_file}"

  # 7) 输出 kubeconfig
  if [[ -n "${output_file}" ]]; then
    # 写入指定文件
    cp "${out}" "${output_file}"
    chmod 600 "${output_file}"
    info "✅ 用户 '${user}' 的 kubeconfig 已生成 (perm=${perm}, scope=${scope}, SA=${sa})"
    info "   用户标识: ${user_ctx}"
    if [[ "${scope}" == "namespace" ]]; then
      info "   授权 namespace: ${namespaces[*]:-}"
      info "   context 默认 ns: ${namespaces[0]:-}"
    fi
    info "   已保存到: ${output_file}"
    info "   验证: KUBECONFIG=${output_file} kubectl get pods -A"
  else
    # 输出到 stdout（纯净 kubeconfig，无分隔线，可直接重定向）
    info "✅ 用户 '${user}' 的 kubeconfig 已生成 (perm=${perm}, scope=${scope}, SA=${sa})"
    info "   用户标识: ${user_ctx}"
    if [[ "${scope}" == "namespace" ]]; then
      info "   授权 namespace: ${namespaces[*]:-}"
      info "   context 默认 ns: ${namespaces[0]:-}"
    fi
    info "   当前环境 kubeconfig: ${CURRENT_KUBECONFIG_FILE}（脚本未修改它）"
    info "   kubeconfig:"
    info "----------------------------- KUBECONFIG ------------------------------"
    cat "${out}"
  fi

  rm -f "${out}"
  trap - EXIT
}

# 删除某用户的专属资源（基于 label，保留共享 ClusterRole 和 namespace）
# 参数: user [perm]  —— perm 为空时删除该用户所有权限的资源
do_delete() {
  local user="$1" perm="${2:-}"
  validate_user "${user}"

  local label="managed-by=gen-kubeconfig,user=${user}"
  [[ -n "${perm}" ]] && label="${label},perm=${perm}"

  if [[ -n "${perm}" ]]; then
    info "删除用户 '${user}' 的 ${perm} 权限资源（保留共享 ClusterRole '${CLUSTER_ROLE_READONLY}'）"
  else
    info "删除用户 '${user}' 的所有专属资源（保留共享 ClusterRole '${CLUSTER_ROLE_READONLY}'）"
  fi

  # 删除顺序：binding -> Secret -> SA
  cleanup_old_bindings "${user}" "${perm}"
  cleanup_user_sa_secret "${user}" "${perm}"

  if [[ -n "${perm}" ]]; then
    info "✅ 用户 '${user}' 的 ${perm} 权限资源已清理"
  else
    info "✅ 用户 '${user}' 的所有专属资源已清理"
  fi
}

usage() {
  cat <<EOF
用法:
  $0 <user> [权限选项] [范围选项] [其他选项]   生成 kubeconfig
  $0 delete <user> [权限选项]                  删除该用户的资源

权限选项:
  --readonly, --ro                  (默认) 只读，SA 前缀 ro-
  --readwrite, --rw                 完全权限，SA 前缀 rw-

范围选项:
  (不指定)                           集群级
  --namespace, --ns <ns[,ns...]>     指定 ns 级，可逗号分隔或多次指定

其他选项:
  --cluster-name, --cn <name>        kubeconfig 中的集群名（默认: kubernetes）
  --output, -o <file>                写入指定文件（不指定则输出到 stdout）

注意: 同一用户可以同时拥有 ro 和 rw 权限（SA 名不同，互不影响）

组合示例:
  $0 zhangsan                                          # 集群只读 (ro-zhangsan)
  $0 zhangsan --rw                                     # 集群全权 (rw-zhangsan)
  $0 zhangsan --ro  --ns prod                          # prod 只读 (ro-zhangsan)
  $0 zhangsan --rw --ns prod                           # prod 全权 (rw-zhangsan)
  $0 zhangsan --rw --ns prod,staging                   # prod+staging 全权
  $0 zhangsan --rw --ns prod --ns staging              # 同上
  $0 zhangsan --rw --cn my-cluster                     # 指定集群名 my-cluster

保存与删除:
  $0 zhangsan --rw -o ~/.kube/kc-zhangsan              # 保存到文件
  $0 zhangsan --rw > ~/.kube/kc-zhangsan               # 重定向保存（stdout 纯净）
  $0 delete zhangsan                                   # 删除该用户所有资源(ro+rw)
  $0 delete zhangsan --ro                              # 只删除只读权限
  $0 delete zhangsan --rw                              # 只删除完全权限
EOF
}

main() {
  [[ $# -ge 1 ]] || { usage; exit 1; }

  # 当前 kubeconfig 必须有集群访问权限
  kubectl get ns >/dev/null 2>&1 || err "当前 kubeconfig 无集群访问权限，请先配置管理员 kubeconfig"

  case "$1" in
    delete)
      [[ $# -ge 2 ]] || { usage; exit 1; }
      local del_user="$2" del_perm=""
      shift 2
      while [[ $# -gt 0 ]]; do
        case "$1" in
          --readonly|--ro)  del_perm="readonly"; shift ;;
          --readwrite|--rw) del_perm="readwrite"; shift ;;
          *) err "delete 只支持 --readonly/--ro 或 --readwrite/--rw，未知参数: $1" ;;
        esac
      done
      do_delete "${del_user}" "${del_perm}"
      ;;
    -h|--help|help)
      usage
      ;;
    *)
      local user="$1" perm="readonly" cluster_name="${CLUSTER_NAME}" output_file=""
      local namespaces=()
      shift
      while [[ $# -gt 0 ]]; do
        case "$1" in
          --readonly|--ro)
            perm="readonly"; shift ;;
          --readwrite|--rw)
            perm="readwrite"; shift ;;
          --namespace|--ns)
            [[ $# -ge 2 ]] || err "--namespace 需要参数: <ns[,ns...]>"
            # 支持逗号分隔
            local IFS=','
            read -ra ns_arr <<< "$2"
            local ns_item
            for ns_item in "${ns_arr[@]}"; do
              # 去除首尾空格
              ns_item="${ns_item## }"
              ns_item="${ns_item%% }"
              [[ -n "${ns_item}" ]] && namespaces+=("${ns_item}")
            done
            shift 2
            ;;
          --cluster-name|--cn)
            [[ $# -ge 2 ]] || err "--cluster-name 需要参数: <name>"
            cluster_name="$2"
            shift 2
            ;;
          --output|-o)
            [[ $# -ge 2 ]] || err "--output 需要参数: <file>"
            output_file="$2"
            shift 2
            ;;
          *)
            err "未知参数: $1（可用: --readonly/--ro / --readwrite/--rw / --namespace/--ns <ns> / --cluster-name/--cn <name> / --output/-o <file>）"
            ;;
        esac
      done
      # 防止误覆盖当前 kubeconfig
      if [[ -n "${output_file}" ]]; then
        local abs_output
        abs_output=$(cd "$(dirname "${output_file}")" 2>/dev/null && echo "$(pwd)/$(basename "${output_file}")" || echo "${output_file}")
        if [[ "${abs_output}" == "${CURRENT_KUBECONFIG_FILE}" ]]; then
          err "拒绝写入当前正在使用的 kubeconfig: ${output_file}（避免覆盖当前环境配置）"
        fi
      fi
      local scope="cluster"
      [[ ${#namespaces[@]:-0} -gt 0 ]] && scope="namespace"
      do_gen "${user}" "${perm}" "${scope}" "${cluster_name}" "${output_file}" ${namespaces[@]+"${namespaces[@]}"}
      ;;
  esac
}

main "$@"
