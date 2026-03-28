# gpu-hire 开发计划

> 版本：v0.1，日期：2026-03-28
> 目标：实现 AutoDL provider + MCP Server，让外部 agent 可以自动租用 GPU 并提交任务

---

## 一、项目结构

```
gpu-hire/
├── gpu_hire/
│   ├── __init__.py
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── base.py              # 抽象基类 + 公共数据模型
│   │   └── autodl/
│   │       ├── __init__.py
│   │       ├── client.py        # HTTP 客户端（认证、重试、错误处理）
│   │       ├── provider.py      # AutoDLProvider 实现
│   │       └── constants.py     # 镜像 UUID 表、区域代码、GPU 名称
│   └── mcp/
│       ├── __init__.py
│       └── server.py            # MCP Server 入口（5 个核心工具）
├── tests/
│   ├── test_autodl_client.py
│   ├── test_autodl_provider.py
│   └── test_mcp_tools.py
├── pyproject.toml
└── README.md
```

---

## 二、数据模型（`providers/base.py`）

所有 provider 共用的数据结构，基于 Pydantic v2。

```python
# GPU 库存条目
class GPUOffer(BaseModel):
    gpu_name: str          # "RTX 4090"
    gpu_count: int         # 可用数量
    region: str            # "westDC2"
    price_per_hour: float  # CNY/hr

# 任务状态
class JobStatus(str, Enum):
    PENDING   = "pending"    # 等待调度
    RUNNING   = "running"    # 运行中
    SUCCEEDED = "succeeded"  # 成功完成
    FAILED    = "failed"     # 失败
    STOPPED   = "stopped"    # 手动停止

# 任务信息
class Job(BaseModel):
    job_id: str
    provider: str = "autodl"
    status: JobStatus
    gpu_type: str
    gpu_count: int
    cmd: str
    created_at: datetime
    finished_at: datetime | None = None
    cost_cny: float | None = None      # 完成后填入

# 实例信息（容器实例模式用）
class Instance(BaseModel):
    instance_id: str
    provider: str = "autodl"
    status: str
    gpu_type: str
    gpu_count: int
    ssh_host: str
    ssh_port: int
    ssh_password: str
    cost_per_hour: float
    created_at: datetime

# 余额信息
class Balance(BaseModel):
    available_cny: float   # 可用余额
    voucher_cny: float     # 代金券余额
    total_spent_cny: float # 累计消费
```

---

## 三、AutoDL HTTP 客户端（`providers/autodl/client.py`）

封装所有 HTTP 细节，上层只调方法，不碰 requests。

### 职责
- 统一注入 `Authorization` Header
- 解析标准响应格式 `{"code": "Success", "data": ...}`，非 Success 时抛异常
- 余额不足（`BALANCE_NOT_ENOUGH`）时提前告警
- 网络超时重试（最多 3 次，指数退避）

### 关键方法

```python
class AutoDLClient:
    BASE_URL = "https://api.autodl.com"

    def __init__(self, token: str): ...

    # 账户
    async def get_balance(self) -> dict: ...
    async def send_wechat_notification(self, title: str, content: str) -> None: ...

    # 弹性部署
    async def get_gpu_stock(self, region: str | None, gpu_names: list[str] | None,
                            cuda_v_from: int, cuda_v_to: int) -> list[dict]: ...
    async def create_deployment(self, payload: dict) -> str: ...          # → deployment_uuid
    async def list_deployments(self, page: int, size: int) -> list[dict]: ...
    async def get_deployment_containers(self, deployment_uuid: str) -> list[dict]: ...
    async def get_container_events(self, deployment_uuid: str) -> list[dict]: ...
    async def stop_deployment(self, deployment_uuid: str) -> None: ...
    async def delete_deployment(self, deployment_uuid: str) -> None: ...

    # 容器实例 Pro（Phase 2）
    async def create_instance(self, payload: dict) -> str: ...            # → instance_uuid
    async def get_instance_status(self, instance_uuid: str) -> str: ...
    async def get_instance_snapshot(self, instance_uuid: str) -> dict: ...
    async def list_instances(self, page: int, size: int) -> list[dict]: ...
    async def power_on_instance(self, instance_uuid: str) -> None: ...
    async def power_off_instance(self, instance_uuid: str) -> None: ...
    async def release_instance(self, instance_uuid: str) -> None: ...
```

