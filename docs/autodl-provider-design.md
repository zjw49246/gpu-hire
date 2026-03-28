# AutoDL Provider 调研与实现设计

> 调研日期：2026-03-28
> 背景：用户拥有 AutoDL 子账号，优先实现 AutoDL provider

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

AutoDL 有竞价实例，折扣通常 30–50%（约 ¥1.00–1.40/hr for 4090），但具体折扣在控制台实时显示，API 文档中未公开如何通过 API 选择竞价模式（目前看似 UI 操作）。

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

#### 查询 GPU 库存
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
Response：`idle_gpu_num`（当前可用），`total_gpu_num`（总量）

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

### ⚠️ 子账号 API Token 问题

官方文档**未明确说明**子账号是否有独立的 Developer Token。
**建议**：进入子账号控制台 → 账号设置，确认是否有独立 Token 生成页面。如有，每个子账号可独立调用 API。

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

1. **基础 HTTP 客户端封装**
   - 统一认证 Header 处理
   - 错误处理（`code != "Success"` 的情况）
   - 余额不足提前告警

2. **容器实例 Pro API**
   - 创建实例（`create`）
   - 状态轮询直到 running（`status`）
   - 获取 SSH 信息（`snapshot`）
   - 列出 / 关机 / 释放

3. **MCP Server**
   - 至少 5 个核心工具：查库存、启动实例、提交任务、查状态、关机/释放

4. **CLI**
   - `gpu-hire autodl launch --gpu 4090`
   - `gpu-hire autodl list`
   - `gpu-hire autodl stop <id>`

### Phase 2

5. **弹性部署 Job API**
   - 一键提交训练命令，自动管理生命周期
   - 任务完成微信通知

6. **子账号支持**
   - 多 Token 管理
   - 子账号任务隔离

7. **镜像管理**
   - 列出私有镜像
   - 公开镜像搜索（如有 API）

### Phase 3

8. **竞价实例支持**（需进一步研究 API 是否开放）
9. **费用监控与预算控制**（超额自动关机）
10. **Web UI**（任务面板、SSH 一键连接、日志查看）

---

## 九、注意事项

1. **镜像 UUID 问题**：Pro API 创建实例需要 `image_uuid`（格式 `image-XXXXXXXXXX`），目前无公开 API 枚举公共镜像。需要：
   - 预置常用镜像 UUID 表（用户验证后维护）
   - 或提供私有镜像列表 API + 允许用户指定 UUID

2. **子账号 API Token**：官方文档未明确。建议用户确认子账号是否有独立 Token，如有则每个子账号可独立使用。

3. **竞价模式**：目前 API 中未见竞价参数，可能仅支持按需模式，竞价为 UI 功能。

4. **数据残留计费**：关机后数据保留但不计算实例费；数据盘扩容费用始终计算（不论开关机）。

5. **网络访问**：仅 SSH + 6006/6008 端口（HTTPS 映射）。如需更多端口，需企业认证或 SSH 隧道。

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
