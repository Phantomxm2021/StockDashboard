FROM node:25-slim AS frontend-build

ARG NPM_REGISTRY=https://registry.npmmirror.com

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci --registry=${NPM_REGISTRY}
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim

ARG APT_MIRROR=https://mirrors.aliyun.com
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV STOCK_TZ=Asia/Shanghai
ENV PIP_DEFAULT_TIMEOUT=120
ENV PIP_INDEX_URL=${PIP_INDEX_URL}

WORKDIR /app

RUN if [ -n "${APT_MIRROR}" ]; then \
      sed -i "s|http://deb.debian.org|${APT_MIRROR}|g; s|http://security.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list.d/debian.sources; \
    fi

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir --no-build-isolation --retries 5 -r requirements.txt

COPY a_stock_shortlist_akshare_html.py dashboard_server.py run_job.py ./
COPY stock_dashboard ./stock_dashboard
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

RUN mkdir -p /app/data /app/output /app/reports /app/logs

EXPOSE 8001

CMD ["python", "-m", "stock_dashboard.container_entrypoint"]
