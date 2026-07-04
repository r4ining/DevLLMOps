from flask import Flask, request, jsonify
import json
import requests
import logging
import os
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import unquote_plus

app = Flask(__name__)

# office 飞书机器人 Webhook 地址 -- 如果没指定，默认使用
webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/4d3fb56d-d2b3-4d47-b974-0469bab08ffb"

# 日志配置：带上海时区时间戳
_sh_tz = ZoneInfo("Asia/Shanghai")

class _ShanghaiFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, tz=_sh_tz)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.strftime("%Y-%m-%d %H:%M:%S")

_handler = logging.StreamHandler()
_handler.setFormatter(_ShanghaiFormatter("[%(asctime)s] [%(levelname)s] [%(threadName)s] %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[_handler])

# === 告警聚合配置（可通过环境变量覆盖） ===
# 收到某个 alertname 的第一条告警后，固定等待该时长（秒）再统一发送，用于合并短时间内的同名告警，避免告警风暴
DEBOUNCE_SECONDS = float(os.environ.get("ALERT_DEBOUNCE_SECONDS", "10"))
# 单条飞书卡片消息最多聚合展示多少条告警明细，超出部分会拆分成多条消息依次发送
MAX_MERGE_COUNT = int(os.environ.get("ALERT_MAX_MERGE_COUNT", "25"))

# 内存态缓冲区：key = (webhook, alertname, status) -> {"first_seen": ts, "alerts": [alert, ...]}
# 注意：该方案假设服务以单进程单副本运行（当前 Deployment replicas=1，且用 `python app.py` 单进程启动）。
# 若未来改为多副本或多 worker 部署，需要把缓冲区迁移到 Redis 等外部共享存储，否则聚合会失效。
_alert_buffer = {}
_buffer_lock = threading.Lock()

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
        alerts = alert_response.get("alerts", [])
        logging.info("收到 Alertmanager 请求，共 %d 条告警，原始消息体: %s",
                     len(alerts), json.dumps(alert_response, ensure_ascii=False))

        if not alerts:
            logging.info("请求中无告警，跳过处理")
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
            logging.info("未指定 webhook 参数，使用默认 webhook: %s", webhook)
        else:
            logging.info("使用请求指定的 webhook: %s", webhook)

        buffered = 0
        for alert in alerts:
            status = alert.get("status", "firing")
            if status not in ("firing", "resolved"):
                logging.warning("跳过未知状态的告警 status=%s, alert=%s",
                                status, json.dumps(alert, ensure_ascii=False))
                continue

            alert_name = alert.get("labels", {}).get("alertname", "Unknown")
            instance = alert.get("labels", {}).get("instance", "Unknown")
            key = (webhook, alert_name, status)
            with _buffer_lock:
                group = _alert_buffer.get(key)
                if group is None:
                    group = {"first_seen": time.time(), "alerts": []}
                    _alert_buffer[key] = group
                    logging.info("创建新的告警聚合分组 alertname=%s status=%s instance=%s，将在 %.0fs 后发送",
                                 alert_name, status, instance, DEBOUNCE_SECONDS)
                else:
                    logging.info("告警追加到已有分组 alertname=%s status=%s instance=%s，当前分组累计 %d 条",
                                 alert_name, status, instance, len(group["alerts"]) + 1)
                group["alerts"].append(alert)
            buffered += 1

        logging.info("本次请求缓冲完成，共 %d 条告警已入队，当前缓冲区分组数: %d", buffered, len(_alert_buffer))
        return f"accepted, {buffered} alert(s) queued for aggregation", 202

    except Exception as e:
        logging.exception("处理告警异常")
        return f"error: {str(e)}", 500


def _flush_loop():
    """后台线程：定期扫描缓冲区，把超过 DEBOUNCE_SECONDS 未再更新的分组取出并发送。"""
    while True:
        time.sleep(1)
        ready_groups = []
        now = time.time()
        with _buffer_lock:
            pending_count = len(_alert_buffer)
            for key in list(_alert_buffer.keys()):
                group = _alert_buffer[key]
                elapsed = now - group["first_seen"]
                if elapsed >= DEBOUNCE_SECONDS:
                    ready_groups.append((key, group))
                    del _alert_buffer[key]
                    logging.info("分组到期触发发送 alertname=%s status=%s 累计%d条 已等待%.1fs",
                                 key[1], key[2], len(group["alerts"]), elapsed)

        if ready_groups:
            logging.info("本次扫描发现 %d 个到期分组待发送，剩余缓冲区分组数: %d",
                         len(ready_groups), pending_count - len(ready_groups))

        for key, group in ready_groups:
            try:
                _dispatch_group(key, group["alerts"])
            except Exception:
                logging.exception("发送聚合告警分组异常: key=%s", key)


def _dispatch_group(key, alerts):
    """把一个分组内的告警发送出去：单条走原始格式，多条按 MAX_MERGE_COUNT 切片走合并格式。"""
    webhook, alert_name, status = key
    total = len(alerts)

    logging.info("开始处理分组 alertname=%s status=%s 共%d条 webhook=%s",
                 alert_name, status, total, webhook)

    if total == 1:
        alert = alerts[0]
        instance = alert.get("labels", {}).get("instance", "Unknown")
        logging.info("分组仅1条告警，使用单条卡片格式发送 alertname=%s instance=%s status=%s",
                     alert_name, instance, status)
        if status == "firing":
            msg_json = format_alert_to_feishu(alert)
        else:
            msg_json = format_resolved_to_feishu(alert)
        response = send_alert(msg_json, webhook)
        logging.info("单条告警发送完成 alertname=%s instance=%s status=%s 结果=%s",
                     alert_name, instance, status, "成功" if response else "失败")
        return

    chunks = [alerts[i:i + MAX_MERGE_COUNT] for i in range(0, total, MAX_MERGE_COUNT)]
    total_parts = len(chunks)
    logging.info("分组含%d条告警，按MAX_MERGE_COUNT=%d拆分为%d片依次发送",
                 total, MAX_MERGE_COUNT, total_parts)

    for part_index, chunk in enumerate(chunks, start=1):
        start_index = (part_index - 1) * MAX_MERGE_COUNT
        chunk_instances = [a.get("labels", {}).get("instance", "Unknown") for a in chunk]
        logging.info("准备发送第%d/%d片，包含%d条告警，实例列表: %s",
                     part_index, total_parts, len(chunk), chunk_instances)
        msg_json = format_merged_alerts_to_feishu(
            chunk, status, alert_name, total, part_index, total_parts, start_index
        )
        response = send_alert(msg_json, webhook)
        logging.info("聚合分片发送完成 alertname=%s status=%s 第%d/%d片 结果=%s",
                     alert_name, status, part_index, total_parts, "成功" if response else "失败")

    logging.info("分组全部发送完毕 alertname=%s status=%s 共%d条 %d片",
                 alert_name, status, total, total_parts)

def send_alert(json_data, webhook=None):
    target = webhook or webhook_url
    try:
        logging.info("正在发送飞书消息到 webhook=%s", target)
        response = requests.post(target, json=json.loads(json_data), timeout=5)
        response.raise_for_status()
        logging.info("发送飞书成功，状态码: %s", response.status_code)
        return response
    except requests.exceptions.RequestException as e:
        logging.error("发送飞书失败，webhook=%s 错误: %s", target, e)
        return None

def format_alert_to_feishu(alert):
    labels = alert.get("labels", {})
    annotations = alert.get("annotations", {})

    alert_name = labels.get("alertname", "Unknown")
    instance = labels.get("instance", "Unknown")
    severity = labels.get("severity", "N/A")
    sev_color = _SEVERITY_COLORS.get(severity.lower(), "grey")
    summary = annotations.get("summary", "")
    description = annotations.get("description", "无描述")
    start_time = format_time(alert.get("startsAt", "Unknown"))

    main_lines = [
        f"**告警名称**：{alert_name}",
        f"**告警实例**：<font color='blue'>{instance}</font>",
        f"**告警级别**：<font color='{sev_color}'>{severity}</font>",
    ]
    if summary:
        main_lines.append(f"**告警摘要**：{summary}")
    main_lines.append(f"**告警描述**：{description}")

    elements = [
        {"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(main_lines)}},
        {"tag": "hr"},
        {"tag": "note", "elements": [{"tag": "plain_text", "content": f"告警触发时间：{start_time}"}]},
    ]

    webhook_msg = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": "===== == 告警 == ====="},
                "template": "red"
            },
            "elements": elements
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

    main_lines = [
        f"**告警名称**：{alert_name}",
        f"**告警实例**：<font color='blue'>{instance}</font>",
    ]
    if summary:
        main_lines.append(f"**告警摘要**：{summary}")
    main_lines.append(f"**告警描述**：{description}")

    elements = [
        {"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(main_lines)}},
        {"tag": "hr"},
        {"tag": "note", "elements": [{"tag": "plain_text", "content": f"告警恢复说明：{success_msg} ｜ 告警恢复时间：{end_time}"}]},
    ]

    webhook_msg = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": "===== == 恢复 == ====="},
                "template": "green"
            },
            "elements": elements
        }
    }
    return json.dumps(webhook_msg, ensure_ascii=False)

