## 使用说明
### 1、安装 pip 依赖
```bash
# 安装脚本依赖
pip install requests openpyxl
# 安装 evalscope 依赖
pip install 'evalscope[perf]' -U
```

### 2、修改配置
> 需要注意：如果模型部署在远程节点并且需要每次测试之后重启模型，则需要将本机与远程节点配置免密
配置文件为`config.yaml`，配置中对应字段已有注释解释


### 3、执行脚本
```bash
# 设置文件打开限制
ulimit -n 1048576
# 执行脚本
python3 llm-benchmark.py [-c config.yaml]
```

执行时间可能比较长，根据模型、显卡、推理引擎、数据集、测试case等因素会有差异，建议放在后台执行
```bash
mkdir -p logs
python3 llm-benchmark.py -c config.yaml |& tee logs/llm-benchmark-$(date +"%y%m%d-%H%M%S").log
```

### 4、查看结果
模型的 benchmark 测试结果默认会保存到 `results/model-benchmark-{timestamp}.xlsx` 文件中

执行的 benchmark 脚本的执行结果保存在 `logs/llm-benchmark-{timestamp}.log` 文件
evalscope 本身也会输出测试日志，保存在 `outputs/{timestamp}` 目录下 
