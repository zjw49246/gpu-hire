# GPU 租赁平台调研与架构设计

> 调研日期：2026-03-24

## 一、调研目标

为 LLM Agent 构建一个代码仓库，使 Agent 能够方便地租用 GPU、提交和管理任务。需要：
1. 找到性价比最高的 GPU 租赁方案（优先弹性计费）
2. 调研现有开源项目是否可直接使用
3. 设计 agent-friendly 的架构

---

## 二、现有开源项目调研

### 结论：没有完全匹配的项目，但 SkyPilot 是最佳基础

| 项目 | Stars | 定位 | Agent 友好度 | 适合我们吗？ |
|------|-------|------|-------------|------------|
| **SkyPilot** | ~9,700 | 多云 GPU 编排 | 高（已有 Claude Code skill） | 最接近，可作为底层 |
| **dstack** | ~2,070 | GPU 任务控制面板 | 中 | 备选方案 |
| **GPUStack** | ~4,700 | GPU 集群推理管理 | 低 | 不匹配（管现有集群，非租赁） |
| **KAI Scheduler** | ~1,190 | K8s GPU 调度器 | 低 | 不匹配（需要已有 K8s 集群） |

### SkyPilot 详细分析

- **GitHub**: https://github.com/skypilot-org/skypilot
- **支持 20+ 云平台**: AWS, GCP, Azure, Lambda, RunPod, Vast.ai, CoreWeave, FluidStack 等
- **核心能力**:
  - 一份 YAML/Python 定义 → 自动选最便宜的可用 GPU
  - Managed Spot Jobs: 自动处理 spot 中断、checkpoint、恢复
  - 内置 Web UI 和 Python API
- **Agent 集成**: 2026年3月发布了 "Agent Skills"，专为 Claude Code / Codex 等 AI 编程 agent 设计。有演示：Claude Code 用 SkyPilot 在 8 小时内自主提交 ~910 个实验到 16-GPU K8s 集群
- **不足**:
  - 通用 ML 基础设施工具，不是 agent-first 设计
  - YAML 配置偏重，对 agent 来说不够结构化
  - 缺少跨平台实时比价、自动选择最优提供商的能力

### dstack 详细分析

- **GitHub**: https://github.com/dstackai/dstack
- **支持**: AWS, GCP, Azure, Lambda, RunPod, Vast.ai, CoreWeave, DigitalOcean 等
- **核心能力**: 开发环境 + 训练 + 推理的统一控制面板，自动 provisioning，job queuing
- **有 Web UI 和 Python SDK**
- **不足**: 无 agent skill/MCP 集成

### Agent-Friendly GPU 工具（MCP Server）

| 工具 | Stars | 说明 |
|------|-------|------|
| **Hyperbolic MCP** | 19 | Agent 可列出、租用、SSH 管理 GPU。但只支持 Hyperbolic 一家 |
| **Lambda Cloud MCP** | 20 | 非官方 Lambda 云 CLI + MCP |
| **Google Colab MCP** | 351 | 官方 Google MCP，agent 可在 Colab GPU 上执行代码（T4/L4） |
| **SkyPilot Agent Skill** | - | 通过 agentskills.so 发布，Claude Code 可直接调用 |

**现有差距（gpu-hire 可填补的空白）**:
1. 没有一个**统一的 MCP server** 能让 agent 跨多个平台租 GPU
2. 没有 **agent-native API**（结构化输出、实时比价、自动选最优平台）
3. 没有开源的**跨平台价格比较与自动决策**工具（Shadeform 做这个但不开源）

---

## 三、GPU 租赁平台对比

### 1. 价格总览

#### H100 80GB 每小时价格

