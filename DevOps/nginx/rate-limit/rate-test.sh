#!/bin/bash
# ==================== Nginx 限流验证脚本 (Curl) ====================

#set -x

URL="http://127.0.0.1:88/hello"
TOKEN_10="sk-wQPmSTMEpNdysBV2Xb6H0v9yTUeonskIrgYLQc7UGb4hPbOR"

echo "=== 测试 sk-111 (10r/s 分组) ==="
for i in {1..25}; do
    #RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN_10" $URL)
    echo "请求 $i:"
    curl -H "Authorization: Bearer $TOKEN_10" $URL
done
