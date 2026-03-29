"""AutoDL provider: business logic using Container Instance Pro + SSH."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from gpu_hire.providers.autodl.client import AutoDLClient
from gpu_hire.providers.autodl.constants import (
    BASE_IMAGE_UUIDS,
    GPU_SPEC_DISPLAY,
    GPU_SPEC_UUIDS,
)
from gpu_hire.providers.autodl.ssh_runner import check_job, get_log_tail, start_job
from gpu_hire.providers.base import Balance, GPUOffer, Job, JobStatus

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 10
DEFAULT_TIMEOUT_MINUTES = 60
INSTANCE_START_TIMEOUT_SECONDS = 180


class JobTimeoutError(Exception):
    def __init__(self, job_id: str, timeout_minutes: int):
        self.job_id = job_id
        super().__init__(
            f"Job {job_id} did not finish within {timeout_minutes} minutes. "
            f"The job is still running — use get_job_status to check later."
        )


class InstanceStartTimeoutError(Exception):
    def __init__(self, instance_uuid: str):
        super().__init__(
            f"Instance {instance_uuid} did not reach 'running' within "
            f"{INSTANCE_START_TIMEOUT_SECONDS}s. It may still be starting."
        )


def resolve_image_uuid(image: str) -> str:
    if image.startswith("image-") or image.startswith("base-image-"):
        return image
    uuid = BASE_IMAGE_UUIDS.get(image)
    if uuid is None:
        raise ValueError(
            f"Unknown image alias: {image!r}. "
            f"Available: {', '.join(BASE_IMAGE_UUIDS.keys())}. "
            f"Or pass an image UUID directly (e.g. 'image-xxx' or 'base-image-xxx')."
        )
    return uuid


def resolve_gpu_spec_uuid(gpu_type: str) -> str:
    """Resolve a GPU type name to a Pro instance spec UUID."""
    if gpu_type in GPU_SPEC_DISPLAY:
        return gpu_type
    uuid = GPU_SPEC_UUIDS.get(gpu_type)
    if uuid is None:
        available = sorted(set(GPU_SPEC_UUIDS.keys()))
        raise ValueError(
            f"Unknown GPU type for Pro instance: {gpu_type!r}. "
            f"Available: {', '.join(available)}"
        )
    return uuid


class AutoDLProvider:
    def __init__(self, token: str):
        self.client = AutoDLClient(token)

    async def close(self):
        await self.client.close()

    # ------------------------------------------------------------------ #
    # GPU availability                                                     #
    # ------------------------------------------------------------------ #

    async def list_gpu_availability(
        self,
        gpu_type: str | None = None,
        region: str | None = None,
    ) -> list[GPUOffer]:
        gpu_names = [gpu_type] if gpu_type else None
        stock_data = await self.client.get_gpu_stock(
            region=region, gpu_names=gpu_names
        )
        offers: list[GPUOffer] = []
        for item in stock_data:
            if isinstance(item, dict):
                for gpu_name, info in item.items():
                    if isinstance(info, dict):
                        idle = info.get("idle_gpu_num", 0)
                        item_region = info.get("_region", region or "auto")
                        if idle > 0:
                            offers.append(
                                GPUOffer(
                                    gpu_name=gpu_name,
                                    gpu_count=idle,
                                    region=item_region,
                                    price_per_hour=0.0,
                                )
                            )
        offers.sort(key=lambda o: o.gpu_count, reverse=True)
        return offers

    # ------------------------------------------------------------------ #
    # Job submission via Container Instance Pro + SSH                     #
    # ------------------------------------------------------------------ #

    async def submit_job(
        self,
        cmd: str,
        gpu_type: str,
        image: str,
        gpu_count: int = 1,
        cuda_v_from: int = 118,
        regions: list[str] | None = None,
        env_vars: dict[str, str] | None = None,
        max_concurrent: int = 3,
    ) -> Job:
        # 0. Guard: check concurrent instance count
        active = await self.client.list_instances()
        if len(active) >= max_concurrent:
            ids = [i.get("uuid", i.get("instance_uuid", "?")) for i in active]
            raise RuntimeError(
                f"Already {len(active)} active instance(s): {ids}. "
                f"Stop them first or raise max_concurrent (current limit: {max_concurrent})."
            )

        # 1. Check balance
        balance_data = await self.client.get_balance()
        available = balance_data.get("assets", 0) / 1000
        if available < 5:
            logger.warning("Low balance: %.2f CNY", available)

        # 2. Resolve spec UUID and image UUID
        gpu_spec_uuid = resolve_gpu_spec_uuid(gpu_type)
        image_uuid = resolve_image_uuid(image)

        # 3. Build command
        wrapped_cmd = cmd
        if env_vars:
            env_prefix = " ".join(f"{k}={v}" for k, v in env_vars.items())
            wrapped_cmd = f"{env_prefix} {cmd}"

        # 4. Create instance
        payload: dict = {
            "req_gpu_amount": gpu_count,
            "gpu_spec_uuid": gpu_spec_uuid,
            "image_uuid": image_uuid,
            "cuda_v_from": cuda_v_from,
            "expand_system_disk_by_gb": 0,
        }
        if regions:
            payload["data_center_list"] = regions

        instance_uuid = await self.client.create_instance(payload)
        created_at = datetime.now(timezone.utc)
        gpu_display = GPU_SPEC_DISPLAY.get(gpu_spec_uuid, gpu_type)
        logger.info("Created instance %s (%s)", instance_uuid, gpu_display)

        # 5. Wait for "running"
        deadline = asyncio.get_event_loop().time() + INSTANCE_START_TIMEOUT_SECONDS
        while asyncio.get_event_loop().time() < deadline:
            status = await self.client.get_instance_status(instance_uuid)
            if status == "running":
                break
            await asyncio.sleep(5)
        else:
            raise InstanceStartTimeoutError(instance_uuid)

        # 6. Get SSH credentials
        snapshot = await self.client.get_instance_snapshot(instance_uuid)
        host = snapshot.get("proxy_host", "")
        port = snapshot.get("ssh_port", 22)
        password = snapshot.get("root_password", "")

        # 7. Start job in background via SSH
        await start_job(host, port, password, wrapped_cmd)
        logger.info("Job started on instance %s", instance_uuid)

        return Job(
            job_id=instance_uuid,
            status=JobStatus.RUNNING,
            gpu_type=gpu_display,
            gpu_count=gpu_count,
            cmd=cmd,
            created_at=created_at,
            ssh_command=f"ssh -p {port} root@{host}",
            ssh_password=password,
        )

    # ------------------------------------------------------------------ #
    # Job status                                                          #
    # ------------------------------------------------------------------ #

    async def get_job_status(self, job_id: str) -> Job:
        """Check status via instance API + SSH. Auto-releases instance when done."""
        instance_uuid = job_id

        instance_status = await self.client.get_instance_status(instance_uuid)

        if instance_status not in ("running", "creating"):
            return Job(
                job_id=job_id,
                status=JobStatus.STOPPED,
                gpu_type="",
                gpu_count=0,
                cmd="",
                created_at=datetime.now(timezone.utc),
                finished_at=datetime.now(timezone.utc),
            )

        snapshot = await self.client.get_instance_snapshot(instance_uuid)
        host = snapshot.get("proxy_host", "")
        port = snapshot.get("ssh_port", 22)
        password = snapshot.get("root_password", "")

        ssh_result, exit_code = await check_job(host, port, password)

        if ssh_result == "running":
            return Job(
                job_id=job_id,
                status=JobStatus.RUNNING,
                gpu_type=snapshot.get("snapshot_gpu_alias_name", ""),
                gpu_count=0,
                cmd="",
                created_at=datetime.now(timezone.utc),
            )

        # Finished — power off and release
        finished_at = datetime.now(timezone.utc)
        job_status = JobStatus.SUCCEEDED if exit_code == 0 else JobStatus.FAILED

        logger.info(
            "Job %s finished: %s (exit_code=%s) — releasing instance",
            job_id, job_status.value, exit_code,
        )
        await self._release_instance(instance_uuid)

        return Job(
            job_id=job_id,
            status=job_status,
            gpu_type=snapshot.get("snapshot_gpu_alias_name", ""),
            gpu_count=0,
            cmd="",
            created_at=datetime.now(timezone.utc),
            finished_at=finished_at,
        )

    async def _release_instance(self, instance_uuid: str) -> None:
        try:
            await self.client.power_off_instance(instance_uuid)
            await asyncio.sleep(8)
            await self.client.release_instance(instance_uuid)
        except Exception as exc:
            logger.warning("Failed to release instance %s: %s", instance_uuid, exc)

    # ------------------------------------------------------------------ #
    # Stop job                                                            #
    # ------------------------------------------------------------------ #

    async def stop_job(self, job_id: str) -> None:
        """Force-stop a job by powering off and releasing its instance."""
        await self._release_instance(job_id)

    # ------------------------------------------------------------------ #
    # Wait helper                                                         #
    # ------------------------------------------------------------------ #

    async def wait_for_job(
        self,
        job_id: str,
        poll_interval: int = POLL_INTERVAL_SECONDS,
        timeout_minutes: int = DEFAULT_TIMEOUT_MINUTES,
    ) -> Job:
        deadline = asyncio.get_event_loop().time() + timeout_minutes * 60
        while asyncio.get_event_loop().time() < deadline:
            job = await self.get_job_status(job_id)
            if job.status in (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.STOPPED):
                return job
            await asyncio.sleep(poll_interval)
        raise JobTimeoutError(job_id, timeout_minutes)

    # ------------------------------------------------------------------ #
    # List active instances                                               #
    # ------------------------------------------------------------------ #

    async def list_active_instances(self) -> list[dict]:
        results: list[dict] = []
        instances = await self.client.list_instances()
        for inst in instances:
            if isinstance(inst, dict):
                results.append({
                    "id": inst.get("instance_uuid", inst.get("uuid", "")),
                    "type": "instance",
                    "gpu_type": inst.get("gpu_type", ""),
                    "status": inst.get("status", ""),
                    "cost_per_hour": inst.get("payg_price", 0) / 1000,
                })
        return results

    # ------------------------------------------------------------------ #
    # Balance                                                             #
    # ------------------------------------------------------------------ #

    async def get_balance(self) -> Balance:
        data = await self.client.get_balance()
        return Balance(
            available_cny=data.get("assets", 0) / 1000,
            voucher_cny=data.get("voucher_balance", 0) / 1000,
            total_spent_cny=data.get("accumulate", 0) / 1000,
        )

    # ------------------------------------------------------------------ #
    # Job log                                                             #
    # ------------------------------------------------------------------ #

    async def get_job_log(self, job_id: str, lines: int = 50) -> str:
        """Fetch the last N lines of a running job's output log."""
        snapshot = await self.client.get_instance_snapshot(job_id)
        host = snapshot.get("proxy_host", "")
        port = snapshot.get("ssh_port", 22)
        password = snapshot.get("root_password", "")
        return await get_log_tail(host, port, password, lines)
