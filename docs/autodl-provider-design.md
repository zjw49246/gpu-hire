# AutoDL Provider 调研与实现设计

> 调研日期：2026-03-28，风险验证：2026-03-28
> 背景：用户拥有 AutoDL 子账号，使用主账号 Token，优先实现 AutoDL provider

---

## 一、AutoDL 平台概览

AutoDL（极速炼丹，autodl.com）是国内主流的 GPU 算力租赁平台，成立于 2021 年。核心定位：**按秒计费、弹性租用、价格对标国内最低**。

平台特点：
- 按秒计费，最低 ¥0.01
- 2000+ 预置镜像（PyTorch、TF、各 CUDA 版本）
- 支持 SSH + JupyterLab 访问
- 有官方 REST API（但无官方 Python SDK）
- 支持子账号系统

---

## 二、价格对比

### 主力 GPU 按需价格（会员价，约 9.5 折）

| GPU 型号 | 显存 | 单卡/小时（约） | API GPU UUID |
|---------|------|--------------|-------------|
| H800 SXM | 80GB | ¥8.88 | `h800` |
| H20 | 96GB | ¥6.98 | - |
| A100 SXM4 | 80GB | ¥6.68 | - |
| A800 | 80GB | ¥4.98 | - |
| L20 | 48GB | ¥3.68 | - |
| A100 | 40GB | ¥3.28 | - |
| RTX 5090 | 32GB | ¥2.88 | `5090-p` |
| V100 | 32GB | ¥2.28 | - |
| RTX 4090 | 24GB | **¥1.98** | `v-48g`（48G双卡） |
| RTX 3090 | 24GB | ¥1.32–1.58 | - |

> **注意**：AutoDL 不提供 H100（受出口管制），最高端为 H800。
> RTX 4090 @ ¥1.98/hr ≈ $0.27/hr，是全球最便宜的 4090 之一。

### 与主流海外平台价格对比

| GPU | AutoDL | RunPod 社区 | Vast.ai | AWS Spot |
|-----|--------|------------|---------|----------|
| RTX 4090 | ¥1.98 (~$0.27) | $0.34 | ~$0.30 | 无 |
| A100 80GB | ¥6.68 (~$0.91) | ~$0.99 | $0.70-0.90 | ~$1.10 |
| 等效 H100 (H800) | ¥8.88 (~$1.21) | $1.99 | $1.49 | ~$2.00 |

**AutoDL 在国内场景下性价比极高，尤其是 RTX 4090。**

### 竞价实例（Spot）

AutoDL 有竞价实例，折扣通常 30–50%（约 ¥1.00–1.40/hr for 4090），但**经验证竞价模式仅支持 UI 操作**，API 明确不支持（见下方风险验证）。

### 存储价格

| 类型 | 免费额度 | 超量收费 |
|------|---------|---------|
| 文件存储 | 20GB | ¥0.01/GB/天 |
| 网盘 | 20GB | ¥0.30/GB/月 |
| 保存的镜像 | 30GB | ¥0.01/GB/天 |
| 系统盘扩容 | 0 | 按使用量（随实例计费） |

---

## 三、API 完整文档

### 认证

所有请求需携带 Header：
```
Authorization: <developer_token>
```

Developer Token 在控制台 → 账号设置 → 开发者 Token 中获取。

Base URL：`https://api.autodl.com`（Pro API）
部分接口使用：`https://www.autodl.com`（旧接口）

---

### 3.1 账户类 API

#### 查询余额
```
POST /api/v1/dev/wallet/balance
```
Response（余额单位为 **1/1000 元**，需 ÷1000）：
```json
{
  "code": "Success",
  "data": {
    "assets": 12345,        // 可用余额（分×10）
    "accumulate": 98765,    // 累计消费
    "voucher_balance": 5000 // 代金券余额
  }
}
```

