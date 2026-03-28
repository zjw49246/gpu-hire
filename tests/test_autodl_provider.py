"""Tests for AutoDL provider business logic."""

import pytest
import httpx
import respx

from gpu_hire.providers.autodl.provider import (
    AutoDLProvider,
    JobTimeoutError,
    resolve_image_uuid,
)
from gpu_hire.providers.base import JobStatus


class TestResolveImageUuid:
    def test_known_alias(self):
        assert resolve_image_uuid("pytorch-cuda11.8") == "base-image-l2t43iu6uk"

    def test_direct_uuid(self):
        assert resolve_image_uuid("image-db8346e037") == "image-db8346e037"

    def test_direct_base_image_uuid(self):
        assert resolve_image_uuid("base-image-abc") == "base-image-abc"

    def test_unknown_alias(self):
        with pytest.raises(ValueError, match="Unknown image alias"):
            resolve_image_uuid("nonexistent")


@pytest.fixture
def provider():
    return AutoDLProvider(token="test-token")


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
class TestListGpuAvailability:
    @respx.mock
    async def test_returns_offers(self, provider):
        _mock_gpu_stock(idle=50)
        offers = await provider.list_gpu_availability(gpu_type="RTX 4090")
        assert len(offers) == 1
        assert offers[0].gpu_name == "RTX 4090"
        assert offers[0].gpu_count == 50

    @respx.mock
    async def test_filters_zero_idle(self, provider):
        _mock_gpu_stock(idle=0)
        offers = await provider.list_gpu_availability(gpu_type="RTX 4090")
        assert len(offers) == 0


@pytest.mark.asyncio
class TestSubmitJob:
    @respx.mock
    async def test_submit_job_success(self, provider):
        _mock_balance()
        _mock_gpu_stock(idle=10)
        respx.post("https://api.autodl.com/api/v1/dev/deployment").mock(
            return_value=httpx.Response(
                200, json={"code": "Success", "data": {"deployment_uuid": "dep-test123"}}
            )
        )

        job = await provider.submit_job(
            cmd="python train.py",
            gpu_type="RTX 4090",
            image="pytorch-cuda11.8",
        )
        assert job.job_id == "dep-test123"
        assert job.status == JobStatus.PENDING
        assert job.gpu_type == "RTX 4090"

    @respx.mock
    async def test_submit_job_no_gpu(self, provider):
        _mock_balance()
        _mock_gpu_stock(idle=0)

        from gpu_hire.providers.autodl.client import NoGPUAvailableError

        with pytest.raises(NoGPUAvailableError):
            await provider.submit_job(
                cmd="python train.py",
                gpu_type="RTX 4090",
                image="pytorch-cuda11.8",
            )


@pytest.mark.asyncio
class TestGetJobStatus:
    @respx.mock
    async def test_running_status(self, provider):
        respx.post("https://api.autodl.com/api/v1/dev/deployment/container/list").mock(
            return_value=httpx.Response(
                200,
                json={
                    "code": "Success",
                    "data": {
                        "list": [{"events": [{"type": "container_running"}]}]
                    },
                },
            )
        )
        job = await provider.get_job_status("dep-123")
        assert job.status == JobStatus.RUNNING

    @respx.mock
    async def test_succeeded_status(self, provider):
        respx.post("https://api.autodl.com/api/v1/dev/deployment/container/list").mock(
            return_value=httpx.Response(
                200,
                json={
                    "code": "Success",
                    "data": {
                        "list": [{"events": [{"type": "container_exited_0"}]}]
                    },
                },
            )
        )
        job = await provider.get_job_status("dep-123")
        assert job.status == JobStatus.SUCCEEDED
        assert job.finished_at is not None

    @respx.mock
    async def test_failed_status(self, provider):
        respx.post("https://api.autodl.com/api/v1/dev/deployment/container/list").mock(
            return_value=httpx.Response(
                200,
                json={
                    "code": "Success",
                    "data": {
                        "list": [{"events": [{"type": "container_exited_1"}]}]
                    },
                },
            )
        )
        job = await provider.get_job_status("dep-123")
        assert job.status == JobStatus.FAILED

    @respx.mock
    async def test_pending_no_events(self, provider):
        respx.post("https://api.autodl.com/api/v1/dev/deployment/container/list").mock(
            return_value=httpx.Response(
                200,
                json={"code": "Success", "data": {"list": [{"events": []}]}},
            )
        )
        job = await provider.get_job_status("dep-123")
        assert job.status == JobStatus.PENDING


@pytest.mark.asyncio
class TestGetBalance:
    @respx.mock
    async def test_balance_conversion(self, provider):
        _mock_balance(assets=23500)
        balance = await provider.get_balance()
        assert balance.available_cny == 23.5
