# 进阶功能验证记录

验证日期：2026-09-13。这里只记录本次实际执行的检查。

| 检查 | 结果 |
| --- | --- |
| 本地全量 pytest | 213 passed、4 skipped；38 条上游弃用警告 |
| Ruff 检查与格式 | 通过 |
| Pyrefly | 0 errors |
| Markdown 全量检查 | 通过 |
| Compose 完整叠加配置解析 | 通过；未启动容器 |
| 五条离线检索评测 | recall@3 = 1.0，仅限这个教学集合 |
| 百炼真实规划 | 返回 3 天计划，error=null |
| 真实规划中的本地知识库 | status=ok，输出参考证据 |
| 缺少高德密钥的真实降级 | weather=unavailable，规划仍成功 |
| 五路节点实际并发 | 屏障测试通过 |
| 配额错误不重试、5xx 重试、缓存隔离 | Mock HTTP 测试通过 |
| 异步任务图的进度写入与结果 | Mock Redis 测试通过 |

## 尚未完成的真实集成验证

本机未配置高德 Key、MCP URL、embedding 模型、CrossEncoder 模型、LangSmith Key，因此没有声称这些外部调用成功。Celery、Redis、Prometheus、Grafana 已有代码和部署配置，但尚未在本次会话中启动完整容器栈验证。

服务器实测总内存约 1613 MiB，可用约 281 MiB，已有四个运行中的业务容器。未在该机器上强行部署完整新增栈。本机 Docker daemon 未启动，Compose 仅验证了配置结构。

本次 GitHub 同步更新源码、依赖锁、测试、CI 与文档。旧的服务器运行镜像不会因 GitHub 推送自动更新。

继续真实集成前，应在 `.env` 或 `.env.deploy` 私下配置所需服务凭据，在资源足够的机器启动进阶 Compose，再验证任务提交、SSE、结果查询、Prometheus targets 和 Grafana 面板。不要将这一页的离线测试结果写成线上性能指标。
