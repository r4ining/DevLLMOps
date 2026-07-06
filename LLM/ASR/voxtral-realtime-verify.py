"""
voxtral-realtime-verify.py — 验证 vLLM 部署的 Voxtral-Mini-4B-Realtime 模型是否可用。

模型: mistralai/Voxtral-Mini-4B-Realtime-2602
参考: https://modelscope.cn/models/mistralai/Voxtral-Mini-4B-Realtime-2602

该模型只支持 vLLM 的 Realtime WebSocket API（/v1/realtime），协议大致为：
    1. 连接 ws://host:port/v1/realtime，等待 session.created
    2. 发送 session.update 校验 model
    3. 发送 input_audio_buffer.append（base64 PCM16 @ 16kHz）分片上传音频
    4. 发送 input_audio_buffer.commit {final: true} 结束音频
    5. 接收 transcription.delta / transcription.done / error 事件

用法示例:
    # 仅检查服务是否存活、模型是否已注册（不发送音频）
    python voxtral-realtime-verify.py --host 10.10.249.5 --port 30000 --check-only

    # 用一段 wav/mp3 音频做端到端转写验证
    python voxtral-realtime-verify.py --host 10.10.249.5 --port 30000 --audio-path ./test.wav

    # 不提供音频文件时，会生成一段合成正弦波做连通性/协议验证（不代表转写准确性）

依赖:
    pip install websockets numpy soundfile scipy requests
"""

import argparse
import asyncio
import base64
import json
import sys
import time
from typing import Optional

import numpy as np

try:
    import requests
except ImportError:
    print("缺少依赖，请先执行: pip install requests", file=sys.stderr)
    sys.exit(1)

try:
    import websockets
except ImportError:
    print("缺少依赖，请先执行: pip install websockets", file=sys.stderr)
    sys.exit(1)


TARGET_SR = 16000


def load_audio_pcm16(audio_path: str) -> np.ndarray:
    """加载任意音频文件，重采样为单声道 16kHz，返回 float32 [-1, 1] 数组。"""
    import soundfile as sf

    data, sr = sf.read(audio_path, always_2d=False, dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)

    if sr != TARGET_SR:
        from scipy.signal import resample_poly
        from math import gcd

        g = gcd(sr, TARGET_SR)
        up, down = TARGET_SR // g, sr // g
        data = resample_poly(data, up, down).astype(np.float32)

    return data