### 错误处理规范

| AutoDL 错误码 | 处理方式 |
|-------------|---------|
| `BALANCE_NOT_ENOUGH` | 抛 `InsufficientBalanceError`，附带当前余额 |
| `GPU_STOCK_NOT_ENOUGH` | 抛 `NoGPUAvailableError`，附带 GPU 名称和区域 |
| `INSTANCE_NOT_FOUND` | 抛 `InstanceNotFoundError` |
| 其他非 Success | 抛 `AutoDLAPIError(code, msg)` |
| HTTP 超时 | 重试 3 次后抛 `AutoDLNetworkError` |

---

## 四、AutoDL Provider（`providers/autodl/provider.py`）

业务逻辑层，编排 client 调用，处理轮询和状态机。

### 核心方法

#### `list_gpu_availability`
```
调用 get_gpu_stock（不传 gpu_names，查全部）
→ 按 idle_gpu_num 降序排列
→ 返回 list[GPUOffer]
```

#### `submit_job`
```
入参：cmd, gpu_type, gpu_count, image_uuid, cuda_v_from, cuda_v_to,
      regions, env_vars, timeout_minutes

1. get_balance() → 余额 < 5 元时 warn
2. get_gpu_stock(gpu_name=gpu_type) → idle == 0 时抛 NoGPUAvailableError
3. 若有 env_vars → 写入文件存储 .gpu-hire/{job_id}/.env
4. 拼装 cmd = "source /root/autodl-fs/.gpu-hire/{job_id}/.env && {cmd}"
   （无 env_vars 则跳过第 3/4 步）
5. create_deployment(type=Job, cmd=wrapped_cmd, ...)
6. 返回 Job(status=PENDING)
```

#### `get_job_status`
```
入参：job_id (即 deployment_uuid)

1. get_container_events(job_id)
2. 取最新事件映射到 JobStatus：
   - container_running  → RUNNING
   - container_exited_0 → SUCCEEDED
   - container_exited_N → FAILED（N != 0）
   - container_stopped  → STOPPED
3. 若 SUCCEEDED/FAILED，计算 cost = duration * price_per_hour
4. 返回 Job（含 finished_at, cost_cny）
```

#### `wait_for_job`（轮询帮助方法，供 MCP/SDK 使用）
```
入参：job_id, poll_interval=10s, timeout=300s

循环调用 get_job_status，直到终态（SUCCEEDED/FAILED/STOPPED）或超时
超时时不自动停止，仅抛 JobTimeoutError 并告知 job_id
```

#### `list_active_instances`
```
list_deployments(status=running) + list_instances(status=running)
合并为统一列表，包含费用/小时
```

### 常量表（`providers/autodl/constants.py`）

```python
# 弹性部署用（人类可读名称，直接传 gpu_name_set）
KNOWN_GPU_NAMES = [
    "RTX 4090", "RTX 3090", "RTX 3080 Ti",
    "A100 SXM4", "A800", "H800",
    "L20", "V100", "RTX A4000",
]

# 容器实例 Pro 用（uuid，传 gpu_spec_uuid）
GPU_SPEC_UUIDS = {
    "H800-80G":      "h800",
    "RTX 4090-24G":  "v-48g",
    "PRO6000-96G":   "pro6000-p",
    "RTX 4080S-32G": "v-32g-p",
    "RTX 3090-48G":  "v-48g-350w",
    "RTX 5090-32G":  "5090-p",
}

# 弹性部署公共基础镜像
BASE_IMAGE_UUIDS = {
    "pytorch-cuda11.1":    "base-image-12be412037",
    "pytorch-cuda11.3":    "base-image-u9r24vthlk",
    "pytorch-cuda11.8":    "base-image-l2t43iu6uk",
    "tensorflow-cuda11.2": "base-image-0gxqmciyth",
    "tensorflow-cuda11.4": "base-image-4bpg0tt88l",
    "miniconda-cuda11.6":  "base-image-mbr2n4urrc",
    "tensorrt-cuda11.8":   "base-image-l2843iu23k",
}

# 区域代码
REGIONS = [
    "westDC2", "westDC3",
    "beijingDC1", "beijingDC2", "beijingDC3", "beijingDC4",
    "neimengDC1", "neimengDC3",
    "foshanDC1", "chongqingDC1", "yangzhouDC1",
]

# CUDA 版本编码（整数）
CUDA_VERSIONS = {
    "11.1": 111, "11.3": 113, "11.8": 118,
    "12.0": 120, "12.1": 121, "12.2": 122,
}
```

