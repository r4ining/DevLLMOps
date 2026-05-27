from flask import Flask, request, jsonify
import json
import requests
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import unquote_plus

app = Flask(__name__)

# office 飞书机器人 Webhook 地址 -- 如果没指定，默认使用
webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/e50c3a87-aa68-4ff0-9afe-b8a979cc4990"

# 日志配置
logging.basicConfig(level=logging.INFO)

def format_time(timestr):
    """把 2025-08-08T06:55:43.825666166Z → 2025-08-08 06:55:43"""
    try:
        dt = datetime.fromisoformat(timestr.replace("Z", "+00:00"))
        sh = dt.astimezone(ZoneInfo("Asia/Shanghai"))
        return sh.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return timestr

# === 新增健康检查路由 ===
@app.route('/health')
def health():
    return jsonify(status="ok"), 200

@app.route('/alert', methods=['POST'])
def receive_alert():
    try:
        alert_response = request.json
        logging.info("收到 Alertmanager 消息体: %s", json.dumps(alert_response, ensure_ascii=False))

        alerts = alert_response.get("alerts", [])
        if not alerts:
            logging.info("没有告警")
            return "no alerts", 200

        # 优先读取 query 参数中的 webhook：
        # 1) 如果请求包含 `webhook` 参数则使用它
        # 2) 否则如果 raw query string 是以 http/https 开头的 URL，则使用解码后的 raw query string
        # 3) 否则回退到全局配置的 `webhook_url`
        qs = request.query_string.decode('utf-8') if request.query_string else ''
        webhook = None
        if request.args.get('webhook'):
            webhook = request.args.get('webhook')
        elif qs:
            decoded = unquote_plus(qs)
            if decoded.startswith('http://') or decoded.startswith('https://'):
                webhook = decoded
            else:
                # 如果以常规 key=value 形式传参，则取第一个参数值
                vals = list(request.args.values())
                if vals:
                    webhook = vals[0]

        if not webhook:
            webhook = webhook_url

        send_status = []
        for alert in alerts:
            status = alert.get("status", "firing")
            if status == "firing":
                msg_json = format_alert_to_feishu(alert)
            elif status == "resolved":
                msg_json = format_resolved_to_feishu(alert)
            else:
                logging.info("未知状态: %s", status)
                continue

            logging.info("生成飞书消息体: %s", msg_json)
            response = send_alert(msg_json, webhook)
            if response is None:
                send_status.append("发送失败")
            else:
                send_status.append(f"发送成功:{response.status_code}")

        return "; ".join(send_status), 200

    except Exception as e:
        logging.exception("处理告警异常")
        return f"error: {str(e)}", 500

def send_alert(json_data, webhook=None):
    try:
        target = webhook or webhook_url
        response = requests.post(target, json=json.loads(json_data), timeout=5)
        response.raise_for_status()
        logging.info("发送飞书成功，状态码: %s", response.status_code)
        return response
    except requests.exceptions.RequestException as e:
        logging.error("发送飞书失败: %s", e)
        return None

def format_alert_to_feishu(alert):
    labels = alert.get("labels", {})
    annotations = alert.get("annotations", {})

    alert_name = labels.get("alertname", "Unknown")
    instance = labels.get("instance", "Unknown")
    severity = labels.get("severity", "N/A")
    summary = annotations.get("summary", "")
    description = annotations.get("description", "无描述")
    start_time = format_time(alert.get("startsAt", "Unknown"))

    lines = [
        f"**告警名称**：{alert_name}",
        f"**告警实例**：{instance}",
        f"**告警级别**：{severity}",
    ]
    if summary:
        lines.append(f"**告警摘要**：{summary}")
    lines.append(f"**告警描述**：{description}")
    lines.append(f"**触发时间**：{start_time}")

    content = "\n".join(lines)

    webhook_msg = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": "===== == 告警 == ====="},
                "template": "red"
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": content}}
            ]
        }
    }
    return json.dumps(webhook_msg, ensure_ascii=False)

def format_resolved_to_feishu(alert):
    labels = alert.get("labels", {})
    annotations = alert.get("annotations", {})

    alert_name = labels.get("alertname", "Unknown")
    instance = labels.get("instance", "Unknown")
    summary = annotations.get("summary", "")
    success_msg = annotations.get("success", "告警已恢复")
    description = annotations.get("description", "无描述")
    end_time = format_time(alert.get("endsAt", "Unknown"))

    lines = [
        f"**告警名称**：{alert_name}",
        f"**告警实例**：{instance}",
    ]
    if summary:
        lines.append(f"**告警摘要**：{summary}")
    lines.append(f"**告警描述**：{description}")
    lines.append(f"**恢复说明**：{success_msg}")
    lines.append(f"**恢复时间**：{end_time}")

    content = "\n".join(lines)

    webhook_msg = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": "===== == 恢复 == ====="},
                "template": "green"
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": content}}
            ]
        }
    }
    return json.dumps(webhook_msg, ensure_ascii=False)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=4000)
