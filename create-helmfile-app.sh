#!/bin/bash

set -e

CHART_DIR="charts/$1"
APPNAME="$(basename ${CHART_DIR})"
NAMESPACE="${2:-${APPNAME}}"
APP_VERSION=$(awk '/appVersion: / {print $2}' ${CHART_DIR}/Chart.yaml)

function log {
    echo -e "[$(date +'%F %T')] \033[36m$@\033[0m"
}


log "Create release file for ${APPNAME}"
cat > helmfile/releases/${APPNAME}.yaml <<EOF
bases:
- ../envs/environments.yaml
---
releases:
- chart: ../../${CHART_DIR}
  version: ${APP_VERSION}
  wait: true
  installed: true
  name: ${APPNAME}
  namespace: ${NAMESPACE}
  skipDeps: true
  labels:
    app: ${APPNAME}
  values:
  - ../values/${APPNAME}.yaml.gotmpl
EOF


log "Create value file for ${APPNAME}"
cp -fv ${CHART_DIR}/values.yaml helmfile/values/${APPNAME}.yaml.gotmpl

log "----------------------"
log "Image list for ${APPNAME}:"
helmfile -f ./helmfile/releases/${APPNAME}.yaml template | grep "image:" | awk '{print $NF}' | tr -d '\"' | sort -u

