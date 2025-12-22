#!/bin/bash
set -ex

version="${1:-v0.0.1}"

docker build -t fake-node-exporter:${version} .

docker push fake-node-exporter:${version}
