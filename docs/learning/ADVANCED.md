# AgentRoute 进阶搭建与源码讲解

本文接着基础手册讲解新增组件。先跑通基础对话，再逐项打开开关。不要把“代码支持”“离线测试通过”和“真实平台调用成功”混为一谈。

## 1. 这次增加了什么

| 能力 | 入口 | 默认行为 |
| --- | --- | --- |
| 五路并行资料查询 | `src/agents/travel_assistant.py` | `TRAVEL_ENABLED=false` 时跳过 |
| 高德天气、景点、酒店与步行路线 | `src/travel/providers.py` | 缺 Key 返回不可用 |
| MCP 优先、REST 备用 | `src/travel/evidence.py` | 配置 MCP URL 后用于景点查询 |
| BM25、结构化召回、RRF | `src/travel/rag.py` | 使用自编教学知识库离线运行 |
| 向量召回 | 同上 | 配置 embedding 模型后调用百炼兼容接口 |
| Query Rewriting / HyDE | 同上 | 显式启用后增加一次模型调用 |
| CrossEncoder 精排 | 同上 | 安装可选依赖并配置模型后启用 |
| Celery、Redis 与任务进度 SSE | `src/travel/jobs.py` | 需要启动队列与 worker |
| Prometheus / Grafana | `monitoring/` | 独立 Compose profile |
| LangSmith | 既有 LangChain tracing 配置 | 默认关闭 |
| 离线评测与 CI 回归 | `evals/`、`scripts/evaluate_travel.py` | 不消耗 API 额度 |

这里的并行分支是工具与检索节点，并非每个分支都调用一次 LLM 的独立自治 Agent。主模型负责需求抽取与最终规划。这样能减少无必要的模型调用，也更容易解释失败来自哪里。

## 2. 先运行最小版本

在项目根目录打开终端：

```bash
conda activate agentroute
uv sync --frozen
```

`uv sync` 默认创建项目 `.venv`，不会自动把依赖装进已经激活的 Conda 环境。后面使用 `uv run`，确保运行的是锁文件对应的环境。若坚持只用 Conda，可以先用 `uv export --frozen --no-dev --no-emit-project -o /tmp/agentroute-requirements.txt`，再 `uv pip install --python "$CONDA_PREFIX/bin/python" -r /tmp/agentroute-requirements.txt`。

保留原 `.env` 的百炼配置，另外增加：

```dotenv
TRAVEL_ENABLED=true
TRAVEL_JOBS_ENABLED=false
```

然后启动原来的后端与 Streamlit。先输入“杭州三天，每人预算 1500 元，喜欢步行”。没有高德密钥时，行程末尾地图分支显示 `unavailable`，知识库显示 `ok`，这是预期的降级结果。

理解问题：为什么没有天气数据还能生成参考行程？因为天气是辅助信息，需求解析与结构化结果校验才是必须成功的环节。没有明确目的地、天数、预算时，系统仍然会追问。

## 3. 看懂并行与汇合

源码顺序：`extract_requirements → prepare_evidence → 五个资料节点 → generate_plan → render_plan`。

`prepare_evidence` 同时连向 weather、attractions、hotels、route 和 knowledge。每个节点只写自己的 State 字段，避免两个并发节点覆盖同一个字典。`add_edge(list(EVIDENCE_KINDS), "generate_plan")` 表示等待全部分支完成后只进入一次规划。

每条分支有总时间限制。异常转成结构化的 `status=unavailable`，所以辅助服务失败不会让整个图报错。用户看到的错误只包含分类，不包含带 API Key 的请求 URL。需求抽取或行程结构校验失败，则进入 `report_error`。

测试 `test_parallel_graph_survives_one_failure` 使用一个屏障：五个节点都进入以后才放行。串行执行会超时，因此它验证了实际并发，而不是仅检查函数名称。

## 4. 接入高德

在高德开放平台创建 Web 服务 Key，将其写入 `.env`：

```dotenv
TRAVEL_AMAP_KEY=替换为自己的Web服务Key
```

不要把 Key 发到聊天或提交 Git。云端使用服务器 `.env.deploy`，本地 `.env` 不会自动传到服务器。

天气先用地理编码取得城市 adcode，再调用天气预报接口；结果中的日期与发布时间必须保留。当前需求模型没有出行日期，因此预报只能作为近期参考，不能声称是任意未来旅行日期的天气。酒店搜索只取得 POI，不代表房价和库存。路线分支查询两个候选景点间的步行路线，不代表最终行程已经做了全局路线优化。

