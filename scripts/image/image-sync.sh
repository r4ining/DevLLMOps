#!/bin/bash

###############################################################################
# 同步镜像
# 使用:
# 同步镜像: bash image-sync.sh 
# 查看同步后镜像tag: bash image-sync.sh tags
###############################################################################

# image_file=${1:-image-list.txt}
image_file="image-list.txt"

REGISTRY="swr.cn-east-3.myhuaweicloud.com/r4in"
images=($(grep -Ev "^#|^$" ${image_file}))

function log {
    echo -e "[$(date +'%F %T')] $@"
}

function usage() {
    cat <<EOF
Usage:
    $0          # 同步镜像
    $0 tags     # 获取同步后的镜像tag
EOF
}

# 同步镜像
function img_sync() {
    log "Image sync..."

    counter=1
    image_num=${#images[@]}

    for img in ${images[@]}; do
        # 去除镜像仓库地址
        # docker.io/grafana/grafana:12.1.1 -> grafana/grafana:12.1.1
        # busybox:latest -> busybox:latest
        img_repo="$(echo ${img} | awk -F/ '{ if ($1 ~ /[.:]/ || $1 == "localhost") sub("^[^/]+/",""); print }')"
        log "[${counter}/${image_num}] ${img} -> ${REGISTRY}/${img_repo}"
        skopeo copy --all docker://${img} docker://${REGISTRY}/${img_repo}

        let counter++
    done
}

# 获取同步后的镜像tag
function img_tags() {
    log "Image tags..."
    (
        echo "Origin_Tag New_Tag"
        for img in ${images[@]}; do
            img_repo="$(echo ${img} | awk -F/ '{ if ($1 ~ /[.:]/ || $1 == "localhost") sub("^[^/]+/",""); print }')"
            echo "${img} ${REGISTRY}/${img_repo}"
        done
    ) | column -t
}

function main() {
    case $1 in
    tags)
        img_tags ;;
    -h)
        usage ;;
    *)
        img_sync ;;
    esac
}

main $@
