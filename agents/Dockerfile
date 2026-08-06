FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

# 依存定義を先にcopyし、アプリ変更時も依存install layerを再利用できるようにする。
COPY requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --requirement requirements.txt \
    && groupadd --system agent \
    && useradd --system --gid agent --home-dir /nonexistent --shell /usr/sbin/nologin agent

# 実行に必要な本番コードだけを配置し、所有者を非root userへ揃える。
COPY --chown=agent:agent main.py ./main.py
COPY --chown=agent:agent src/agent_app ./src/agent_app

USER agent

EXPOSE 8080

CMD ["python", "main.py"]
