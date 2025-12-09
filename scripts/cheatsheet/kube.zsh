# 命令行切换多个k8s集群(zsh版本)

alias k='kubectl'
alias kc='kubecolor'

source <(kubectl completion zsh)

compdef k=kubectl
compdef kc=kubectl
compdef kubecolor=kubectl

# 设置语言，如果是 zh_CN.UTF-8 k9s 边框会“断裂”
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

# add kubeconfig
function add-kube() {
    set -u
    kubeconfig_file=$1
    cluster_name=$2

    profile_file="${HOME}/.kube.zsh"
    mkdir -p ${HOME}/.kube

    echo "Copy kubeconfig: ${kubeconfig_file} -> ~/.kube/kubeconfig-${cluster_name}"
    cp -fv ${kubeconfig_file} ~/.kube/kubeconfig-${cluster_name}

    echo "Add a-${cluster_name} function(for activate kubeconfig) to ${profile_file} "
    sed -i '' "/${cluster_name} CONFIG START/,/${cluster_name} CONFIG END/d" ${profile_file}
    cat >> ${profile_file} <<EOF

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

    blue_color="%F{blue}"   # 加粗蓝色, 未加粗，使用 %f 可以重置颜色
    red_color="%B%F{red}"     # 加粗红色
    reset_color="%f%b"        # 重置颜色 + 重置加粗

    echo " %{☸️%} ${blue_color}K8S:(%f${red_color}${kube_env}${reset_color}${blue_color})%f "
}


if [[ $PROMPT != *'$(kube_prompt_info)'* ]]; then
    PROMPT="${PROMPT}\$(kube_prompt_info)"
fi