def _indent_multiline(text, first_prefix="　", cont_prefix="　　"):
    """对多行文本统一缩进，第一行用 first_prefix，后续行用 cont_prefix，避免描述中的换行打乱排版。"""
    text_lines = text.split("\n")
    result = [first_prefix + text_lines[0]] if text_lines else []
    for tl in text_lines[1:]:
        result.append(cont_prefix + tl.strip())
    return "\n".join(result)


_SEVERITY_COLORS = {
    "critical": "red",
    "high": "red",
    "warning": "orange",
    "info": "blue",
    "low": "grey",
}


def format_merged_alerts_to_feishu(alerts, status, alert_name, total, part_index, total_parts, start_index):
    """把同一 alertname 分组内的多条告警合并成一张飞书卡片。
    每条告警用 div 展示主体内容，note 展示时间等次要信息，hr 做分割线。"""
    is_firing = status == "firing"

    title = "===== == 告警 == =====" if is_firing else "===== == 恢复 == ====="

    part_suffix = f"（第{part_index}/{total_parts}片）" if total_parts > 1 else ""
    header_content = "\n".join([
        f"**告警名称**：{alert_name}",
        f"**告警{'触发' if is_firing else '恢复'}数量**：共{total}条(按告警名称聚合){part_suffix}",
    ])

    elements = [
        {"tag": "div", "text": {"tag": "lark_md", "content": header_content}},
    ]

    for offset, alert in enumerate(alerts, start=1):
        idx = start_index + offset
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})
        instance = labels.get("instance", "Unknown")
        summary = annotations.get("summary", "")
        description = annotations.get("description", "无描述")

        if is_firing:
            severity = labels.get("severity", "N/A")
            sev_color = _SEVERITY_COLORS.get(severity.lower(), "grey")
            start_time = format_time(alert.get("startsAt", "Unknown"))

            main_lines = [
                f"<font color='black'>**#{idx}**</font>",
                f"**告警实例**：<font color='blue'>{instance}</font>",
                f"**告警级别**：<font color='{sev_color}'>{severity}</font>",
            ]
            if summary:
                main_lines.append(f"**告警摘要**：{summary}")
            main_lines.append(f"**告警描述**：{description}")

            elements.append({"tag": "hr"})
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(main_lines)}})
            elements.append({"tag": "note", "elements": [{"tag": "plain_text", "content": f"告警触发时间：{start_time}"}]})
        else:
            success_msg = annotations.get("success", "告警已恢复")
            end_time = format_time(alert.get("endsAt", "Unknown"))

            main_lines = [
                f"<font color='black'>**#{idx}**</font>",
                f"**告警实例**：<font color='blue'>{instance}</font>",
            ]
            if summary:
                main_lines.append(f"**告警摘要**：{summary}")
            main_lines.append(f"**告警描述**：{description}")

            elements.append({"tag": "hr"})
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(main_lines)}})
            elements.append({"tag": "note", "elements": [{"tag": "plain_text", "content": f"告警恢复说明：{success_msg} ｜ 告警恢复时间：{end_time}"}]})

    webhook_msg = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "red" if is_firing else "green"
            },
            "elements": elements
        }
    }
    return json.dumps(webhook_msg, ensure_ascii=False)


_flush_thread = threading.Thread(target=_flush_loop, daemon=True)
_flush_thread.start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=4000)