---

## 五、MCP Server（`mcp/server.py`）

使用 `mcp` Python SDK（`pip install mcp`），以 stdio 模式启动。

### 5 个核心工具

#### Tool 1：`autodl_check_gpu_availability`

```
描述：
  查询 AutoDL 各区域 GPU 库存和价格。
  返回可用 GPU 列表，gpu_name 字段可直接传给 autodl_submit_job。
  调用场景：提交任务前确认有货，或比较不同 GPU 型号的价格。

入参：
  gpu_type: str | None  # 不传则返回全部型号
  region: str | None    # 不传则查所有区域

返回：
  list[GPUOffer] — 含 gpu_name, region, idle_count, price_per_hour(CNY)
```

#### Tool 2：`autodl_submit_job`

```
描述：
  在 AutoDL 上提交 GPU 批量任务（弹性部署 Job 模式）。
  任务完成后自动释放资源，按实际运行时间计费（按秒）。
  适合：训练、评估、批量推理等无需交互的任务。
  不适合：需要 JupyterLab 或交互式调试的场景。
  注意：会产生费用，RTX 4090 约 ¥1.98/小时。

入参：
  cmd: str              # 运行命令，如 "python train.py --epochs 10"
  gpu_type: str         # GPU 型号，必须是 autodl_check_gpu_availability 返回的 gpu_name
  image: str            # 镜像，如 "pytorch-cuda11.8"，或直接传 image_uuid
  gpu_count: int = 1    # GPU 数量
  regions: list[str] | None  # 指定区域，不传自动选
  env_vars: dict | None      # 环境变量，安全写入文件存储后注入

返回：
  Job — 含 job_id, status=pending
```

#### Tool 3：`autodl_get_job_status`

```
描述：
  查询 AutoDL 任务的当前状态。
  对于已完成的任务，同时返回运行时长和费用。

入参：
  job_id: str   # autodl_submit_job 返回的 job_id

返回：
  Job — 含 status, duration_minutes(若完成), cost_cny(若完成)
```

#### Tool 4：`autodl_list_instances`

```
描述：
  列出当前所有活跃的 AutoDL 实例和部署（正在计费的资源）。
  用于检查是否有忘记释放的资源，避免意外扣费。

入参：无

返回：
  list[dict] — 每项含 id, type(job/instance), gpu_type, status, cost_per_hour, running_minutes
```

#### Tool 5：`autodl_check_balance`

```
描述：
  查询 AutoDL 账户余额。建议在提交任务前调用，确认余额充足。
  余额单位为人民币（CNY）。

入参：无

返回：
  Balance — 含 available_cny, voucher_cny
```

### 启动方式

```bash
# 直接运行
AUTODL_TOKEN=xxx python -m gpu_hire.mcp.server

# 通过 uvx（推荐，用户无需手动安装）
uvx gpu-hire

# Claude Code 配置（.claude/settings.json 或全局）
{
  "mcpServers": {
    "gpu-hire": {
      "command": "uvx",
      "args": ["gpu-hire"],
      "env": { "AUTODL_TOKEN": "your_token_here" }
    }
  }
}
```

---

## 六、典型 Agent 工作流

```
用户：帮我在 AutoDL 上跑 train.py，用 4090

Agent 调用链：
  1. autodl_check_balance()
     → ¥23.50 可用，代金券 ¥5.00

  2. autodl_check_gpu_availability(gpu_type="RTX 4090")
     → westDC2: 215 idle @ ¥1.98/hr
     → beijingDC1: 48 idle @ ¥1.98/hr

  3. autodl_submit_job(
       cmd="python train.py",
       gpu_type="RTX 4090",
       image="pytorch-cuda11.8"
     )
     → job_id: "dep-a1b2c3d4"

  4. [稍后] autodl_get_job_status("dep-a1b2c3d4")
     → status: running, 已运行 12 分钟

  5. [完成后] autodl_get_job_status("dep-a1b2c3d4")
     → status: succeeded, 运行 23 分钟, 费用 ¥0.76
```