| 平台 | On-Demand | Spot/竞价 | 计费粒度 | API |
|------|-----------|----------|---------|-----|
| **SaladCloud** | $0.99 | - | 按秒 | REST API |
| **Vast.ai** | $1.49-1.87 | 竞价制 | 按秒 | Python SDK + REST |
| **TensorDock** | $2.25 | $1.30 | 按秒 | Python SDK + REST |
| **FluidStack** | $1.80-2.60 | - | 按秒 | REST API |
| **RunPod** | $3.99（安全）/ $1.99（社区） | 社区竞价 | 按秒 | Python SDK + REST |
| **Lambda Cloud** | $2.49-2.99 | - | 按秒 | REST API |
| **CoreWeave** | $4.76 | - | 按分钟 | K8s API |
| **Modal** | ~$3.95 | - | 按秒（Serverless） | Python SDK |
| **AWS (p5.xlarge)** | $3.90 | ~$2.00-2.50 | 按秒 | boto3 |
| **GCP (a3-highgpu)** | $3.00 | $2.25 | 按秒 | gcloud SDK |
| **Azure** | $6.98 | ~$2.10 | 按秒 | Azure SDK |

#### A100 80GB 每小时价格

| 平台 | On-Demand | Spot/竞价 |
|------|-----------|----------|
| **SaladCloud** | $0.50 | - |
| **TensorDock** | $1.05 | $0.67 |
| **Vast.ai** | $0.70-0.90 | 竞价制 |
| **RunPod** | $1.64（安全）/ ~$0.99（社区） | 社区竞价 |
| **Azure Spot** | - | $0.74 |
| **AWS Spot** | - | ~$1.10-1.60 |
| **GCP Spot** | - | ~$1.00-1.50 |

### 2. 各平台详细分析

#### Tier 1：最具性价比（优先实现）

##### Vast.ai — 市场竞价模式，最灵活
- **模式**: P2P GPU 市场，用户竞价租用
- **GPU 类型**: RTX 3090, 4090, A100, H100, L40S 等（供应商提供的各种型号）
- **定价**: 竞价制，可设最高价，市场化定价极具竞争力
- **API**: Python SDK (`vastai-sdk`) + REST API + CLI
- **Job 支持**: 支持容器化任务提交，可以提交 Docker 容器
- **特点**: 支持按需和竞价、自动竞价、实例搜索和过滤
- **注意**: 机器质量参差不齐，网络可能不稳定

##### RunPod — 平衡性价比与体验
- **模式**: On-Demand + Community Cloud + Serverless
- **GPU 类型**: A100, H100, A10G, RTX 4090, L40S 等
- **Serverless**: 按请求计费，自动扩缩容，冷启动优化
- **API**: Python SDK (`runpod`) + REST API + GraphQL
- **Job 支持**: Serverless Endpoint 原生支持任务队列
- **特点**:
  - Community Cloud 便宜但可能被中断
  - Secure Cloud 可靠性更高
  - Serverless 模式非常适合推理任务

##### Modal — 最佳 Serverless 体验
- **模式**: 纯 Serverless，Python 装饰器即可部署
- **GPU 类型**: T4, L4, A10G, A100, H100
- **定价**: 按秒计费，自动扩缩到 0，$30/月免费额度
- **API**: Python SDK（原生 Python，不需要 YAML/Docker）
- **Job 支持**: 原生支持异步任务、批量推理
- **特点**:
  - 开发体验最好，`@app.function(gpu="H100")` 即可
  - 零配置，无需管理基础设施
  - 适合推理和中小规模训练
- **不足**: 不支持自定义 spot 策略，价格比 Vast.ai 高

##### TensorDock — 低价 Spot
- **模式**: On-Demand + Spot（市场化）
- **GPU 类型**: A100, H100, RTX 4090 等
- **定价**: Spot 价格极低（H100 $1.30/hr, A100 $0.67/hr）
- **API**: Python SDK + REST API
- **特点**: 价格竞争力强，Spot 市场

#### Tier 2：大厂云 Spot（稳定性好）

##### AWS Spot GPU
- **GPU 实例**: p3 (V100), p4d (A100), p5 (H100), g4dn (T4), g5 (A10G), g6 (L4)
- **Spot 折扣**: 通常 40-70% off on-demand
- **API**: boto3 + AWS CLI，生态最成熟
- **Job 支持**: SageMaker Training Jobs, AWS Batch
- **特点**:
  - 2025年6月 H100 降价 44%，竞争力提升
  - Spot 中断率取决于实例类型和区域
  - 隐藏成本：数据传输 $0.08-0.12/GB