#### 发送微信通知（任务完成提醒）
```
POST https://www.autodl.com/api/v1/wechat/message/send
Body: { "title": "任务完成", "name": "训练结束", "content": "loss: 0.01" }
```
限制：每天 50 条，每分钟 5 条。

---

### 3.2 容器实例 Pro API

#### 创建实例
```
POST /api/v1/dev/instance/pro/create
```
```json
{
  "req_gpu_amount": 1,                    // GPU 数量 1-4
  "gpu_spec_uuid": "v-48g",               // GPU 型号 UUID（见下方映射表）
  "image_uuid": "image-db8346e037",       // 镜像 UUID
  "cuda_v_from": 118,                     // CUDA 版本下限（118 = CUDA 11.8）
  "expand_system_disk_by_gb": 0,          // 系统盘扩容 GB (0-500)
  "data_center_list": ["westDC2"],        // 可选：指定数据中心
  "instance_name": "my-training-job"     // 可选：实例名称
}
```
Response：`{"code": "Success", "data": {"instance_uuid": "pro-76419909953e"}}`

**GPU UUID 映射表：**

| 显示名 | API UUID |
|--------|---------|
| H800-80G | `h800` |
| RTX 4090-24G（48G双卡） | `v-48g` |
| PRO6000-96G | `pro6000-p` |
| RTX 4080(S)-32G | `v-32g-p` |
| RTX 3090-48G（双卡） | `v-48g-350w` |
| RTX 5090-32G | `5090-p` |

#### 获取实例详情（SSH 信息、状态、资源用量）
```
GET /api/v1/dev/instance/pro/snapshot?instance_uuid=pro-76419909953e
```
Response 包含：
- SSH 连接信息（host, port, password/key）
- JupyterLab token
- GPU/CPU/内存用量
- 计费信息

#### 查询实例状态
```
GET /api/v1/dev/instance/pro/status?instance_uuid=pro-76419909953e
```
状态值：`"running"` / `"shutdown"` / `"creating"` / `"releasing"`

#### 列出实例
```
POST /api/v1/dev/instance/pro/list
Body: { "page_index": 1, "page_size": 20 }
```

#### 开机
```
POST /api/v1/dev/instance/pro/power_on
Body: { "instance_uuid": "pro-76419909953e", "payload": "gpu" }
```
`payload` 可选：`"gpu"`（使用 GPU）或 `"non_gpu"`（仅 CPU，省钱）

#### 关机
```
POST /api/v1/dev/instance/pro/power_off
Body: { "instance_uuid": "pro-76419909953e" }
```

#### 释放实例
```
POST /api/v1/dev/instance/pro/release
Body: { "instance_uuid": "pro-76419909953e" }
```
> 必须先关机才能释放。释放后数据永久删除。

---

### 3.3 弹性部署 API（适合批量任务 / 生产推理）

弹性部署是 AutoDL 为批量任务设计的功能，类似 Kubernetes Job，**更适合 Agent 提交批量训练任务**。

> **重要：弹性部署对 GPU 型号无限制，支持所有在 `gpu_stock` API 里能查到的型号。**
> `gpu_name_set` 必须使用 `gpu_stock` 返回的 key 作为值（人类可读名称，如 `"RTX 4090"`），
> 不是 Pro Instance API 的 UUID 格式。可先调 `gpu_stock` 动态发现合法 GPU 名称。

#### 查询 GPU 库存（兼具发现合法 GPU 名称的作用）
```
POST /api/v1/dev/machine/region/gpu_stock
```
```json
{
  "region_sign": "westDC2",
  "cuda_v_from": 118,
  "cuda_v_to": 125,
  "gpu_name_set": ["RTX 4090"],
  "price_from": 0,
  "price_to": 300
}
```
Response 示例：
```json
{
  "data": [
    { "RTX 4090":    { "idle_gpu_num": 215, "total_gpu_num": 2285 } },
    { "RTX 3080 Ti": { "idle_gpu_num": 20,  "total_gpu_num": 392  } },
    { "RTX A4000":   { "idle_gpu_num": 6,   "total_gpu_num": 24   } }
  ]
}
```
返回的 key（如 `"RTX 4090"`）即为 `gpu_name_set` 的合法值，可直接传给创建部署接口。