POI 没有 location 时额外做一次地理编码。网络错误或 HTTP 5xx 最多重试一次；鉴权、配额等业务错误立即失败。进程内缓存有效期 300 秒，最多 256 项，重启会清空；它不是 Redis 共享缓存。实际调用量要测量，不能写“减少百分之多少”而没有对照组。

接口依据：[高德天气文档](https://lbs.amap.com/api/webservice/guide/api/weatherinfo)、[POI 搜索文档](https://lbs.amap.com/api/webservice/guide/api/search/)。

## 5. MCP 是怎样接进去的

MCP 是工具发现和调用协议。配置运营者可信的 Streamable HTTP MCP 服务地址：

```dotenv
TRAVEL_MCP_URL=https://你的可信服务地址/mcp
TRAVEL_MCP_TOKEN=仅在服务要求Bearer鉴权时填写
```

项目读取工具列表后，仅选择 `maps_text_search`，不会让模型任意挑选服务器上的写入工具。当前适配器要求此工具接受 keywords、city、citylimit 参数；其他厂商同名工具也应核对 schema。MCP 失败后改用高德 REST。REST 同样需要自己的 Web 服务 Key。没有可用服务时正常显示降级，不伪造 MCP 成功。

这个实现只将 MCP 接到景点分支，其他分支使用 REST。MCP 返回的文本有长度限制，作为不可信参考资料注入模型；不能把工具返回内容当作系统指令。

## 6. RAG：从检索走到带来源的生成

知识库在 `src/travel/knowledge.json`，包含稳定 ID、城市、正文和来源。当前五条都是自编教学材料，不是抓取的真实游客口碑，不足以证明真实攻略质量。

流程如下：先按城市过滤，再分别运行 BM25 和城市结构化召回；配置 embedding 后加上余弦相似度向量召回；最后用 RRF 合并排名。中文基线使用字符二元组，例如“西湖步行”变成“西湖、湖步、步行”，不需要下载分词模型。BM25 同时考虑词频、文档长度与词在多少篇文档出现。

RRF 对每路排名中的文档累加 `1 / (60 + 排名)`，不直接相加无法比较的 BM25 分数和余弦分数。代码保留最多八个候选，精排后取三条给规划模型。

打开向量召回：

```dotenv
TRAVEL_EMBEDDING_MODEL=text-embedding-v3
```

该模型名需要在你的百炼地域与账号中可用。代码复用 `COMPATIBLE_API_KEY` 和 `COMPATIBLE_BASE_URL`，模型不可用会回退并记录 `dense_unavailable`。教学版每次重新计算小语料向量；扩大语料时应离线索引、记录语料版本与 embedding 版本，不能沿用每次全量计算的方式。

打开查询改写与 HyDE：

```dotenv
TRAVEL_QUERY_EXPANSION=true
```

它额外生成一段假设性文本，只参与检索，不直接当事实注入最终答案。当前扩写用于补充 BM25，向量查询仍用原始问题。要比较收益，应分别关闭和开启跑同一个评测集。

CrossEncoder 同时读取“问题 + 文档”打分，计算比向量点积贵。先在内存较大的本机安装：

```bash
uv sync --frozen --extra rerank
```

再配置 `TRAVEL_CROSS_ENCODER_MODEL` 为你已下载并验证的模型路径。首次加载可能耗时且耗内存，外层超时不会强制终止已经开始的 CPU 线程；小内存服务器不要启用。它是可选真实模型接口，未加载模型前不能说已验证精排效果。

## 7. Celery 与 Redis：提交后慢慢做

普通 `/stream` 仍然是原有多轮对话接口。新增 `/travel/jobs` 是独立单次规划任务：任务之间不共享聊天历史，完整需求应一次提交；缺字段时结果会返回追问，但不是自动续接旧聊天。

Redis 负责消息队列、结果状态及进度事件。Celery worker 从队列取任务运行 LangGraph。FastAPI 提交任务后立即返回 202，不等待模型。默认 worker 并发为 1、prefetch 为 1，避免小机器一下领取大量任务。结果和事件保留一小时，事件保留最多约 100 条。

本地先启动 Redis，然后分别开两个终端：

```bash
PYTHONPATH=src uv run celery -A travel.jobs:celery_app worker --loglevel=warning --concurrency=1
PYTHONPATH=src uv run python src/run_service.py
```

`.env` 增加：

```dotenv
TRAVEL_JOBS_ENABLED=true
TRAVEL_REDIS_URL=redis://localhost:6379/0
```

使用已配置的后端令牌，调用以下路径：

```bash
curl -X POST http://localhost:8080/travel/jobs \
  -H "Authorization: Bearer $AUTH_SECRET" \
  -H 'Content-Type: application/json' \
  -d '{"message":"杭州三天，每人1500元，喜欢西湖步行"}'
```

返回 job_id 后，用相同 Authorization 请求 `GET /travel/jobs/{job_id}` 看状态，用 `curl -N` 请求 `/travel/jobs/{job_id}/events` 看进度。SSE 的 `done` 表示 worker 结束；还要查看结果里的 `error`，判断业务规划是否成功。订阅重新连接时会从头重放保留的节点事件，客户端可以按事件 ID 去重。

这里沿用项目共享 Bearer Token 的信任模型，任务 UUID 不是用户身份验证。公开多用户产品需要真正的登录与任务归属校验。Celery 不自动重试整条规划，以免重复产生模型费用；worker 崩溃时也没有承诺任务恰好执行一次。

## 8. 监控部署

完整叠加配置是 `compose.advanced.yaml`。它增加 Redis、worker、Prometheus 和 Grafana，所有面板端口只绑定本机回环地址。你的原服务器内存较小，先确认可用资源，不要直接把完整配置强行启动。

在 `.env.deploy` 设置独立强密码 `GRAFANA_ADMIN_PASSWORD`。创建 `.monitoring-token`，内容只放后端 AUTH_SECRET，供 Prometheus 访问受保护的 `/metrics`；该文件已加入 Git 与 Docker 忽略。容器中的 Prometheus 用户需要能读取挂载文件，建议使用受限目录并为该文件配置合适的组权限。

```bash
docker compose --env-file .env.deploy \
  -f compose.deploy.yaml -f compose.advanced.yaml \
  --profile async --profile monitoring up -d --build
```

完整配置各服务的内存上限之和约 2.6 GiB，还需要系统余量，建议在至少 4 GiB 主机上做完整演示，CrossEncoder 另计。基础模式继续用原 `compose.deploy.yaml`。只有 monitoring profile 时 jobs 开关仍会打开但没有 worker，因此建议按上面命令同时启用两个 profile。

Prometheus 查询例子：

```promql
sum(rate(agentroute_http_requests_total[5m])) by (route)
```

```promql
histogram_quantile(0.95, sum(rate(agentroute_http_seconds_bucket[5m])) by (le, route))
```

第二个指标是 HTTP 响应开始阶段延迟，不包含 SSE 消息流完整耗时，不能把它写成“规划 P95”。Grafana 自动连接 Prometheus，并提供基础请求量面板。低流量时 rate 与分位数可能没有统计意义。

## 9. LangSmith 与隐私

原项目已经支持 LangChain tracing，只有明确需要时才配置：

```dotenv
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT=agentroute-learning
LANGCHAIN_API_KEY=自己的LangSmithKey
```

调用链可显示抽取、资料分支与生成过程。模型输入输出可能上传到第三方，使用虚构旅行需求做演示。没有 Key、没有在控制台看到真实 trace，就记录为未验证，不当作完成了全链路线上观测。

## 10. 评测与 bad case 回归

运行不联网的检索回归：

```bash
PYTHONPATH=src uv run python scripts/evaluate_travel.py
uv run pytest tests/agents/test_travel_assistant.py tests/agents/test_travel_evidence.py tests/agents/test_travel_evaluation.py
```

五条检索测试检查期望资料能否进入前三名，CI 会在 recall@3 低于 1 时失败。这是很小的冒烟集，不能据此宣传真实用户检索准确率。

`score_plan` 提供天数和时间段完整度、偏好关键词召回、预算一致性三项确定性诊断。关键词命中不是语义偏好满足；预算检查不验证市场价格。上线前还应扩展人工标注案例、路线可达性与来源正确性检查。

发现 bad case 时，先匿名化需求，保存“输入、期望、实际、失败原因”，再把可复现部分加入 `evals/retrieval.json` 或相应 pytest。修复后重跑同一集，推送 GitHub 触发 CI。暂不自动把真实用户聊天上传进仓库。

## 11. 三天如何学

第一天只看基础手册、需求抽取、State、条件路由和预算校验。自己改一个参数并观察追问。第二天读 providers、evidence、rag，画出并行节点图，亲自关闭高德 Key 验证降级。第三天在资源足够的机器运行 Redis、worker、SSE 与监控，再跑评测，准备五分钟演示。

面试可以演示：缺预算时追问；补齐后生成；禁用天气仍可规划；展示资料来源；提交异步任务看节点进度；运行离线测试。只把自己实际运行和理解的部分写入简历。P95、缓存延迟、调用量下降等数字必须来自自己测量，不能复制示例数字。