- **适合**: 需要高可靠性、已有 AWS 生态的用户

##### GCP Spot GPU
- **GPU 实例**: T4, L4, A100, H100
- **Spot 定价**: 约 on-demand 的 60-75%
- **API**: google-cloud SDK
- **Job 支持**: Vertex AI Training
- **特点**: Spot 可能被随时抢占（最长 24 小时）

##### Azure Spot GPU
- **GPU 实例**: T4, A100, H100
- **Spot 定价**: Azure Spot A100 $0.74/hr 是大厂最低
- **API**: Azure SDK
- **特点**: On-demand 最贵（H100 $6.98/hr），但 Spot 有竞争力

#### Tier 3：特殊场景

##### SaladCloud — 极低价，适合容错推理
- **模式**: 利用消费级 GPU（RTX 4090 等），分布式推理
- **定价**: H100 $0.99/hr, A100 $0.50/hr, RTX 4090 $0.16/hr（全网最低）
- **API**: REST API
- **注意**: 消费级 GPU，可靠性低，适合无状态、可容错的推理任务
- **不适合**: 训练任务

##### Lambda Cloud — 简单可靠
- **模式**: 简单的 GPU 云，按需租用
- **GPU**: A100, H100
- **定价**: H100 $2.49-2.99/hr，无隐藏费用，无数据传输费
- **API**: REST API + 非官方 MCP
- **适合**: 需要简单、可靠的 GPU 实例

##### CoreWeave — 企业级
- **模式**: GPU-native 云平台
- **GPU**: A100, H100, GB200
- **定价**: H100 $4.76/hr
- **API**: Kubernetes API
- **适合**: 大规模训练，企业客户

##### FluidStack — 中等价位
- **GPU**: A100, H100, A10G
- **定价**: H100 $1.80-2.60/hr
- **API**: REST API + Python SDK

##### DigitalOcean GPU Droplets
- **GPU**: H100 SXM 80GB
- **定价**: $3.21/hr
- **API**: DigitalOcean API
- **适合**: DigitalOcean 已有用户

### 3. 按使用场景推荐

| 场景 | 推荐平台 | 原因 |
|------|---------|------|
| **训练（省钱）** | Vast.ai / TensorDock Spot | H100 $1.30-1.87/hr |
| **训练（可靠）** | Lambda Cloud / AWS Spot | 稳定性好，spot 有中断恢复 |
| **推理（Serverless）** | Modal / RunPod Serverless | 按需扩缩，按秒计费 |
| **推理（大批量低价）** | SaladCloud | 极低价，适合容错批量推理 |
| **交互式开发** | Modal（$30 免费）/ RunPod | 开箱即用 |
| **多云灵活切换** | SkyPilot + 任意平台 | 自动选最便宜的 |

---

## 四、gpu-hire 架构设计建议

### 定位

**Agent-first 的多平台 GPU 租赁与任务管理工具**，填补现有开源工具的空白。

### 两种架构路线

#### 方案 A：基于 SkyPilot 的上层封装

```
┌─────────────────────────────────────────────┐
│              gpu-hire                         │
│  ┌─────────┐ ┌──────────┐ ┌───────────────┐ │
│  │ MCP     │ │ CLI /    │ │ Web UI        │ │
│  │ Server  │ │ Python   │ │ (可选前端)     │ │
│  │         │ │ SDK      │ │               │ │
│  └────┬────┘ └────┬─────┘ └──────┬────────┘ │
│       └───────────┼──────────────┘           │
│             ┌─────▼─────┐                    │
│             │ 统一任务   │                    │
│             │ 管理层     │                    │
│             └─────┬─────┘                    │
│             ┌─────▼─────┐                    │
│             │ SkyPilot   │ ← 核心编排引擎    │
│             └─────┬─────┘                    │
└───────────────────┼─────────────────────────┘
        ┌───────────┼───────────┐
        ▼           ▼           ▼
    ┌──────┐   ┌──────┐   ┌──────┐
    │AWS   │   │RunPod│   │Vast  │  ...
    │Spot  │   │      │   │.ai   │
    └──────┘   └──────┘   └──────┘
```

