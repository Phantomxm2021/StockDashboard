# 多市场主线观察台

React + FastAPI 的多市场观察看板。系统支持 A 股、港股和美股，按市场独立生成观察池，并提供登录、用户管理、任务触发和自动调度。

## 功能概览

- 默认深色 UI。
- SQLite 本地用户库。
- 默认管理员账号初始化为 `root / admin@root`。
- 不开放注册；只有管理员可以创建用户。
- 管理员可查看策略运行状态、触发任务、管理用户。
- 普通用户只查看观察池数据。
- 左侧市场下拉框可切换 A 股、港股和美股；菜单会随市场变化。
- Docker Compose 部署包含两个服务：
  - `web`：FastAPI + React 页面。
  - `scheduler`：按市场定时执行观察任务。

## 多市场支持

系统支持三个市场：

- A股市场：收盘观察、早盘确认。
- 港股市场：收盘观察、盘前观察。
- 美股市场：盘后观察、盘前观察。

页面通过左侧市场下拉框切换市场。策略说明不显示在看板页面中，任务结果按市场独立保存到 `reports/<market>/`。

美股盘前/盘后观察使用 AKShare 做候选池初筛，再用 Alpaca Basic 的 IEX snapshot 修正扩展时段价格。需要配置 `ALPACA_API_KEY_ID` 和 `ALPACA_API_SECRET_KEY`；未配置时任务会失败并提示，不会退回到 AKShare 生成重复的伪扩展时段报告。

## 策略摘要

当前模型为“主线强势观察模型”，核心维度：

- 个股强度：成交额、涨幅、量价表现。
- 板块强度：行业板块资金流和成分股映射。
- 资金流向：个股主力资金流，龙虎榜只作为补充加分。
- 位置风险：过热涨幅、高换手、高位风险。
- 新闻催化：热度/新闻相关数据。
- 市场环境：
  - 缩量：全市场成交额低于 8001 亿，排除科创板。
  - 平量：8001 亿到 10000 亿，正常评分。
  - 放量：高于 10000 亿，创业板和科创板弹性加权。

本项目仅用于数据整理和量化研究，不构成投资建议。

## Docker 部署

前置条件：

- Docker
- Docker Compose

启动：

```bash
export ALPACA_API_KEY_ID=你的_Alpaca_Key_ID
export ALPACA_API_SECRET_KEY=你的_Alpaca_Secret_Key
docker compose up --build -d
```

`web` 容器启动时会先检查 `reports/<market>/latest_*.csv`。默认 `STOCK_BOOTSTRAP_REPORTS=missing`，只补齐缺失的数据；如果希望每次重新部署都强制重新抓取一轮，设置：

```bash
STOCK_BOOTSTRAP_REPORTS=always docker compose up --build -d
```

单个市场或单个报告抓取失败不会阻塞网站启动，失败原因会写入 `web` 容器日志。

### 中国大陆 / 阿里云构建优化

项目默认对 Docker 构建启用中国大陆可用性更好的源：

- Debian apt：`https://mirrors.aliyun.com`
- pip：`https://mirrors.aliyun.com/pypi/simple/`
- npm：`https://registry.npmmirror.com`

正常情况下直接构建即可：

```bash
docker compose build --no-cache
docker compose up -d
```

如果要切回官方源：

```bash
APT_MIRROR= PIP_INDEX_URL=https://pypi.org/simple/ NPM_REGISTRY=https://registry.npmjs.org docker compose build --no-cache
```

如果慢在拉取基础镜像 `node:25-slim` 或 `python:3.13-slim`，需要配置 Docker daemon 镜像加速。阿里云 ECS 可在容器镜像服务控制台获取专属加速地址，然后写入 `/etc/docker/daemon.json`：

```json
{
  "registry-mirrors": [
    "https://你的专属加速地址.mirror.aliyuncs.com"
  ]
}
```

重启 Docker：

```bash
sudo systemctl daemon-reload
sudo systemctl restart docker
```

访问：

```text
http://127.0.0.1:8001
```

查看日志：

```bash
docker compose logs -f web
docker compose logs -f scheduler
```

停止：

```bash
docker compose down
```

保留数据卷：

```bash
docker compose down
```

删除数据卷：

```bash
docker compose down -v
```

## 自动任务

`scheduler` 服务按北京时间运行：

- `15:05`：A股收盘观察。
- `09:40`：A股早盘确认。
- `16:15`：港股收盘观察。
- `09:22`：港股盘前观察。
- `05:15`：美股盘后观察。
- `21:00`：美股盘前观察。

调度器优先使用 AKShare 交易日历判断交易日；如果交易日历获取失败，会退回到跳过周末。

## 目录和数据

Docker Compose 使用命名卷保存运行数据：

- `/app/data`：SQLite 用户库。
- `/app/reports`：看板读取的 latest 报告。
- `/app/output`：任务输出的 CSV/HTML。
- `/app/logs`：任务日志目录。

启动抓取策略由 `STOCK_BOOTSTRAP_REPORTS` 控制：

- `missing`：默认值，只在 latest 报告缺失时抓取。
- `always`：每次容器启动都强制抓取一轮。
- `off`：关闭启动抓取。

本地开发时对应目录是：

- `data/`
- `reports/`
- `output/`
- `logs/`

报告按市场隔离：

- `reports/cn/`
- `reports/hk/`
- `reports/us/`

这些目录已加入 `.gitignore`，不会提交到仓库。

## 本地开发

Python 环境按当前项目约定使用 conda base：

```bash
source /Users/nswell/Documents/Env/Miniconda3/etc/profile.d/conda.sh
conda activate base
```

安装后端依赖：

```bash
python -m pip install -r requirements.txt
```

安装前端依赖：

```bash
cd frontend
npm install
cd ..
```

构建前端：

```bash
cd frontend
npm run build
cd ..
```

启动后端：

```bash
export ALPACA_API_KEY_ID=你的_Alpaca_Key_ID
export ALPACA_API_SECRET_KEY=你的_Alpaca_Secret_Key
PYTHONPATH=. python -m uvicorn dashboard_server:app --host 127.0.0.1 --port 8001
```

本地开发访问：

```text
http://127.0.0.1:8001
```

## 手动运行任务

A股收盘观察：

```bash
python run_job.py --market cn --report-type after_close --force
```

A股早盘确认：

```bash
python run_job.py --market cn --report-type morning --force
```

港股盘前观察：

```bash
python run_job.py --market hk --report-type pre_market --force
```

美股盘后观察：

```bash
python run_job.py --market us --report-type after_hours --force
```

美股盘前观察：

```bash
python run_job.py --market us --report-type pre_market --force
```

旧 A 股命令仍可兼容：

```bash
python run_job.py --mode after_close --force
python run_job.py --mode morning --force
```

也可以登录页面后，在“任务中心”触发。任务会后台运行，页面轮询显示状态和日志。

## 验证

后端测试：

```bash
PYTHONPATH=. python -m pytest -q
```

前端构建：

```bash
cd frontend
npm run build
```

当前环境如果没有 Docker 命令，则无法本地验证 Docker 构建；可在安装 Docker 的机器上运行：

```bash
docker compose config
docker compose up --build
```

## 安全说明

- 默认 root 密码应在首次部署后尽快更换。当前版本没有密码修改页面，可以通过删除数据卷重新初始化，或后续增加管理员修改密码功能。
- 生产部署建议设置强随机 `STOCK_AUTH_SECRET`。
- 不要将 `data/`、`reports/`、`output/`、`logs/` 提交到 Git。
