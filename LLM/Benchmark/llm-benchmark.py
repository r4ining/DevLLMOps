import ast
import os
import logging
import subprocess
import time
import requests
import sys
import argparse
import yaml
import shlex
from datetime import datetime
from openpyxl import Workbook
from evalscope.perf.main import run_perf_benchmark
from evalscope.perf.arguments import Arguments


def get_logger(level=logging.INFO):
    # 创建logger实例
    logger = logging.getLogger("LLM-Benchmark")
    logger.setLevel(level)
    logger.propagate = False

    if not logger.handlers:
        # 创建控制台处理器
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        # 创建格式化器
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        console_handler.setFormatter(formatter)
        # 添加处理器到logger
        logger.addHandler(console_handler)

    return logger


logger = get_logger(logging.INFO)


class BenchmarkRunner:
    def __init__(self, config_path):
        self.config = self.load_config(config_path)
        if self.config is None:
            raise ValueError("配置加载失败，程序退出。")
        self.timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.result_file = f"{self.config['result_dir']}/{self.config['result_file_prefix']}-{self.timestamp}.xlsx"

    def load_config(self, file_path):
        """加载 YAML 配置文件，并解析元组字符串"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                conf = yaml.safe_load(f)
            # 转换字符串元组为实际 tuple
            test_case = conf.get('test_case', {})
            context = [ast.literal_eval(c) for c in test_case.get('context', [])]
            batch_request = [ast.literal_eval(b) for b in test_case.get('batch_request', [])]
            conf['test_case']['context'] = context
            conf['test_case']['batch_request'] = batch_request
            return conf
        except FileNotFoundError:
            logger.error(f"配置文件不存在: {file_path}")
        except yaml.YAMLError as e:
            logger.error(f"YAML 解析错误: {e}")
        except Exception as e:
            logger.error(f"加载配置时发生未知错误: {e}")
        return None

    def generate_test_cases(self):
        """根据 mode 生成测试用例"""
        mode = self.config['test_case']['mode']
        context = self.config['test_case']['context']
        batch_request = self.config['test_case']['batch_request']
        if mode == 1:
            return [(ctx, br) for ctx in context for br in batch_request]
        elif mode == 2:
            if len(context) != len(batch_request):
                logger.error("mode=2 时 context 与 batch_request 长度必须一致")
                return []
            return list(zip(context, batch_request))
        else:
            logger.error(f"不支持的测试模式: {mode}")
            return []

    def restart_local_container(self):
        """重启本机 Docker 容器"""
        container = self.config['container_name']
        # 从配置文件获取重启命令
        restart_cmd_template = self.config.get('restart_cmd', 'docker restart {container_name}')
        cmd = restart_cmd_template.format(container_name=shlex.quote(container))
        logger.info(f"🔄 重启本机容器: {container}")
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                logger.info("✅ 本机容器重启成功")
                return True
            else:
                logger.error(f"❌ 本机重启失败: {result.stderr.strip()}")
                return False
        except subprocess.TimeoutExpired:
            logger.error("❌ 本机重启超时")
            return False
        except Exception as e:
            logger.error(f"❌ 本机重启异常: {e}")
            return False

    def restart_remote_container(self, host):
        """通过 SSH 重启远程主机上的容器（需免密登录）"""
        ip = host['ip']
        user = host['user']
        port = host.get('port', 22)
        container = self.config['container_name']

        # 判断是否为本地地址
        if ip in ['localhost', '127.0.0.1']:
            return self.restart_local_container()

        # 从配置文件获取重启命令
        restart_cmd_template = self.config.get('restart_cmd', 'docker restart {container_name}')
        remote_cmd = restart_cmd_template.format(container_name=shlex.quote(container))
        # 从配置文件获取SSH命令模板
        ssh_cmd_template = self.config.get('ssh_cmd',
                                           'ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 -p {port} {user}@{ip} {cmd}')
        # 构建完整的SSH命令
        ssh_cmd_full = ssh_cmd_template.format(port=port, user=user, ip=ip, cmd=remote_cmd)

        # 将命令分割成列表形式供subprocess使用
        ssh_cmd_list = shlex.split(ssh_cmd_full)
        logger.info(f"🔄 通过 SSH 重启远程容器 ({container}) {user}@{ip}:{port}")
        try:
            result = subprocess.run(ssh_cmd_list, capture_output=True, text=True, timeout=60)
            if result.returncode == 0:
                logger.info("✅ 远程容器重启成功")
                return True
            else:
                logger.error(f"❌ 远程重启失败 ({ip}): {result.stderr.strip()}")
                return False
        except subprocess.TimeoutExpired:
            logger.error(f"❌ 远程重启超时 ({ip})")
            return False
        except Exception as e:
            logger.error(f"❌ 远程重启异常 ({ip}): {e}")
            return False

    def restart_model_service(self):
        """重启所有节点（本地 + 远程）上的模型容器"""
        hosts = self.config.get('hosts', [])
        if not hosts:
            logger.warning("未配置 hosts，仅尝试重启本机容器")
            return self.restart_local_container()

        success = True
        # 重启所有远程节点（包括第一个，即 master）
        for i, host in enumerate(hosts, 1):
            logger.info(f"🔄 重启进度: {i}/{len(hosts)} - 正在重启 {host['ip']}")
            if not self.restart_remote_container(host):
                success = False

        logger.info("✅ 所有节点重启完成" if success else "⚠️ 节点重启已完成，但部分节点失败")
        return success

    def health_check(self):
        """健康检查：仅对主节点（第一个 host 或本机）发起请求"""
        url = self.config['url']
        logger.info(f"对 {url} 执行健康检查...")

        logger.info(f"⏳模型启动时间较长，{self.config['healthcheck']['initial_delay']}s后开始第一次检查")
        time.sleep(self.config['healthcheck']['initial_delay'])
        headers = {"Content-Type": "application/json"}
        data = {
            "model": self.config['model_name'],
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 3,
            "temperature": 0.6,
            "top_p": 0.95,
            "stream": False
        }

        for i in range(self.config['healthcheck']['retry_count']):
            try:
                resp = requests.post(url, json=data, headers=headers, timeout=10)
                if resp.status_code == 200:
                    logger.info("✅ 健康检查通过")
                    return True
                else:
                    logger.warning(f"健康检查失败（状态码 {resp.status_code}），{self.config['healthcheck']['interval']}s 后重试")
            except requests.RequestException as e:
                logger.warning(f"健康检查异常: {e}，{self.config['healthcheck']['interval']}s 后重试")
            time.sleep(self.config['healthcheck']['interval'])

        logger.error("❌ 健康检查超时失败")
        return False

    def run_single_benchmark(self, context, batch_req):
        input_tokens, output_tokens = context
        batch_size, request_count = batch_req
        logger.info(f"▶ 测试: in={input_tokens}, out={output_tokens}, concurrency={batch_size}, requests={request_count}")

        bench_args = Arguments(
            parallel=[batch_size],
            number=[request_count],
            model=self.config['model_name'],
            url=self.config['url'],
            tokenizer_path=self.config['tokenizer_path'],
            api='openai',
            dataset=self.config['dataset'],
            min_tokens=output_tokens,
            max_tokens=output_tokens,
            min_prompt_length=input_tokens,
            max_prompt_length=input_tokens,
            debug=False,
            extra_args={'ignore_eos': True}
        )

        try:
            result = run_perf_benchmark(bench_args)
            return self.parse_benchmark_result(result[0])
        except SystemExit as e:
            logger.error(f"基准测试异常退出 (code={e.code})")
            return None
        except Exception as e:
            logger.error(f"基准测试执行失败: {e}")
            return None

    def parse_benchmark_result(self, result):
        comment = ""
        failed = int(result.get("Failed requests", 0))
        if failed > 0:
            comment = f"失败请求数: {failed}/{result.get('Total requests', 'N/A')}"
        return {
            "ttft": result.get("Average time to first token (s)"),
            "tpot": result.get("Average time per output token (s)"),
            "throughput": result.get("Total token throughput (tok/s)"),
            "duration": result.get("Time taken for tests (s)"),
            "comment": comment
        }

    def create_workbook(self):
        wb = Workbook()
        ws = wb.active
        ws.title = "基准测试结果"
        headers = ["输入Token数", "输出Token数", "并发数", "请求数", "TTFT(s)", "TPOT(s)", "吞吐(tokens/s)", "持续时间(s)", "备注"]
        ws.append(headers)
        return wb, ws

    def save_result(self, ws, wb, context, batch_req, result):
        if result is None:
            logger.warning("结果为空，跳过保存")
            return
        row = [
            context[0], context[1],
            batch_req[0], batch_req[1],
            result["ttft"], result["tpot"],
            result["throughput"], result["duration"],
            result["comment"]
        ]
        ws.append(row)
        os.makedirs(os.path.dirname(self.result_file), exist_ok=True)
        wb.save(self.result_file)
        logger.info(f"💾 结果已保存: {self.result_file}")

    def run_benchmarks(self):
        test_cases = self.generate_test_cases()
        if not test_cases:
            logger.error("未生成有效测试用例")
            return

        logger.info(f"共 {len(test_cases)} 个测试用例")
        wb, ws = self.create_workbook()

        for i, (context, batch_req) in enumerate(test_cases, 1):
            logger.info(f"_PROGRESS_ {i}/{len(test_cases)}")

            if self.config.get('restart_model', False):
                if not self.restart_model_service() or not self.health_check():
                    logger.error("服务重启或健康检查失败，跳过当前测试")
                    # 仍保存一条空结果（可选）
                    self.save_result(ws, wb, context, batch_req, None)
                    continue

            result = self.run_single_benchmark(context, batch_req)
            self.save_result(ws, wb, context, batch_req, result)

        logger.info("🎉 所有测试完成！")


def main():
    parser = argparse.ArgumentParser(description='自动化 LLM 测试工具')
    parser.add_argument('-c', '--config', type=str, default='config.yaml', help='配置文件路径')
    args = parser.parse_args()

    try:
        runner = BenchmarkRunner(args.config)
        runner.run_benchmarks()
    except KeyboardInterrupt:
        logger.info("用户中断执行")
    except Exception as e:
        logger.error(f"程序异常退出: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()