def make_synthetic_audio(duration_s: float = 2.0, freq: float = 440.0) -> np.ndarray:
    """生成一段合成正弦波，仅用于连通性/协议验证，不代表真实转写效果。"""
    t = np.linspace(0, duration_s, int(TARGET_SR * duration_s), endpoint=False)
    return (0.3 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def to_pcm16_base64(audio: np.ndarray) -> str:
    pcm16 = (audio * 32767.0).astype(np.int16)
    return base64.b64encode(pcm16.tobytes()).decode("utf-8")


def check_model_registered(base_http_url: str, model: str, timeout: float = 10.0) -> bool:
    url = base_http_url.rstrip("/") + "/v1/models"
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        model_ids = [m.get("id") for m in data.get("data", [])]
        print(f"  服务端已注册模型: {model_ids}")
        if model in model_ids:
            print(f"  ✅ 目标模型 '{model}' 已注册")
            return True
        else:
            print(f"  ⚠️  目标模型 '{model}' 未在列表中找到")
            return False
    except Exception as e:
        print(f"  ❌ 查询 /v1/models 失败: {e}")
        return False


async def realtime_transcribe(
    ws_url: str,
    model: str,
    audio: np.ndarray,
    chunk_size: int = 4096,
    timeout: float = 60.0,
) -> bool:
    audio_base64 = to_pcm16_base64(audio)
    audio_bytes = base64.b64decode(audio_base64)
    total_chunks = (len(audio_bytes) + chunk_size - 1) // chunk_size

    t_start = time.perf_counter()
    t_first_delta: Optional[float] = None

    try:
        async with websockets.connect(ws_url, open_timeout=timeout) as ws:
            response = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
            if response.get("type") == "session.created":
                print(f"  ✅ Session created: {response.get('id')}")
            else:
                print(f"  ❌ 未收到 session.created，实际响应: {response}")
                return False

            await ws.send(json.dumps({"type": "session.update", "model": model}))
            await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))

            print(f"  发送 {total_chunks} 个音频分片...")
            for i in range(0, len(audio_bytes), chunk_size):
                chunk = audio_bytes[i : i + chunk_size]
                await ws.send(
                    json.dumps(
                        {
                            "type": "input_audio_buffer.append",
                            "audio": base64.b64encode(chunk).decode("utf-8"),
                        }
                    )
                )

            await ws.send(json.dumps({"type": "input_audio_buffer.commit", "final": True}))
            print("  音频发送完成，等待转写结果...\n")

            print("  转写内容: ", end="", flush=True)
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                response = json.loads(raw)
                rtype = response.get("type")
                if rtype == "transcription.delta":
                    if t_first_delta is None:
                        t_first_delta = time.perf_counter()
                    print(response.get("delta", ""), end="", flush=True)
                elif rtype == "transcription.done":
                    t_end = time.perf_counter()
                    print(f"\n\n  最终转写: {response.get('text')}")
                    if response.get("usage"):
                        print(f"  Usage: {response['usage']}")
                    if t_first_delta is not None:
                        print(f"  首字延迟(TTFB): {(t_first_delta - t_start) * 1000:.0f} ms")
                    print(f"  端到端耗时: {(t_end - t_start) * 1000:.0f} ms")
                    return True
                elif rtype == "error":
                    print(f"\n  ❌ Error: {response.get('error')}")
                    return False
                else:
                    # 忽略其他事件类型（如 conversation.item.created 等）
                    pass
    except Exception as e:
        print(f"  ❌ WebSocket 会话失败: {e}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="验证 vLLM 部署的 Voxtral-Mini-4B-Realtime 模型",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--host", default="10.10.249.5", help="vLLM 服务地址")
    parser.add_argument("--port", type=int, default=30000, help="vLLM 服务端口")
    parser.add_argument(
        "--model", default="voxtral-mini-4b-realtime-2602", help="模型 ID"
    )
    parser.add_argument(
        "--audio-path", default=None,
        help="用于转写测试的音频文件路径（wav/mp3 等）。不提供则使用合成正弦波仅测试连通性",
    )
    parser.add_argument(
        "--check-only", action="store_true",
        help="仅检查 /v1/models 是否已注册目标模型，不建立 realtime 会话",
    )
    parser.add_argument("--timeout", type=float, default=60.0, help="WebSocket 超时时间（秒）")
    args = parser.parse_args()

    base_http_url = f"http://{args.host}:{args.port}"
    ws_url = f"ws://{args.host}:{args.port}/v1/realtime"

    print("Voxtral-Mini-4B-Realtime 验证")
    print(f"  HTTP URL : {base_http_url}")
    print(f"  WS URL   : {ws_url}")
    print(f"  Model    : {args.model}\n")

    print("[1/2] 检查模型是否已在服务端注册...")
    registered = check_model_registered(base_http_url, args.model)

    if args.check_only:
        sys.exit(0 if registered else 1)

    print("\n[2/2] 建立 Realtime WebSocket 会话进行转写测试...")
    if args.audio_path:
        print(f"  加载音频文件: {args.audio_path}")
        try:
            audio = load_audio_pcm16(args.audio_path)
        except Exception as e:
            print(f"  ❌ 音频加载失败: {e}")
            sys.exit(1)
    else:
        print("  未提供 --audio-path，使用合成正弦波（仅验证连通性/协议，不代表转写准确性）")
        audio = make_synthetic_audio()

    ok = asyncio.run(
        realtime_transcribe(ws_url, args.model, audio, timeout=args.timeout)
    )

    print("\n" + ("=" * 50))
    if ok:
        print("✅ 验证通过：realtime 会话可正常完成转写流程")
    else:
        print("❌ 验证失败，请检查上方错误信息")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
