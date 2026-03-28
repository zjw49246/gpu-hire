"""Tests for MCP tool parameter validation and response format."""

import os
import pytest
import httpx
import respx

# Set token before importing server module
os.environ.setdefault("AUTODL_TOKEN", "test-token")

from gpu_hire.mcp.server import (
    autodl_check_gpu_availability,
    autodl_submit_job,
    autodl_get_job_status,
    autodl_list_instances,
    autodl_check_balance,
    _provider,
)
import gpu_hire.mcp.server as server_module


@pytest.fixture(autouse=True)
def reset_provider():
    server_module._provider = None
    yield
    server_module._provider = None


def _mock_balance(assets=50000):
    respx.post("https://api.autodl.com/api/v1/dev/wallet/balance").mock(
        return_value=httpx.Response(
            200, json={"code": "Success", "data": {"assets": assets, "accumulate": 0, "voucher_balance": 0}}
        )
    )


def _mock_gpu_stock(idle=100):
    respx.post("https://api.autodl.com/api/v1/dev/machine/region/gpu_stock").mock(
        return_value=httpx.Response(
            200,
            json={
                "code": "Success",
                "data": [{"RTX 4090": {"idle_gpu_num": idle, "total_gpu_num": 200}}],
            },
        )
    )


@pytest.mark.asyncio
class TestCheckGpuAvailability:
    @respx.mock
    async def test_returns_list(self):
        _mock_gpu_stock(idle=50)
        result = await autodl_check_gpu_availability(gpu_type="RTX 4090")
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["gpu_name"] == "RTX 4090"

    @respx.mock
    async def test_all_gpus(self):
        _mock_gpu_stock(idle=10)
        result = await autodl_check_gpu_availability()
        assert isinstance(result, list)


@pytest.mark.asyncio
class TestSubmitJob:
    @respx.mock
    async def test_returns_job_dict(self):
        _mock_balance()
        _mock_gpu_stock()
        respx.post("https://api.autodl.com/api/v1/dev/deployment").mock(
            return_value=httpx.Response(
                200, json={"code": "Success", "data": {"deployment_uuid": "dep-mcp-test"}}
            )
        )
        result = await autodl_submit_job(
            cmd="python train.py",
            gpu_type="RTX 4090",
            image="pytorch-cuda11.8",
        )
        assert isinstance(result, dict)
        assert result["job_id"] == "dep-mcp-test"
        assert result["status"] == "pending"


@pytest.mark.asyncio
class TestGetJobStatus:
    @respx.mock
    async def test_returns_status(self):
        respx.post("https://api.autodl.com/api/v1/dev/deployment/container/list").mock(
            return_value=httpx.Response(
                200,
                json={
                    "code": "Success",
                    "data": {"list": [{"events": [{"type": "container_running"}]}]},
                },
            )
        )
        result = await autodl_get_job_status(job_id="dep-123")
        assert result["status"] == "running"


@pytest.mark.asyncio
class TestListInstances:
    @respx.mock
    async def test_returns_list(self):
        respx.post("https://api.autodl.com/api/v1/dev/deployment/list").mock(
            return_value=httpx.Response(
                200, json={"code": "Success", "data": {"list": []}}
            )
        )
        respx.post("https://api.autodl.com/api/v1/dev/instance/pro/list").mock(
            return_value=httpx.Response(
                200, json={"code": "Success", "data": {"list": []}}
            )
        )
        result = await autodl_list_instances()
        assert isinstance(result, list)


@pytest.mark.asyncio
class TestCheckBalance:
    @respx.mock
    async def test_returns_balance(self):
        _mock_balance(assets=23500)
        result = await autodl_check_balance()
        assert result["available_cny"] == 23.5
