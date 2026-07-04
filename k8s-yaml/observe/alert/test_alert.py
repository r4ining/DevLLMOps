#!/usr/bin/env python3
"""告警发送测试脚本：支持单条和多条聚合两种模式。

用法：
  python test_alert.py                          # 进程内测试，发送单条告警
  python test_alert.py single                   # 进程内测试，发送单条告警
  python test_alert.py multi                    # 进程内测试，发送 23 条聚合告警
  python test_alert.py resolved                 # 进程内测试，发送单条恢复告警
  python test_alert.py resolved-multi           # 进程内测试，发送 23 条聚合恢复告警
  python test_alert.py multi --url http://localhost:4000       # 发送到真实服务
  python test_alert.py single --url http://alert-flask-webhook-svc.monitor.svc:4000
"""
import argparse
import sys
import time
from urllib.parse import quote

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import app as m

TEST_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/4d3fb56d-d2b3-4d47-b974-0469bab08ffb"


def build_single_alert():
    return {
        "status": "firing",
        "labels": {
            "alertname": "Kubernetes Pod 健康状态异常",
            "instance": "Unknown",
            "severity": "high",
        },
        "annotations": {
            "summary": "Kubernetes Pod not healthy (glm/gpu-glm-5-2-prefill-group5-6775545887-z9rgm)",
            "description": "Pod 状态异常超过5分钟\n  命名空间: glm\n  Pod: gpu-glm-5-2-prefill-group5-6775545887-z9rgm",
        },
        "startsAt": "2026-07-03T17:00:13.000000000Z",
    }


def build_multi_alerts(count=23):
    namespaces = ["glm", "qwen", "deepseek", "llama", "yi"]
    alerts = []
    for i in range(count):
        ns = namespaces[i % len(namespaces)]
        pod = f"gpu-{ns}-5-2-prefill-group{i}-6775545887-z{i:03d}"
        alerts.append({
            "status": "firing",
            "labels": {
                "alertname": "Kubernetes Pod 健康状态异常",
                "instance": "Unknown",
                "severity": "high",
            },
            "annotations": {
                "summary": f"Kubernetes Pod not healthy ({ns}/{pod})",
                "description": f"Pod 状态异常超过5分钟\n  命名空间: {ns}\n  Pod: {pod}",
            },
            "startsAt": "2026-07-03T17:00:13.000000000Z",
        })
    return alerts


def build_single_resolved():
    return {
        "status": "resolved",
        "labels": {
            "alertname": "Kubernetes Pod 健康状态异常",
            "instance": "Unknown",
            "severity": "high",
        },
        "annotations": {
            "summary": "Kubernetes Pod not healthy (glm/gpu-glm-5-2-prefill-group5-6775545887-z9rgm)",
            "description": "Pod 状态异常超过5分钟\n  命名空间: glm\n  Pod: gpu-glm-5-2-prefill-group5-6775545887-z9rgm",
            "success": "Pod 已恢复正常",
        },
        "startsAt": "2026-07-03T17:00:13.000000000Z",
        "endsAt": "2026-07-03T18:30:00.000000000Z",
    }


def build_multi_resolved(count=23):
    namespaces = ["glm", "qwen", "deepseek", "llama", "yi"]
    alerts = []
    for i in range(count):
        ns = namespaces[i % len(namespaces)]
        pod = f"gpu-{ns}-5-2-prefill-group{i}-6775545887-z{i:03d}"
        alerts.append({
            "status": "resolved",
            "labels": {
                "alertname": "Kubernetes Pod 健康状态异常",
                "instance": "Unknown",
                "severity": "high",
            },
            "annotations": {
                "summary": f"Kubernetes Pod not healthy ({ns}/{pod})",
                "description": f"Pod 状态异常超过5分钟\n  命名空间: {ns}\n  Pod: {pod}",
                "success": f"Pod {pod} 已恢复正常",
            },
            "startsAt": "2026-07-03T17:00:13.000000000Z",
            "endsAt": "2026-07-03T18:30:00.000000000Z",
        })
    return alerts


def send_alerts(alerts, server_url=None):
    webhook_param = quote(TEST_WEBHOOK, safe='')

    if server_url:
        import requests
        url = f"{server_url.rstrip('/')}/alert?webhook={webhook_param}"
        print(f"发送到真实服务: {url}")
        resp = requests.post(url, json={"alerts": alerts}, timeout=10)
        print("POST result:", resp.status_code, resp.text)
        print(f"等待 {m.DEBOUNCE_SECONDS + 3}s 让服务端 flush...")
        time.sleep(m.DEBOUNCE_SECONDS + 3)
    else:
        with m.app.test_client() as c:
            url = f"/alert?webhook={webhook_param}"
            resp = c.post(url, json={"alerts": alerts})
            print("POST result:", resp.status_code, resp.data)

        wait_seconds = m.DEBOUNCE_SECONDS + 3
        print(f"等待 {wait_seconds}s 让后台线程 flush...")
        time.sleep(wait_seconds)
        print("缓冲区剩余(应为空):", m._alert_buffer)


def main():
    parser = argparse.ArgumentParser(description="告警发送测试脚本")
    parser.add_argument("mode", nargs="?", default="single",
                        choices=["single", "multi", "resolved", "resolved-multi"],
                        help="测试模式：single/multi/resolved/resolved-multi，默认 single")
    parser.add_argument("--url", default=None,
                        help="真实服务地址，如 http://localhost:4000，不指定则用进程内测试")
    args = parser.parse_args()

    if args.mode == "multi":
        print("=== 发送 23 条聚合告警 ===")
        alerts = build_multi_alerts(23)
    elif args.mode == "resolved":
        print("=== 发送单条恢复告警 ===")
        alerts = [build_single_resolved()]
    elif args.mode == "resolved-multi":
        print("=== 发送 23 条聚合恢复告警 ===")
        alerts = build_multi_resolved(23)
    else:
        print("=== 发送单条告警 ===")
        alerts = [build_single_alert()]

    send_alerts(alerts, server_url=args.url)


if __name__ == "__main__":
    main()
