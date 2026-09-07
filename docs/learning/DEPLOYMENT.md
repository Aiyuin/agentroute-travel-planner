# 服务器部署与演示操作

## 部署结构

服务器地址通过 `SERVER_IP` 环境变量填写。服务器独立目录：`/opt/agentroute`。

```text
本机浏览器 localhost:18501
        │ SSH 加密隧道
        ▼
服务器 127.0.0.1:8501 → Streamlit → Docker 内网 agent_service:8080
                                               │
                                               ├─ 百炼北京 qwen-plus
                                               └─ SQLite 持久化卷
```

本机演示端口使用 18501，避开本机开发版 8501。服务器原有的 80 端口项目保持独立。

服务器 `.env.deploy` 存放百炼凭证和自动生成的服务间认证密钥，权限为 600。Streamlit 容器只接收后端地址和服务间认证密钥，不接收百炼密钥。模型凭证仅进入后端容器。

## 2026-09-07 部署验收结果

部署目录为 `/opt/agentroute`，两个容器都配置 `restart: unless-stopped` 并通过健康检查。实际验收结果如下：

| 检查项 | 结果 |
| --- | --- |
| 后端容器 | healthy；只暴露 Docker 内网 8080 |
| Streamlit 容器 | healthy；只绑定服务器 `127.0.0.1:8501` |
| API 鉴权 | 未携带服务密钥访问 `/info` 被拒绝 |
| 真实百炼多轮调用 | “杭州三天”追问预算，补充 1500 元后通过 SSE 返回完整行程 |
| 会话历史 | 同一 `thread_id` 保存四条消息 |
| 重启恢复 | 重启后仍能读取上述四条消息 |
| 密钥隔离 | Streamlit 容器没有百炼 API Key |
| SSH 隧道 | 本机 `http://127.0.0.1:18501/_stcore/health` 返回 `ok` |

重启后的瞬时资源占用：后端约 575 MiB（限制 768 MiB），前端约 51 MiB（限制 384 MiB），服务器可用内存约 474 MiB。服务器没有 swap，当前两服务可运行，但不适合直接追加 Redis、Celery、Prometheus 和 Grafana。若继续扩展，应先升级内存或把监控和任务队列移到其他机器。

## 访问远程演示

在本机终端运行并保持连接：

```bash
export SERVER_IP="your-server-ip"
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:18501:127.0.0.1:8501 root@"$SERVER_IP"
```

打开 <http://127.0.0.1:18501>。本机开发版仍在 <http://127.0.0.1:8501>，不要混淆。

隧道断开后远程服务仍会运行，只是本机无法通过该端口访问。重新执行命令即可。演示需要这台电脑能够 SSH 登录服务器。

## 服务器运维命令

服务器访问默认 Python 包源较慢，本次 Compose 构建使用清华镜像。Dockerfile 默认仍为官方包源，通过 `PACKAGE_INDEX` 参数覆盖。先从 `uv.lock` 导出固定版本和哈希，再用 `uv --no-config pip install --require-hashes` 安装；更换下载源不代表升级版本。安装阶段的 `--no-config` 避免对缺少上传时间的镜像包重新执行日期筛选，锁文件和哈希校验仍保留。

以下命令在 SSH 登录后执行：

```bash
cd /opt/agentroute
docker compose --env-file .env.deploy -f compose.deploy.yaml ps
docker compose --env-file .env.deploy -f compose.deploy.yaml logs --tail=50 agent_service
docker stats --no-stream
```

启动或更新容器：

```bash
cd /opt/agentroute
COMPOSE_PARALLEL_LIMIT=1 docker compose --env-file .env.deploy -f compose.deploy.yaml build
docker compose --env-file .env.deploy -f compose.deploy.yaml up -d --wait --wait-timeout 240
```

仅重启：

```bash
docker compose --env-file .env.deploy -f compose.deploy.yaml restart
```

停止服务但保留对话数据：

```bash
docker compose --env-file .env.deploy -f compose.deploy.yaml stop
```

不要添加 `down -v`，它会删除持久化卷。不要打印或分享完整 `docker compose config` 或 `.env.deploy`，前者会展开密钥。

## 三分钟演示

1. 选择 travel-assistant，新建会话，发送“杭州三天”。展示程序追问预算。
2. 补充“每人1500元，不含往返交通，喜欢自然风景”。展示按天行程和程序计算的费用总额。
3. 发送“改成0天，预算-100元”。展示规则校验拒绝进入规划。
4. 展示源码状态图与 tests，说明模型负责提取/生成，代码负责范围校验、路由和总额计算。

不要将模型生成的景点、价格和时间说成已经联网核实。当前版本没有地图、天气、实时票务或 RAG。接入真实工具属于下一版扩展。

## 简历表述（按真实完成情况使用）

> 基于开源 agent-service-toolkit 二次开发旅行规划助手，使用 LangGraph StateGraph 编排需求提取、参数校验、缺失追问和结构化行程生成；通过 Pydantic 与 Python 规则限制天数、预算及结果结构，由程序统一计算分类费用总额和预算差额；复用 FastAPI SSE 接口与 SQLite 检查点实现多轮对话，并补充异常、会话隔离与结果校验测试。

远程部署已经验证，可以加上 Docker Compose 部署、数据卷持久化与服务间认证。不能写成已经完成了四路多 Agent、MCP、RAG 或高并发优化。
