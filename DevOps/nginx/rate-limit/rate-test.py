#!/usr/bin/env python3
"""并发压测模型接口，重点观察速率限制（429）表现。"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import statistics
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass
class CaseResult:
	status_code: int
	latency_s: float
	ok: bool
	error: str = ""


def percentile(values: list[float], p: float) -> float:
	if not values:
		return 0.0
	if p <= 0:
		return min(values)
	if p >= 100:
		return max(values)
	sorted_vals = sorted(values)
	idx = (len(sorted_vals) - 1) * (p / 100.0)
	low = int(idx)
	high = min(low + 1, len(sorted_vals) - 1)
	frac = idx - low
	return sorted_vals[low] * (1 - frac) + sorted_vals[high] * frac


def build_payload(model: str, prompt: str) -> dict[str, Any]:
	return {
		"model": model,
		"messages": [{"role": "user", "content": prompt}],
	}


def single_request(
	url: str,
	token: str,
	payload: dict[str, Any],
	timeout: float,
	ssl_context: ssl.SSLContext | None,
) -> CaseResult:
	data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
	headers = {
		"Authorization": f"Bearer {token}",
		"Content-Type": "application/json",
	}
	req = Request(url=url, data=data, headers=headers, method="POST")

	start = time.perf_counter()
	try:
		with urlopen(req, timeout=timeout, context=ssl_context) as resp:
			_ = resp.read()
			latency_s = time.perf_counter() - start
			status_code = getattr(resp, "status", 200)
			return CaseResult(status_code=status_code, latency_s=latency_s, ok=(status_code < 400))
	except HTTPError as e:
		latency_s = time.perf_counter() - start
		body = ""
		try:
			body = e.read().decode("utf-8", errors="ignore")[:200]
		except Exception:
			pass
		return CaseResult(status_code=e.code, latency_s=latency_s, ok=False, error=body)
	except URLError as e:
		latency_s = time.perf_counter() - start
		return CaseResult(status_code=0, latency_s=latency_s, ok=False, error=str(e.reason))
	except ssl.SSLCertVerificationError as e:
		latency_s = time.perf_counter() - start
		return CaseResult(status_code=0, latency_s=latency_s, ok=False, error=f"SSL verify failed: {e}")
	except Exception as e:  # 防御性兜底，保证压测不中断
		latency_s = time.perf_counter() - start
		return CaseResult(status_code=0, latency_s=latency_s, ok=False, error=str(e))


def build_ssl_context(ca_bundle: str, insecure_skip_verify: bool) -> ssl.SSLContext:
	if insecure_skip_verify:
		return ssl._create_unverified_context()

	if ca_bundle:
		return ssl.create_default_context(cafile=ca_bundle)

	try:
		import certifi  # type: ignore

		return ssl.create_default_context(cafile=certifi.where())
	except Exception:
		return ssl.create_default_context()


def run_benchmark(
	url: str,
	token: str,
	model: str,
	prompt: str,
	total_requests: int,
	concurrency: int,
	timeout: float,
	ssl_context: ssl.SSLContext | None,
) -> list[CaseResult]:
	payload = build_payload(model=model, prompt=prompt)
	results: list[CaseResult] = []

	with ThreadPoolExecutor(max_workers=concurrency) as executor:
		futures = [
			executor.submit(single_request, url, token, payload, timeout, ssl_context)
			for _ in range(total_requests)
		]
		for fut in as_completed(futures):
			results.append(fut.result())
	return results


def print_report(results: list[CaseResult], wall_time_s: float) -> None:
	total = len(results)
	if total == 0:
		print("无结果")
		return

	counter = Counter(r.status_code for r in results)
	latencies = [r.latency_s for r in results]
	success = sum(1 for r in results if r.ok)
	too_many_requests = counter.get(429, 0)
	network_or_other_err = counter.get(0, 0)

	print("\n===== 压测结果 =====")
	print(f"总请求数: {total}")
	print(f"成功数(2xx/3xx): {success}")
	print(f"429 数量: {too_many_requests} ({too_many_requests / total:.2%})")
	print(f"网络/本地异常数: {network_or_other_err}")
	print(f"总耗时: {wall_time_s:.3f}s")
	print(f"吞吐(QPS): {total / wall_time_s:.2f}")

	print("\n状态码分布:")
	for code, cnt in sorted(counter.items(), key=lambda x: x[0]):
		print(f"  {code}: {cnt} ({cnt / total:.2%})")

	print("\n延迟统计(秒):")
	print(f"  min:  {min(latencies):.4f}")
	print(f"  avg:  {statistics.mean(latencies):.4f}")
	print(f"  p50:  {percentile(latencies, 50):.4f}")
	print(f"  p95:  {percentile(latencies, 95):.4f}")
	print(f"  p99:  {percentile(latencies, 99):.4f}")
	print(f"  max:  {max(latencies):.4f}")

	first_err = next((r for r in results if not r.ok and r.error), None)
	if first_err:
		print("\n示例错误信息(截断):")
		print(first_err.error)


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="模型并发速率限制测试脚本")
	parser.add_argument(
		"--url",
		default="https://api.shuoyao.tech/v1/chat/completions",
		help="接口地址",
	)
	parser.add_argument("--model", default="minimax-m2.5", help="模型名称")
	parser.add_argument("--prompt", default="你好，你是谁？", help="测试提示词")
	parser.add_argument("--total", type=int, default=200, help="总请求数")
	parser.add_argument("--concurrency", type=int, default=20, help="并发数")
	parser.add_argument("--timeout", type=float, default=30.0, help="单请求超时秒数")
	parser.add_argument(
		"--ca-bundle",
		default=os.getenv("SSL_CERT_FILE", ""),
		help="CA 证书文件路径，默认读取环境变量 SSL_CERT_FILE",
	)
	parser.add_argument(
		"--insecure-skip-verify",
		action="store_true",
		help="跳过 TLS 证书校验（仅调试使用，不建议生产环境）",
	)
	parser.add_argument(
		"--token",
		default=os.getenv("OPENAI_API_KEY", ""),
		help="Bearer Token；默认读取环境变量 OPENAI_API_KEY",
	)
	return parser.parse_args()


def main() -> None:
	args = parse_args()
	if not args.token:
		raise SystemExit("请提供 --token 或设置环境变量 OPENAI_API_KEY")
	if args.total <= 0 or args.concurrency <= 0:
		raise SystemExit("--total 和 --concurrency 必须 > 0")

	print("开始压测...")
	print(f"URL: {args.url}")
	print(f"Model: {args.model}")
	print(f"Total: {args.total}, Concurrency: {args.concurrency}, Timeout: {args.timeout}s")
	if args.ca_bundle:
		print(f"CA bundle: {args.ca_bundle}")
	if args.insecure_skip_verify:
		print("TLS verify: disabled (debug only)")

	ssl_context = build_ssl_context(args.ca_bundle, args.insecure_skip_verify)

	t0 = time.perf_counter()
	results = run_benchmark(
		url=args.url,
		token=args.token,
		model=args.model,
		prompt=args.prompt,
		total_requests=args.total,
		concurrency=args.concurrency,
		timeout=args.timeout,
		ssl_context=ssl_context,
	)
	wall_time_s = time.perf_counter() - t0
	print_report(results, wall_time_s)


if __name__ == "__main__":
	main()
