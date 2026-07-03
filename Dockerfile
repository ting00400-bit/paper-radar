# paper-radar NAS cron 執行環境：Node 22（wrangler）+ Python 3（pipeline）。
# 用法：DSM 任務排程表以 `docker run --rm -v <專案>:/app -w /app paper-radar bash run.sh` 呼叫。
FROM node:22-bookworm-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g wrangler
ENV TZ=Asia/Taipei
WORKDIR /app
CMD ["bash", "run.sh"]
