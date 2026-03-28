# Test Guide

## Running Tests

```bash
uv run pytest tests/ -v
```

## Test Structure

| File | Coverage |
|------|----------|
| `tests/test_autodl_client.py` | HTTP client: auth headers, error code mapping, retry logic, deployment API |
| `tests/test_autodl_provider.py` | Provider: image resolution, GPU availability, job submission, status parsing, balance conversion |
| `tests/test_mcp_tools.py` | MCP tools: parameter validation, response format for all 5 tools |

## Test Details

### Client Tests (`test_autodl_client.py`)
- Response code mapping: `Success`, `BALANCE_NOT_ENOUGH`, `GPU_STOCK_NOT_ENOUGH`, `INSTANCE_NOT_FOUND`, generic errors
- Auth header injection
- Retry on network timeout (3 attempts with exponential backoff)
- Deployment create/stop API calls

### Provider Tests (`test_autodl_provider.py`)
- Image alias resolution (known alias, direct UUID, unknown alias)
- GPU availability listing with idle count filtering
- Job submission flow (balance check -> stock check -> create deployment)
- Job status parsing from container events (running, succeeded, failed, pending)
- Balance unit conversion (1/1000 yuan -> yuan)

### MCP Tool Tests (`test_mcp_tools.py`)
- `autodl_check_gpu_availability`: returns list of dicts with gpu_name
- `autodl_submit_job`: returns dict with job_id and pending status
- `autodl_get_job_status`: returns dict with status field
- `autodl_list_instances`: returns empty list when no active resources
- `autodl_check_balance`: returns dict with correct CNY conversion

## All tests use `respx` to mock HTTP requests — no real API calls are made.