**优点**: SkyPilot 已对接 20+ 平台，Spot 管理成熟，社区活跃
**缺点**: 重度依赖 SkyPilot，灵活性受限；SkyPilot 的 YAML 范式对 agent 不够友好

#### 方案 B：轻量级多平台抽象层（推荐）

```
┌──────────────────────────────────────────────────┐
│                    gpu-hire                        │
│                                                    │
│  ┌──────────┐ ┌──────────┐ ┌───────────────────┐ │
│  │ MCP      │ │ Python   │ │ Web UI (React)    │ │
│  │ Server   │ │ SDK/CLI  │ │ 任务面板+日志+费用 │ │
│  └────┬─────┘ └────┬─────┘ └──────┬────────────┘ │
│       └────────────┼───────────────┘              │
│              ┌─────▼──────┐                       │
│              │ Core Engine │                       │
│              │             │                       │
│              │ • 实时比价   │                       │
│              │ • 任务调度   │                       │
│              │ • Spot 管理  │                       │
│              │ • 成本追踪   │                       │
│              └─────┬──────┘                       │
│              ┌─────▼──────┐                       │
│              │ Provider    │                       │
│              │ Abstraction │                       │
│              │ Layer       │                       │
│              └─────┬──────┘                       │
│   ┌────────┬───────┼───────┬────────┬───────┐    │
│   ▼        ▼       ▼       ▼        ▼       ▼    │
│ ┌──────┐┌──────┐┌──────┐┌──────┐┌──────┐┌─────┐ │
│ │Vast  ││RunPod││Modal ││AWS   ││Tensor││GCP  │ │
│ │.ai   ││      ││      ││Spot  ││Dock  ││Spot │ │
│ │Plugin││Plugin││Plugin││Plugin││Plugin││Plug.│ │
│ └──────┘└──────┘└──────┘└──────┘└──────┘└─────┘ │
└──────────────────────────────────────────────────┘
```

**优点**: 轻量、可控、agent-first 设计、每个 provider 独立插件
**缺点**: 需要自己实现每个 provider 的对接

### 推荐方案 B 的模块设计

```
gpu-hire/
├── gpu_hire/
│   ├── __init__.py
│   ├── core/
│   │   ├── engine.py          # 核心调度引擎
│   │   ├── pricing.py         # 实时比价模块
│   │   ├── job.py             # 任务生命周期管理
│   │   └── models.py          # 数据模型（Pydantic）
│   ├── providers/             # Provider 插件
│   │   ├── base.py            # 抽象基类
│   │   ├── vastai.py          # Vast.ai
│   │   ├── runpod.py          # RunPod
│   │   ├── modal_provider.py  # Modal
│   │   ├── aws_spot.py        # AWS Spot
│   │   ├── tensordock.py      # TensorDock
│   │   ├── gcp_spot.py        # GCP Spot
│   │   └── lambda_cloud.py    # Lambda Cloud
│   ├── mcp/                   # MCP Server（Agent 接口）
│   │   ├── server.py          # MCP Server 实现
│   │   └── tools.py           # MCP Tools 定义
│   ├── cli/                   # CLI 接口
│   │   └── main.py
│   └── api/                   # REST API（供前端调用）
│       └── app.py
├── frontend/                  # 可选 Web UI
│   └── ...                    # React/Next.js 任务面板
├── tests/
├── docs/
├── pyproject.toml
└── README.md
```

### Provider 抽象基类设计思路

每个 provider 需要实现以下接口：

```python
class GPUProvider(ABC):
    """GPU 云平台抽象接口"""

    @abstractmethod
    async def list_gpus(self, filters: GPUFilter) -> list[GPUOffer]:
        """列出可用 GPU 及价格"""

    @abstractmethod
    async def launch(self, config: LaunchConfig) -> Instance:
        """启动 GPU 实例"""

    @abstractmethod
    async def submit_job(self, instance_id: str, job: JobConfig) -> Job:
        """提交任务到实例"""

    @abstractmethod
    async def get_job_status(self, job_id: str) -> JobStatus:
        """查询任务状态"""

    @abstractmethod
    async def stop(self, instance_id: str) -> None:
        """停止实例"""

    @abstractmethod
    async def get_logs(self, job_id: str) -> str:
        """获取任务日志"""
```

