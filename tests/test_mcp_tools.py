"""Tests for MCP tool parameter validation and response format."""

import os
import pytest
import httpx
import respx
import unittest.mock as mock

os.environ.setdefault("AUTODL_TOKEN", "test-token")

from gpu_hire.mcp.server import (
    autodl_check_gpu_availability,
    autodl_submit_job,
    autodl_get_job_status,
    autodl_get_job_log,
    autodl_stop_job,
    autodl_list_instances,
    autodl_check_balance,
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
            json={"code": "Success", "data": [{"RTX 4090": {"idle_gpu_num": idle, "total_gpu_num": 200}}]},
        )
    )


@pytest.mark.asyncio
class TestCheckGpuAvailability:
    @respx.mock
    async def test_returns_list(self):
        _mock_gpu_stock(idle=50)
        result = await autodl_check_gpu_availability(gpu_type="RTX 4090")
        assert isinstance(result, list)
        assert len(result) > 0
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
        respx.post("https://api.autodl.com/api/v1/dev/instance/pro/list").mock(
            return_value=httpx.Response(200, json={"code": "Success", "data": {"list": []}})
        )
        respx.post("https://api.autodl.com/api/v1/dev/instance/pro/create").mock(
            return_value=httpx.Response(200, json={"code": "Success", "data": "pro-mcp-test"})
        )
        respx.get(url__regex=r".*/instance/pro/status.*").mock(
            return_value=httpx.Response(200, json={"code": "Success", "data": "running"})
        )
        respx.get(url__regex=r".*/instance/pro/snapshot.*").mock(
            return_value=httpx.Response(200, json={"code": "Success", "data": {
                "proxy_host": "test.host", "ssh_port": 22,
                "root_password": "pw", "snapshot_gpu_alias_name": "RTX 3090",
                "payg_price": 1870,
            }})
        )
        with mock.patch("gpu_hire.providers.autodl.provider.start_job") as m:
            m.return_value = None
            result = await autodl_submit_job(
                cmd="python train.py",
                gpu_type="RTX 3090",
                image="pytorch-cuda11.8",
            )
        assert isinstance(result, dict)
        assert result["job_id"] == "pro-mcp-test"
        assert result["status"] == "running"


@pytest.mark.asyncio
class TestGetJobStatus:
    @respx.mock
    async def test_returns_status(self):
        respx.get(url__regex=r".*/instance/pro/status.*").mock(
            return_value=httpx.Response(200, json={"code": "Success", "data": "running"})
        )
        respx.get(url__regex=r".*/instance/pro/snapshot.*").mock(
            return_value=httpx.Response(200, json={"code": "Success", "data": {
                "proxy_host": "test.host", "ssh_port": 22, "root_password": "pw",
                "snapshot_gpu_alias_name": "RTX 3090",
            }})
        )
        with mock.patch("gpu_hire.providers.autodl.provider.check_job") as m:
            m.return_value = ("running", None)
            result = await autodl_get_job_status(job_id="pro-123")
        assert result["status"] == "running"


@pytest.mark.asyncio
class TestGetJobLog:
    @respx.mock
    async def test_returns_string(self):
        respx.get(url__regex=r".*/instance/pro/snapshot.*").mock(
            return_value=httpx.Response(200, json={"code": "Success", "data": {
                "proxy_host": "test.host", "ssh_port": 22, "root_password": "pw",
            }})
        )
        with mock.patch("gpu_hire.providers.autodl.provider.get_log_tail") as m:
            m.return_value = "epoch 1/10 loss=0.5\n"
            result = await autodl_get_job_log(job_id="pro-123")
        assert "epoch" in result


@pytest.mark.asyncio
class TestStopJob:
    @respx.mock
    async def test_stops_and_releases(self):
        respx.post(url__regex=r".*/instance/pro/power_off").mock(
            return_value=httpx.Response(200, json={"code": "Success", "data": None})
        )
        respx.post(url__regex=r".*/instance/pro/release").mock(
            return_value=httpx.Response(200, json={"code": "Success", "data": None})
        )
        with mock.patch("asyncio.sleep"):
            result = await autodl_stop_job(job_id="pro-123")
        assert result["status"] == "stopped"


@pytest.mark.asyncio
class TestListInstances:
    @respx.mock
    async def test_returns_list(self):
        respx.post("https://api.autodl.com/api/v1/dev/instance/pro/list").mock(
            return_value=httpx.Response(200, json={"code": "Success", "data": {"list": []}})
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