---

## 七、任务清单

### Phase 1（当前目标）

- [ ] **P1-1** 初始化项目：`pyproject.toml`，依赖（httpx, pydantic, mcp），包结构
- [ ] **P1-2** `providers/base.py`：`GPUOffer`, `Job`, `JobStatus`, `Balance`, `Instance` 数据模型
- [ ] **P1-3** `providers/autodl/constants.py`：GPU 名称表、镜像 UUID 表、区域代码
- [ ] **P1-4** `providers/autodl/client.py`：HTTP 客户端，认证，错误处理，重试
- [ ] **P1-5** `providers/autodl/provider.py`：`list_gpu_availability`, `submit_job`, `get_job_status`, `wait_for_job`, `list_active_instances`
- [ ] **P1-6** `mcp/server.py`：5 个 MCP 工具，stdio 模式启动
- [ ] **P1-7** `pyproject.toml` 配置 entry point：`gpu-hire = gpu_hire.mcp.server:main`
- [ ] **P1-8** 单元测试（mock HTTP）：client 错误处理、provider 状态机、MCP 工具参数校验
- [ ] **P1-9** `README.md`：安装、配置 Token、Claude Code 接入步骤

### Phase 2

- [ ] **P2-1** 容器实例 Pro API（`launch_instance`, `stop_instance`, `release_instance`）
- [ ] **P2-2** 日志 wrapper：训练脚本自动 tee 到文件存储
- [ ] **P2-3** 微信通知：任务完成/失败时推送
- [ ] **P2-4** CLI：`gpu-hire submit/status/list/balance`

### Phase 3

- [ ] **P3-1** 费用监控：累计超阈值时告警/自动停止
- [ ] **P3-2** 私有镜像管理
- [ ] **P3-3** Web UI

---

## 八、关键约束与实现注意事项

### 弹性部署的固有限制

| 约束 | 具体表现 | 实现处理 |
|------|---------|---------|
| 无日志 API | 无法实时拉取 stdout/stderr | wrapper 脚本写文件存储；`get_job_status` 只返回状态不返回日志 |
| 无环境变量字段 | `container_template` 没有 `env` | 提交前写 `.env` 到文件存储，cmd 里 `source` |
| 停止即删数据 | 容器停止后数据立即消失 | 任务结果必须在退出前写入文件存储或外部存储 |
| 无重启 | 失败后只能重新提交 | `get_job_status` 返回 FAILED 时提示用户重新调用 `submit_job` |
| 多卡不保证同机 | 2 卡可能跨两台机器 | 文档注明此限制；需要同机多卡推荐用容器实例模式 |

### `gpu_name_set` 的正确用法

弹性部署用**人类可读名称**（如 `"RTX 4090"`），不是 Pro Instance API 的 UUID。
实现时先调 `gpu_stock` 获取合法名称，不要硬编码白名单。

### 余额单位换算

AutoDL API 返回余额单位为 **1/1000 元**，所有展示和计算前必须 `÷ 1000`：
```python
available_cny = data["assets"] / 1000
```

### 轮询策略

```python
# get_job_status 的 container_event 映射
EVENT_TO_STATUS = {
    "container_running":   JobStatus.RUNNING,
    "container_exited_0":  JobStatus.SUCCEEDED,   # exit code 0
    "container_stopped":   JobStatus.STOPPED,
    # exit code 非 0 → FAILED（需从事件 detail 里取 exit_code 判断）
}

# wait_for_job 轮询参数
POLL_INTERVAL_SECONDS = 10
DEFAULT_TIMEOUT_MINUTES = 60
```

### 镜像参数处理

`submit_job` 的 `image` 参数支持两种格式：
- 别名（如 `"pytorch-cuda11.8"`）→ 从 `BASE_IMAGE_UUIDS` 查表转换
- 直接传 UUID（如 `"image-db8346e037"`）→ 直接使用

```python
def resolve_image_uuid(image: str) -> str:
    if image.startswith("image-") or image.startswith("base-image-"):
        return image  # 已经是 UUID
    return BASE_IMAGE_UUIDS.get(image) or raise ValueError(f"Unknown image alias: {image}")
```
