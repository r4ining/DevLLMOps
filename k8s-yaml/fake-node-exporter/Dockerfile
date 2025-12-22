FROM swr.cn-east-3.myhuaweicloud.com/r4in/python:3.11-slim-bookworm-all

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY . .
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

ENV MOCK_CONFIG_PATH=/app/config.yaml

CMD ["python", "fake-node-exporter.py"]