#### 创建部署（批量 Job）
```
POST /api/v1/dev/deployment
```
```json
{
  "name": "my-training-job",
  "deployment_type": "Job",           // "ReplicaSet" / "Job" / "Container"
  "replica_num": 1,
  "container_template": {
    "dc_list": ["westDC2"],
    "gpu_name_set": ["RTX 4090"],
    "gpu_num": 1,
    "cuda_v_from": 118,
    "cuda_v_to": 125,
    "cpu_num_from": 4,
    "memory_size_from": 16,
    "price_from": 0,
    "price_to": 300,
    "image_uuid": "image-db8346e037",
    "cmd": "python train.py --epochs 100"  // 启动命令
  }
}
```
Response：`{"deployment_uuid": "dep-xxxxxxxx"}`

#### 列出部署
```
POST /api/v1/dev/deployment/list
Body: { "page_index": 1, "page_size": 20, "status": "running" }
```

#### 列出部署中的容器（查看任务进度）
```
POST /api/v1/dev/deployment/container/list
Body: { "deployment_uuid": "dep-xxxxxxxx", "page_index": 1, "page_size": 20 }
```

#### 停止部署
```
PUT /api/v1/dev/deployment/operate
Body: { "deployment_uuid": "dep-xxxxxxxx", "operate": "stop" }
```

#### 删除部署
```
DELETE /api/v1/dev/deployment
Body: { "deployment_uuid": "dep-xxxxxxxx" }
```

---

### 3.4 数据中心区域代码

| 区域代码 | 位置 |
|---------|-----|
| `westDC2` | 西部 DC2 |
| `westDC3` | 西部 DC3 |
| `beijingDC1–4` | 北京 DC1-4 |
| `neimengDC1` | 内蒙 DC1 |
| `neimengDC3` | 内蒙 DC3 |
| `foshanDC1` | 佛山 DC1 |
| `chongqingDC1` | 重庆 DC1 |
| `yangzhouDC1` | 扬州 DC1 |

---

## 四、子账号系统

### 基本架构

```
主账号 (Main Account)
├── 子账号 A → 独立实例 + 虚拟余额
├── 子账号 B → 独立实例 + 虚拟余额
└── 子账号 C → 共享主账号余额
```

- 主账号默认最多创建 **10 个子账号**（可申请扩容）
- 子账号登录入口：`https://www.autodl.com/subAccountLogin`
- 子账号可见范围：仅自己的实例 OR 全部实例（可配置）

### 权限配置（每个子账号独立配置）

| 权限项 | 说明 |
|--------|------|
| 容器实例 | 可开关，控制子账号是否能创建/管理实例 |
| 弹性部署 | 可开关 |
| 镜像管理 | 可开关 |
| 文件存储 | 可开关 |
| 充值/账单 | 可控制子账号是否能看到账单、充值 |
| 余额隔离 | 共享主账号余额 OR 给子账号独立虚拟余额（可设上限） |

### 计费逻辑

- 子账号产生的费用由**对应子账号承担**（从其虚拟余额扣）
- 主账号是实际付款方
- 主账号可查看每个子账号的消费汇总
- 如子账号虚拟余额耗尽，可配置自动关机

### API Token 策略（已确认）

**使用主账号 Token。** 主账号 Developer Token 在控制台 → 账号设置中生成，功能完整，可操作所有资源。子账号文档完全未提及独立 Token，架构上不需要多 Token 支持，直接用主账号 Token 统一管理。

---

## 五、现有开源工具

| 工具 | GitHub | 功能 |
|------|--------|------|
| `autodl-keeper` | turbo-duck/autodl-keeper | 防止实例到期：定期自动开关机 |
| `autodl_idle_gpu_monitor` | iioSnail/autodl_idle_gpu_monitor | GPU 空闲检测 + 微信通知 + 自动关机 |

