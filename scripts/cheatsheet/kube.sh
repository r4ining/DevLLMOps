# 命令行切换多个k8s集群(bash版本)

# alias
alias k='kubectl'
alias kc='kubecolor'

# 启用 kubectl 自动补全（bash）
source <(kubectl completion bash)
# 默认情况下 bash 补全会有问题，需要 source 一下 /etc/profile.d/bash_completion.sh
source /etc/profile.d/bash_completion.sh

complete -F __start_kubectl k
complete -F __start_kubectl kc
complete -F __start_kubectl kubecolor

# 设置语言，避免 k9s 边框问题
export LANG=en_US.UTF-8
# export LC_ALL=en_US.UTF-8

# add kubeconfig
function add-kube() {
    set -u
    kubeconfig_file=$1
    cluster_name=$2

    profile_file="${HOME}/.kube.sh"
    mkdir -p ${HOME}/.kube

    echo "Copy kubeconfig: ${kubeconfig_file} -> ~/.kube/kubeconfig-${cluster_name}"
    cp -fv "${kubeconfig_file}" "${HOME}/.kube/kubeconfig-${cluster_name}"

    echo "Add a-${cluster_name} function(for activate kubeconfig) to ${profile_file}"
    sed -i "/${cluster_name} CONFIG START/,/${cluster_name} CONFIG END/d" "${profile_file}"
    cat >> "${profile_file}" <<EOF

# ${cluster_name} CONFIG START
# use k8s ${cluster_name} env
function a-${cluster_name}() { ka ${cluster_name}; }
# ${cluster_name} CONFIG END
EOF

    echo "All done."
    echo "Please execute following command manually:"
    echo "  source ${profile_file}"
}

# kubectl activate
function ka() {
    export CURRENT_KUBE_ENV=$1
    export KUBECONFIG="${HOME}/.kube/kubeconfig-${CURRENT_KUBE_ENV}"
    alias k9s="k9s --kubeconfig=${KUBECONFIG}"
    kc get nodes
}

# kubectl de-activate
function d-ka() {
    unset CURRENT_KUBE_ENV
    unset KUBECONFIG
}

# prompt 信息函数
function kube_prompt_info() {
    local kube_env=${CURRENT_KUBE_ENV:-}
    if [[ -z "$kube_env" ]]; then
        return
    fi

    local blue_color="\033[34m"
    local red_color="\033[31m"
    local reset_color="\033[0m"

    echo -e " ☸️ ${blue_color}K8S:(${red_color}${kube_env}${blue_color})${reset_color} "
}

# 修改 Bash 提示符
if [[ $PS1 != *'$(kube_prompt_info)'* ]]; then
    PS1="${PS1}\$(kube_prompt_info)"
fi