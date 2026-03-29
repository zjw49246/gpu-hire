"""Tests for AutoDL provider business logic."""

import pytest
import httpx
import respx

from gpu_hire.providers.autodl.provider import (
    AutoDLProvider,
    resolve_image_uuid,
    resolve_gpu_spec_uuid,
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


class TestResolveGpuSpecUuid:
    def test_known_name(self):
        assert resolve_gpu_spec_uuid("RTX 3090") == "v-48g-350w"

    def test_known_alias(self):
        assert resolve_gpu_spec_uuid("vGPU-48GB-350W") == "v-48g-350w"

    def test_direct_spec_uuid(self):
        assert resolve_gpu_spec_uuid("v-48g-350w") == "v-48g-350w"

    def test_unknown(self):
        with pytest.raises(ValueError, match="Unknown GPU type"):
            resolve_gpu_spec_uuid("RTX 2080 Ti")


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
        assert len(offers) > 0
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
    async def test_submit_job_creates_instance(self, provider):
        _mock_balance()
        # list_instances (concurrent guard) → empty
        respx.post("https://api.autodl.com/api/v1/dev/instance/pro/list").mock(
            return_value=httpx.Response(200, json={"code": "Success", "data": {"list": []}})
        )
        # create_instance
        respx.post("https://api.autodl.com/api/v1/dev/instance/pro/create").mock(
            return_value=httpx.Response(
                200, json={"code": "Success", "data": "pro-test123"}
            )
        )
        # get_instance_status → running immediately
        respx.get(url__regex=r".*/instance/pro/status.*").mock(
            return_value=httpx.Response(
                200, json={"code": "Success", "data": "running"}
            )
        )
        # get_instance_snapshot
        respx.get(url__regex=r".*/instance/pro/snapshot.*").mock(
            return_value=httpx.Response(
                200,
                json={"code": "Success", "data": {
                    "proxy_host": "connect.test.seetacloud.com",
                    "ssh_port": 12345,
                    "root_password": "testpass",
                    "snapshot_gpu_alias_name": "RTX 3090",
                    "payg_price": 1870,
                }},
            )
        )

        # Mock SSH start_job
        import unittest.mock as mock
        with mock.patch("gpu_hire.providers.autodl.provider.start_job") as mock_ssh:
            mock_ssh.return_value = None
            job = await provider.submit_job(
                cmd="python train.py",
                gpu_type="RTX 3090",
                image="pytorch-cuda11.8",
            )

        assert job.job_id == "pro-test123"
        assert job.status == JobStatus.RUNNING
        assert job.gpu_type == "RTX 3090"
        assert job.ssh_command == "ssh -p 12345 root@connect.test.seetacloud.com"
        assert job.ssh_password == "testpass"

    @respx.mock
    async def test_concurrent_guard_blocks(self, provider):
        _mock_balance()
        # list_instances returns 3 running instances
        respx.post("https://api.autodl.com/api/v1/dev/instance/pro/list").mock(
            return_value=httpx.Response(200, json={"code": "Success", "data": {
                "list": [
                    {"uuid": "pro-1", "status": "running"},
                    {"uuid": "pro-2", "status": "running"},
                    {"uuid": "pro-3", "status": "running"},
                ]
            }})
        )
        with pytest.raises(RuntimeError, match="Already 3 active instance"):
            await provider.submit_job(
                cmd="python train.py",
                gpu_type="RTX 3090",
                image="pytorch-cuda11.8",
                max_concurrent=3,
            )


@pytest.mark.asyncio
class TestGetJobStatus:
    @respx.mock
    async def test_running_status(self, provider):
        respx.get(url__regex=r".*/instance/pro/status.*").mock(
            return_value=httpx.Response(200, json={"code": "Success", "data": "running"})
        )
        respx.get(url__regex=r".*/instance/pro/snapshot.*").mock(
            return_value=httpx.Response(200, json={"code": "Success", "data": {
                "proxy_host": "test.host", "ssh_port": 22, "root_password": "pw",
                "snapshot_gpu_alias_name": "RTX 3090",
            }})
        )
        import unittest.mock as mock
        with mock.patch("gpu_hire.providers.autodl.provider.check_job") as mock_check:
            mock_check.return_value = ("running", None)
            job = await provider.get_job_status("pro-test123")

        assert job.status == JobStatus.RUNNING

    @respx.mock
    async def test_succeeded_auto_releases(self, provider):
        respx.get(url__regex=r".*/instance/pro/status.*").mock(
            return_value=httpx.Response(200, json={"code": "Success", "data": "running"})
        )
        respx.get(url__regex=r".*/instance/pro/snapshot.*").mock(
            return_value=httpx.Response(200, json={"code": "Success", "data": {
                "proxy_host": "test.host", "ssh_port": 22, "root_password": "pw",
                "snapshot_gpu_alias_name": "RTX 3090",
            }})
        )
        respx.post(url__regex=r".*/instance/pro/power_off").mock(
            return_value=httpx.Response(200, json={"code": "Success", "data": None})
        )
        respx.post(url__regex=r".*/instance/pro/release").mock(
            return_value=httpx.Response(200, json={"code": "Success", "data": None})
        )

        import unittest.mock as mock
        with mock.patch("gpu_hire.providers.autodl.provider.check_job") as mock_check:
            mock_check.return_value = ("done", 0)
            with mock.patch("asyncio.sleep"):
                job = await provider.get_job_status("pro-test123")

        assert job.status == JobStatus.SUCCEEDED
        assert job.finished_at is not None

    @respx.mock
    async def test_failed_status(self, provider):
        respx.get(url__regex=r".*/instance/pro/status.*").mock(
            return_value=httpx.Response(200, json={"code": "Success", "data": "running"})
        )
        respx.get(url__regex=r".*/instance/pro/snapshot.*").mock(
            return_value=httpx.Response(200, json={"code": "Success", "data": {
                "proxy_host": "test.host", "ssh_port": 22, "root_password": "pw",
                "snapshot_gpu_alias_name": "RTX 3090",
            }})
        )
        respx.post(url__regex=r".*/instance/pro/power_off").mock(
            return_value=httpx.Response(200, json={"code": "Success", "data": None})
        )
        respx.post(url__regex=r".*/instance/pro/release").mock(
            return_value=httpx.Response(200, json={"code": "Success", "data": None})
        )

        import unittest.mock as mock
        with mock.patch("gpu_hire.providers.autodl.provider.check_job") as mock_check:
            mock_check.return_value = ("done", 1)
            with mock.patch("asyncio.sleep"):
                job = await provider.get_job_status("pro-test123")

        assert job.status == JobStatus.FAILED

    @respx.mock
    async def test_stopped_instance(self, provider):
        respx.get(url__regex=r".*/instance/pro/status.*").mock(
            return_value=httpx.Response(200, json={"code": "Success", "data": "shutdown"})
        )
        job = await provider.get_job_status("pro-test123")
        assert job.status == JobStatus.STOPPED


@pytest.mark.asyncio
class TestGetBalance:
    @respx.mock
    async def test_balance_conversion(self, provider):
        _mock_balance(assets=23500)
        balance = await provider.get_balance()
        assert balance.available_cny == 23.5