### MCP Tools 设计思路

为 AI Agent 暴露的工具：

| Tool | 说明 | 典型调用场景 |
|------|------|------------|
| `gpu_search` | 跨平台搜索可用 GPU，返回价格排序列表 | "找一个最便宜的 A100" |
| `gpu_compare_prices` | 指定 GPU 型号，比较各平台价格 | "H100 在各平台多少钱" |
| `gpu_launch` | 在指定平台启动 GPU 实例 | "在 RunPod 启动一个 A100" |
| `gpu_launch_cheapest` | 自动选最便宜的平台启动 | "用最便宜的 H100 跑这个任务" |
| `job_submit` | 提交训练/推理任务 | "在这个实例上运行 train.py" |
| `job_status` | 查询任务状态 | "我的训练任务完成了吗" |
| `job_logs` | 获取任务日志 | "看看训练日志" |
| `job_list` | 列出所有任务 | "我有哪些在跑的任务" |
| `instance_list` | 列出所有实例 | "我现在租了哪些 GPU" |
| `instance_stop` | 停止实例 | "停掉这个实例" |
| `cost_summary` | 费用汇总 | "这个月花了多少钱" |

### 优先实现路线图

#### Phase 1：核心 MVP
1. **Vast.ai provider** — 最便宜，API 完善，适合快速验证
2. **RunPod provider** — Serverless + On-Demand，覆盖推理场景
3. **核心引擎** — 比价、任务管理
4. **MCP Server** — Agent 可用
5. **CLI** — 人类可用

#### Phase 2：扩展平台
6. **Modal provider** — 最佳 Serverless 体验
7. **AWS Spot provider** — 企业级 Spot
8. **TensorDock provider** — 低价 Spot

#### Phase 3：完善体验
9. **Web UI** — 任务面板、费用追踪、日志查看
10. **GCP/Azure Spot providers**
11. **自动 Spot 中断恢复**
12. **费用预警与预算控制**

---

## 五、关键决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 架构路线 | 方案 B（轻量级抽象层） | 更灵活，agent-first，不依赖 SkyPilot |
| 语言 | Python | GPU/ML 生态主力语言，各平台 SDK 都是 Python |
| Agent 接口 | MCP Server | Claude Code / OpenClaw 等主流 Agent 都支持 MCP |
| 首批 Provider | Vast.ai + RunPod | 性价比高、API 好、覆盖训练+推理 |
| 前端 | 可选，Phase 3 | 先保证 Agent 和 CLI 可用 |
| 数据模型 | Pydantic v2 | 类型安全，JSON Schema 导出（MCP 友好） |
| 异步 | asyncio | Provider API 调用天然适合异步 |

---

## 六、参考资源

### 开源项目
- SkyPilot: https://github.com/skypilot-org/skypilot
- dstack: https://github.com/dstackai/dstack
- GPUStack: https://github.com/gpustack/gpustack
- Hyperbolic MCP: https://github.com/HyperbolicLabs/hyperbolic-mcp
- Google Colab MCP: https://github.com/googlecolab/colab-mcp
- Vast.ai CLI: https://github.com/vast-ai/vast-cli
- RunPod Python SDK: https://github.com/runpod/runpod-python

### Provider SDK
- Vast.ai Python SDK: https://docs.vast.ai/sdk/python/quickstart
- RunPod SDK: https://github.com/runpod/runpod-python
- Modal: https://modal.com/docs
- AWS boto3: https://boto3.amazonaws.com/v1/documentation/api/latest/
- TensorDock: https://www.tensordock.com/

### 价格信息
- H100 价格对比: https://intuitionlabs.ai/articles/h100-rental-prices-cloud-comparison
- 免费 GPU 额度汇总: https://www.thundercompute.com/blog/free-cloud-gpu-credits
- Serverless GPU 对比: https://introl.com/blog/serverless-gpu-platforms-runpod-modal-beam-comparison-guide-2025