**结论：目前没有 AutoDL 的 MCP Server、CLI 工具或 Python SDK。这正是 gpu-hire 的机会所在。**

---

## 六、AutoDL Provider 实现设计

### 核心数据模型

```python
# 实例状态
class AutoDLInstanceStatus(str, Enum):
    CREATING = "creating"
    RUNNING = "running"
    SHUTDOWN = "shutdown"
    RELEASING = "releasing"

# 任务类型（对应弹性部署类型）
class AutoDLDeploymentType(str, Enum):
    JOB = "Job"             # 批量任务，运行到完成
    REPLICA_SET = "ReplicaSet"  # 持续运行副本（推理服务）
    CONTAINER = "Container"  # 单容器

# 统一实例信息
class GPUInstance(BaseModel):
    instance_id: str
    provider: str = "autodl"
    status: AutoDLInstanceStatus
    gpu_type: str
    gpu_count: int
    ssh_host: str
    ssh_port: int
    ssh_password: str
    cost_per_hour: float  # CNY
    created_at: datetime
```

### AutoDL Provider 接口设计

```python
class AutoDLProvider(GPUProvider):

    async def list_gpu_prices(
        self,
        gpu_types: list[str] | None = None,
        region: str | None = None
    ) -> list[GPUOffer]:
        """查询实时 GPU 价格和库存"""
        # 调用 /api/v1/dev/machine/region/gpu_stock

    async def launch_instance(
        self,
        gpu_type: str,        # 如 "RTX 4090"
        gpu_count: int = 1,
        image: str = "pytorch",  # 预置镜像名或 image_uuid
        cuda_version: int = 118,
        disk_gb: int = 0,
        region: str | None = None,
    ) -> GPUInstance:
        """创建并启动实例，等待 running 状态，返回 SSH 信息"""
        # 1. 创建实例: POST /api/v1/dev/instance/pro/create
        # 2. 轮询状态: GET /api/v1/dev/instance/pro/status
        # 3. 获取 SSH 信息: GET /api/v1/dev/instance/pro/snapshot

    async def submit_job(
        self,
        cmd: str,             # 运行命令，如 "python train.py"
        gpu_type: str = "RTX 4090",
        gpu_count: int = 1,
        image: str = "pytorch",
        region: str | None = None,
    ) -> Job:
        """通过弹性部署提交批量任务（不需要手动管理实例生命周期）"""
        # 调用 POST /api/v1/dev/deployment（type=Job）

    async def get_instance(self, instance_id: str) -> GPUInstance:
        """获取实例详情"""

    async def list_instances(self) -> list[GPUInstance]:
        """列出所有实例"""

    async def stop_instance(self, instance_id: str) -> None:
        """关机（保留数据，停止计费）"""

    async def release_instance(self, instance_id: str) -> None:
        """释放实例（永久删除）"""

    async def get_balance(self) -> Balance:
        """查询余额"""

    async def send_notification(
        self, title: str, content: str
    ) -> None:
        """发送微信通知（任务完成等场景）"""
```

### 任务提交两种模式对比

| 模式 | 适用场景 | 实现方式 |
|------|---------|---------|
| **容器实例 + SSH** | 交互式开发、需要调试、长期持有 | 创建实例 → SSH 上传代码 → 执行命令 |
| **弹性部署 Job** | 批量训练、自动化任务、Agent 提交 | 直接 API 创建 Job，指定镜像+命令 |

**Agent 使用场景推荐弹性部署 Job**：
- 无需手动管理实例生命周期
- 任务完成自动释放
- 支持多任务并发
- API 一步提交，结构化返回

---

## 七、MCP Tools 设计（针对 AutoDL）

