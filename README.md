# gpu-hire

GPU rental automation via MCP Server. Let AI agents rent GPUs and submit training jobs on AutoDL.

## Features

- **MCP Server** with 5 tools for GPU rental automation
- **AutoDL provider** — check GPU availability, submit batch jobs, monitor status, check balance
- Automatic resource release after job completion (elastic deployment Job mode)
- Per-second billing, costs in CNY

## Installation

```bash
# Install with uv (recommended)
uv tool install gpu-hire

# Or with pip
pip install gpu-hire
```

## Configuration

### 1. Get your AutoDL token

Go to [AutoDL Console](https://www.autodl.com) -> Account Settings -> Developer Token.

### 2. Connect to Claude Code

Add to your Claude Code settings (`.claude/settings.json` or global settings):

```json
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

### 3. Or run directly

```bash
AUTODL_TOKEN=your_token_here python -m gpu_hire.mcp.server
```

## MCP Tools

| Tool | Description |
|------|-------------|
| `autodl_check_gpu_availability` | Query GPU stock and prices across regions |
| `autodl_submit_job` | Submit a batch GPU job (auto-releases on completion) |
| `autodl_get_job_status` | Check job status (pending/running/succeeded/failed) |
| `autodl_list_instances` | List all active instances (find forgotten resources) |
| `autodl_check_balance` | Check account balance in CNY |

## Example Workflow

```
User: Run train.py on a 4090

Agent:
  1. autodl_check_balance()         -> 23.50 CNY available
  2. autodl_check_gpu_availability() -> RTX 4090: 215 idle @ 1.98 CNY/hr
  3. autodl_submit_job(cmd="python train.py", gpu_type="RTX 4090", image="pytorch-cuda11.8")
     -> job_id: "dep-a1b2c3d4", status: pending
  4. autodl_get_job_status("dep-a1b2c3d4")
     -> status: succeeded, cost: 0.76 CNY
```

## Available Images

| Alias | Image UUID |
|-------|-----------|
| `pytorch-cuda11.1` | `base-image-12be412037` |
| `pytorch-cuda11.3` | `base-image-u9r24vthlk` |
| `pytorch-cuda11.8` | `base-image-l2t43iu6uk` |
| `tensorflow-cuda11.2` | `base-image-0gxqmciyth` |
| `tensorflow-cuda11.4` | `base-image-4bpg0tt88l` |
| `miniconda-cuda11.6` | `base-image-mbr2n4urrc` |
| `tensorrt-cuda11.8` | `base-image-l2843iu23k` |

You can also pass image UUIDs directly (e.g., `image-xxx` or `base-image-xxx`).

## Development

```bash
# Clone and install
git clone https://github.com/zjw49246/gpu-hire.git
cd gpu-hire
uv sync

# Run tests
uv run pytest tests/ -v
```

## Limitations

- Elastic deployment has no real-time log API — results must be written to file storage before exit
- Multi-GPU jobs may be scheduled across machines (use container instance mode for guaranteed co-location)
- Spot/bidding instances are not supported via API
- Container data is deleted when the job stops
