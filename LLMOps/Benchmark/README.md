# LLM 性能评测工具

自动化 LLM 推理性能测试工具，支持模型容器自动启停、健康检查、evalscope 压测、Excel 结果记录。

## 目录结构

```
├── llm-perf-eval.py    # 评测脚本（单文件）
├── bench-conf.yaml     # 压测配置
├── model-conf.yaml     # 模型启动配置
├── requirements.txt    # 依赖
└── README.md
```

## 环境准备

```bash
pip install pyyaml requests openpyxl

# 或

pip install -r requirements.txt
```

依赖：`pyyaml`、`requests`、`openpyxl`、`evalscope`

## 运行方式

```bash
python llm-perf-eval.py
```

默认读取脚本同目录下的 `bench-conf.yaml` 和 `model-conf.yaml`，也可手动指定：

```bash
python llm-perf-eval.py -b /path/to/bench-conf.yaml -m /path/to/model-conf.yaml
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `-b` / `--bench-config` | `bench-conf.yaml` | 压测配置文件路径 |
| `-m` / `--model-config` | `model-conf.yaml` | 模型启动配置文件路径 |

## 测试模式

### 模式1：固定测试 Case (`mode: 1`)

按照配置的 **上下文长度 × 并发数** 组合逐一测试。

**执行流程：**

1. 遍历 `model.yaml` 中每组模型启动参数
2. 拼接 `container_cmd` + `commands[N].cmd` 启动容器
3. 等待健康检查通过
4. 可选预热（`warmup: true`）
5. 遍历所有测试用例执行 evalscope 压测
6. 停止容器，进入下一组参数
7. 结果保存至 `results/<prefix>-<timestamp>.xlsx`

**Excel 输出：** 每组模型参数一个 sheet（`参数1`、`参数2`...），包含：

| 列 | 说明 |
|----|------|
| 输入上下文长度 | 输入 token 数 |
| 输出上下文长度 | 输出 token 数 |
| 并发数 | 并行请求数 |
| 请求数 | 总请求数 |
| TTFT(s) | 首 token 延迟 |
| TPOT(s) | 每 token 延迟 |
| 吞吐(tokens/s) | 总吞吐 |
| ITL(s) | token 间延迟 |
| 持续时间(s) | 测试耗时 |
| 备注 | 失败请求信息等 |

每个 sheet 末尾附完整启动命令。

### 模式2：SLO 最大并发探测 (`mode: 2`)

根据 SLO 准则（TTFT ≤ X、TPOT ≤ Y），自动搜索每个上下文长度下满足 SLO 的最大并发数。

**搜索策略：**

- **`binary`**：纯二分搜索 — 达标翻倍，不达标二分收敛
- **`stopN`**：步进搜索 — 达标 +N，不达标 -N，确定上下界后二分收敛

**Per-Context 参数覆盖（`override_args`）：**

在 `bench_only: false` 模式下，可以为每个上下文单独配置 `override_args`，在原始模型启动命令的基础上覆盖、添加或删除参数。支持三种操作：

| 格式 | 作用 | 示例 |
|------|------|------|
| `"--key value"` | 添加或覆盖带值参数 | `--chunked-prefill-size 1024` |
| `"--flag"` | 添加或覆盖布尔标志 | `--enable-mixed-chunk` |
| `"!--key"` | 删除参数（带值或布尔标志均可） | `"!--enable-mixed-chunk"` |

**行为规则：**

1. **按需重启** — 仅当某个上下文的有效参数与当前运行的参数不同时才重启模型（参数顺序不同但值相同不会触发重启）
2. **自动回退** — 如果上下文 A 有 `override_args`，上下文 B 没有，测试 B 时会自动回退到原始参数并重启
3. **Excel 记录** — 汇总表中的参数列按覆盖后的实际值记录；明细表末尾会列出各上下文的实际启动命令
4. **引擎通用** — 同时兼容 sglang（`python3 -m sglang.launch_server`）和 vllm（`vllm serve`）命令格式

**Excel 输出：**

- **汇总 sheet**：模型名称、镜像、上下文、参数序号、自动解析的模型参数列、最大达标并发、核心指标
- **参数N sheet**：该参数组所有探测记录（达标行绿色高亮）+ 完整启动命令（存在多种有效命令时分别列出）

## 配置说明

### bench-conf.yaml（压测配置）

```yaml
mode: 1                    # 1=固定测试case, 2=SLO探测