```python
# 面向 AI Agent 的 MCP 工具

@mcp_tool
async def autodl_check_gpu_availability(
    gpu_type: str,       # "RTX 4090" | "A100" | "H800"
    region: str = "auto"
) -> GPUStockInfo:
    """查询指定 GPU 在各区域的库存和价格"""

@mcp_tool
async def autodl_launch_instance(
    gpu_type: str,
    image: str = "pytorch:2.1.0-cuda11.8",
    disk_gb: int = 50
) -> InstanceInfo:
    """
    启动 GPU 实例，返回 SSH 连接信息。
    注意：实例关机前会持续计费。
    """

@mcp_tool
async def autodl_submit_job(
    cmd: str,
    gpu_type: str = "RTX 4090",
    image: str = "pytorch:2.1.0-cuda11.8",
    gpu_count: int = 1
) -> JobInfo:
    """
    提交批量任务，任务完成后自动释放资源。
    适合训练、批量推理等无需交互的任务。
    """

@mcp_tool
async def autodl_get_job_status(job_id: str) -> JobStatus:
    """查询任务状态（running/succeeded/failed）"""

@mcp_tool
async def autodl_list_instances() -> list[InstanceInfo]:
    """列出所有在运行的实例及费用"""

@mcp_tool
async def autodl_stop_instance(instance_id: str) -> None:
    """关机（保留数据，停止计费）"""

@mcp_tool
async def autodl_release_instance(instance_id: str) -> None:
    """释放实例（永久删除数据，请确认后再操作）"""

@mcp_tool
async def autodl_check_balance() -> BalanceInfo:
    """查询 AutoDL 账户余额（CNY）"""
```

---

## 八、实现优先级

### Phase 1 MVP（优先实现）

核心目标：外部 agent 通过 MCP 可以自动提交 GPU 任务。

1. **基础 HTTP 客户端封装**
   - 统一认证 Header（主账号 Token）
   - 标准错误处理（`code != "Success"`）
   - 余额不足提前告警

2. **弹性部署 Job API**（agent 提交任务的主路径）
   - 查询 GPU 库存 `gpu_stock`（兼发现合法 GPU 名称）
   - 创建 Job 部署
   - 轮询容器状态（5s 间隔，5min 超时）
   - 停止 / 删除部署

3. **MCP Server（5 个核心工具）**
   - `autodl_check_gpu_availability` — 查库存 + 返回合法 GPU 名称
   - `autodl_submit_job` — 提交批量任务，自动释放
   - `autodl_get_job_status` — 查任务状态
   - `autodl_list_instances` — 列出所有实例（防忘关机）
   - `autodl_check_balance` — 查余额（提交前先确认有钱）

4. **CLI**
   - `gpu-hire autodl submit --gpu "RTX 4090" --cmd "python train.py"`
   - `gpu-hire autodl status <job_id>`
   - `gpu-hire autodl list`
   - `gpu-hire autodl balance`

### Phase 2

5. **容器实例 Pro API**（交互式开发场景）
   - 创建实例、状态轮询、获取 SSH 信息、关机、释放

6. **日志与通知**
   - 训练脚本 wrapper（自动写日志到文件存储）
   - 任务完成微信通知

7. **环境变量安全传递**
   - 提交前写 `.env` 到文件存储，cmd 里 source

### Phase 3

8. **费用监控与预算控制**（超额自动关机）
9. **私有镜像管理**（列出 + 创建）
10. **Web UI**（任务面板、日志查看、费用追踪）

---

## 九、风险验证结论（已实测）

经过对官方文档的逐一核查，以下风险点已确认：

