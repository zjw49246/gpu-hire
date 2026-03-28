"""Tests for AutoDL HTTP client error handling and retries."""

import pytest
import httpx
import respx

from gpu_hire.providers.autodl.client import (
    AutoDLClient,
    AutoDLAPIError,
    AutoDLNetworkError,
    InsufficientBalanceError,
    NoGPUAvailableError,
    InstanceNotFoundError,
)


@pytest.fixture
def client():
    return AutoDLClient(token="test-token")


@pytest.mark.asyncio
class TestCheckResponse:
    def test_success(self):
        result = AutoDLClient._check_response({"code": "Success", "data": {"key": "val"}})
        assert result == {"key": "val"}

    def test_balance_not_enough(self):
        with pytest.raises(InsufficientBalanceError):
            AutoDLClient._check_response({"code": "BALANCE_NOT_ENOUGH", "msg": "low"})

    def test_gpu_stock_not_enough(self):
        with pytest.raises(NoGPUAvailableError):
            AutoDLClient._check_response({"code": "GPU_STOCK_NOT_ENOUGH", "msg": "none"})

    def test_instance_not_found(self):
        with pytest.raises(InstanceNotFoundError):
            AutoDLClient._check_response({"code": "INSTANCE_NOT_FOUND", "msg": "gone"})

    def test_generic_error(self):
        with pytest.raises(AutoDLAPIError) as exc_info:
            AutoDLClient._check_response({"code": "UNKNOWN_ERR", "msg": "oops"})
        assert exc_info.value.code == "UNKNOWN_ERR"


@pytest.mark.asyncio
class TestGetBalance:
    @respx.mock
    async def test_get_balance_success(self, client):
        respx.post("https://api.autodl.com/api/v1/dev/wallet/balance").mock(
            return_value=httpx.Response(
                200,
                json={"code": "Success", "data": {"assets": 12345, "accumulate": 500, "voucher_balance": 100}},
            )
        )
        result = await client.get_balance()
        assert result["assets"] == 12345

    @respx.mock
    async def test_get_balance_auth_header(self, client):
        route = respx.post("https://api.autodl.com/api/v1/dev/wallet/balance").mock(
            return_value=httpx.Response(
                200,
                json={"code": "Success", "data": {"assets": 0}},
            )
        )
        await client.get_balance()
        assert route.calls[0].request.headers["Authorization"] == "test-token"


@pytest.mark.asyncio
class TestGetGpuStock:
    @respx.mock
    async def test_gpu_stock_success(self, client):
        respx.post("https://api.autodl.com/api/v1/dev/machine/region/gpu_stock").mock(
            return_value=httpx.Response(
                200,
                json={
                    "code": "Success",
                    "data": [
                        {"RTX 4090": {"idle_gpu_num": 215, "total_gpu_num": 2285}},
                    ],
                },
            )
        )
        result = await client.get_gpu_stock(gpu_names=["RTX 4090"])
        assert len(result) == 1
        assert "RTX 4090" in result[0]

    @respx.mock
    async def test_gpu_stock_with_region(self, client):
        route = respx.post("https://api.autodl.com/api/v1/dev/machine/region/gpu_stock").mock(
            return_value=httpx.Response(
                200,
                json={"code": "Success", "data": []},
            )
        )
        await client.get_gpu_stock(region="westDC2", gpu_names=["RTX 4090"])
        import json
        body = json.loads(route.calls[0].request.content)
        assert body["region_sign"] == "westDC2"
        assert body["gpu_name_set"] == ["RTX 4090"]


@pytest.mark.asyncio
class TestRetry:
    @respx.mock
    async def test_retries_on_timeout(self, client):
        route = respx.post("https://api.autodl.com/api/v1/dev/wallet/balance")
        route.side_effect = [
            httpx.ConnectError("timeout"),
            httpx.ConnectError("timeout"),
            httpx.Response(200, json={"code": "Success", "data": {"assets": 100}}),
        ]
        result = await client.get_balance()
        assert result["assets"] == 100
        assert route.call_count == 3

    @respx.mock
    async def test_raises_after_max_retries(self, client):
        route = respx.post("https://api.autodl.com/api/v1/dev/wallet/balance")
        route.side_effect = httpx.ConnectError("timeout")
        with pytest.raises(AutoDLNetworkError, match="failed after 3 retries"):
            await client.get_balance()


@pytest.mark.asyncio
class TestDeployment:
    @respx.mock
    async def test_create_deployment(self, client):
        respx.post("https://api.autodl.com/api/v1/dev/deployment").mock(
            return_value=httpx.Response(
                200,
                json={"code": "Success", "data": {"deployment_uuid": "dep-abc123"}},
            )
        )
        result = await client.create_deployment({"name": "test"})
        assert result == "dep-abc123"

    @respx.mock
    async def test_stop_deployment(self, client):
        route = respx.put("https://api.autodl.com/api/v1/dev/deployment/operate").mock(
            return_value=httpx.Response(
                200,
                json={"code": "Success", "data": {}},
            )
        )
        await client.stop_deployment("dep-abc123")
        import json
        body = json.loads(route.calls[0].request.content)
        assert body["operate"] == "stop"