# 模型信息
model_name: "glm-5"
tokenizer_path: "ZhipuAI/GLM-5"
url: "http://localhost:30000/v1/chat/completions"
api_key: ""
dataset: "random"

# 输出
result_dir: "./results"
result_file_prefix: "glm-5"

# 健康检查
healthcheck:
  initial_delay: 120       # 启动后等待秒数
  interval: 5              # 重试间隔
  retry_count: 60          # 最大重试次数

warmup: true               # 正式测试前预热

# ---- 模式1配置 ----
test_cases:
  combination_mode: 1      # 1=交叉组合, 2=一一对应
  context:                 # (输入长度, 输出长度)
    - (1024, 1024)
    - (8192, 1024)
  batch_request:           # (并发数, 请求数)
    - (1, 5)
    - (8, 40)
    - (64, 320)

# ---- 模式2配置 ----
slo:
  criteria:
    ttft: 0.2s             # 支持 s、ms 单位
    tpot: 50ms
  search_method: stopN     # binary 或 stopN
  stop_n: 2
  init_concurrent: 3       # 默认初始并发
  max_concurrent: 128      # 最大并发限制（可选，防止异常无限增长）
  request_multiplier: 4    # 请求数 = 并发 × 倍数
  context:
    - context: (1024, 1024)
      init_concurrent: 8   # 可单独覆盖初始并发
      max_concurrent: 64   # 可单独覆盖最大并发限制
      override_args:        # 可选，覆盖模型启动参数（仅 bench_only: false）
        - --dp-size 1
        - --chunked-prefill-size 1024
        - --prefill-attention-backend fa3
        - "!--enable-mixed-chunk"   # 删除该参数
    - context: (4096, 1024)          # 无 override_args，使用原始参数
    - context: (8192, 1024)
```

### model-conf.yaml（模型启动配置）

```yaml
# 远程执行（可选，不配置则本地执行，支持多跳 SSH）
# ssh_cmd: "sshpass -p pass ssh -o StrictHostKeyChecking=no -J root@10.10.249.214:22,ubuntu@10.1.5.1 ubuntu@10.1.8.15"

# 容器启动命令（完整命令 = container_cmd + commands[N].cmd）
container_cmd: |
  docker run --gpus all -d --name model-server \
    --shm-size 32g -p 30000:30000 \
    -v /data/models:/models \
    lmsys/sglang:latest

# 容器停止命令
stop_cmd: |
  docker stop model-server && docker rm -f model-server

# 多组模型启动参数，串行测试
commands:
  - cmd: |
      python -m sglang.launch_server \
        --model-path /models/GLM-5 \
        --tp 4 \
        --disable-radix-cache
  - cmd: |
      python -m sglang.launch_server \
        --model-path /models/GLM-5 \
        --tp 4 \
        --chunked-prefill-size 4096
```

> 模式2 汇总表会自动从 `cmd` 中解析 `--key value` 参数作为动态列（如 `tp`、`chunked-prefill-size`），方便不同参数组之间横向对比。

## 远程执行

在本机运行脚本，通过 SSH 在远程服务器上启停模型容器：

1. 在 `model-conf.yaml` 中配置 `ssh_cmd`（支持 `-J` 多跳）
2. `bench-conf.yaml` 中的 `url` 填远程服务器可访问的地址
3. 健康检查和压测均从本机发起 HTTP 请求

```yaml
# model-conf.yaml
ssh_cmd: "sshpass -p pass ssh -o StrictHostKeyChecking=no -J root@10.10.249.214:22,ubuntu@10.1.5.1 ubuntu@10.1.8.15"
```

**执行流程：**
- `container_cmd` + `stop_cmd` + `docker logs` → 通过 SSH 远程执行
- 健康检查 → 本机 HTTP 请求到 `url`
- evalscope 压测 → 本机执行

不配置 `ssh_cmd` 则所有命令在本地执行，行为与之前一致。

## 示例

**模式1 — 固定用例测试：**
```bash
# bench-conf.yaml 中设置 mode: 1，配好 test_cases
python llm-perf-eval.py
# 输出: results/glm-5-20260326-180000.xlsx
```

**模式2 — SLO 并发探测：**
```bash
# bench-conf.yaml 中设置 mode: 2，配好 slo
python llm-perf-eval.py
# 输出: results/glm-5-slo-20260326-180000.xlsx
```