| 风险点 | 结论 | 严重程度 | 应对方案 |
|--------|------|---------|---------|
| **实时日志获取** | 弹性部署无任何日志 API | 高 | 训练脚本 tee 到文件存储，完成后拉取 |
| **公共镜像 UUID** | 无枚举 API，文档有静态列表（不完整） | 中 | 维护常用镜像 UUID 常量表，允许用户传 UUID 覆盖 |
| **竞价实例 API** | **不支持**，文档原文："暂不支持选择其他计费方式" | 高 | 无法绕过，但按需价已是全球最低，影响有限 |
| **子账号 Token** | 文档无提及，直接用主账号 Token | 已解决 | 主账号 Token 统一管理 |
| **环境变量传递** | `container_template` 无 `env` 字段 | 中 | 写入文件存储后在 cmd 里 source，或拼入 cmd 字符串 |
| **实例启动时间** | ~1 分钟，纯轮询，无 webhook | 低 | 5-10s 轮询，5min 超时；启用容器复用可加速 |
| **弹性部署 GPU 限制** | **无限制**，支持所有 gpu_stock 返回的型号 | 无风险 | 先调 gpu_stock 动态发现合法 GPU 名称 |
| **price_from/to 是竞价吗** | **否**，是调度过滤条件（只在该价格范围机器上运行）| 中（易误解）| 文档说明清楚，不作为竞价机制使用 |

### 环境变量传递方案（推荐）

```bash
# 方案 A：写入文件存储（推荐，密钥不暴露在命令行）
# 提交前：将 .env 写到 /root/autodl-fs/.gpu-hire/{job_id}/.env
# cmd:
"source /root/autodl-fs/.gpu-hire/{job_id}/.env && python train.py"

# 方案 B：拼入 cmd（简单，但 ps 可见）
"HF_TOKEN=xxx WANDB_KEY=yyy python train.py"
```

### 日志获取方案

```bash
# 训练脚本 wrapper（gpu-hire 自动注入）：
"python train.py 2>&1 | tee /root/autodl-fs/.gpu-hire/{job_id}/output.log; echo $? > /root/autodl-fs/.gpu-hire/{job_id}/exit_code"

# 任务完成后通过文件存储 API 拉取日志
```

### 基础镜像 UUID 常量表（文档提供的静态值）

| 框架 | CUDA | image_uuid |
|------|------|-----------|
| PyTorch | 11.1 | `base-image-12be412037` |
| PyTorch | 11.3 | `base-image-u9r24vthlk` |
| PyTorch | 11.8 | `base-image-l2t43iu6uk` |
| TensorFlow | 11.2 | `base-image-0gxqmciyth` |
| TensorFlow | 11.4 | `base-image-4bpg0tt88l` |
| Miniconda | 11.6 | `base-image-mbr2n4urrc` |
| TensorRT | 11.8 | `base-image-l2843iu23k` |

> 更多新镜像需联系 AutoDL 客服获取 UUID，或用户提供私有镜像 UUID。

---

## 十、注意事项

1. **数据残留计费**：关机后数据保留但不计算实例费；数据盘扩容费用始终计算（不论开关机）。弹性部署容器停止后数据立即删除。

2. **网络访问**：仅 SSH + 6006/6008 端口（HTTPS 映射）。如需更多端口，需企业认证或 SSH 隧道。

3. **多卡调度**：弹性部署多卡任务（如 2 卡）可能调度到两台不同机器，不保证同机。如需同机多卡请用容器实例模式。

4. **容器复用**（`reuse_container: true`）：弹性部署停止后容器缓存 7 天，下次提交同镜像可跳过 pull，启动更快。

---

## 十、参考资源

- [AutoDL 官方文档](https://www.autodl.com/docs/)
- [AutoDL Pro API 文档](https://www.autodl.com/docs/instance_pro_api/)
- [AutoDL 弹性部署 API](https://www.autodl.com/docs/esd_api_doc/)
- [AutoDL 子账号文档](https://api.autodl.com/docs/c_user/)
- [AutoDL 微信通知 API](https://www.autodl.com/docs/msg/)
- [AutoDL GPU 规格](https://www.autodl.com/docs/gpu/)
- [AutoDL 价格页](https://www.autodl.com/docs/price/)
- [GitHub: autodl-keeper](https://github.com/turbo-duck/autodl-keeper)（社区参考实现）
- [GitHub: autodl_idle_gpu_monitor](https://github.com/iioSnail/autodl_idle_gpu_monitor)
