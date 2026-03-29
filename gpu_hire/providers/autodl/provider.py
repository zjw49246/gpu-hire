"""AutoDL provider: business logic layer on top of the HTTP client."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from gpu_hire.providers.autodl.client import AutoDLClient, NoGPUAvailableError
from gpu_hire.providers.autodl.constants import BASE_IMAGE_UUIDS
from gpu_hire.providers.base import Balance, GPUOffer, Job, JobStatus

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 10
DEFAULT_TIMEOUT_MINUTES = 60

EVENT_TO_STATUS: dict[str, JobStatus] = {
    "container_running": JobStatus.RUNNING,
    "container_exited_0": JobStatus.SUCCEEDED,
    "container_stopped": JobStatus.STOPPED,
}


class JobTimeoutError(Exception):
    def __init__(self, job_id: str, timeout_minutes: int):
        self.job_id = job_id
        super().__init__(
            f"Job {job_id} did not finish within {timeout_minutes} minutes. "
            f"The job is still running — use get_job_status to check later."
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


class AutoDLProvider:
    def __init__(self, token: str):
        self.client = AutoDLClient(token)

    async def close(self):
        await self.client.close()

    # --- GPU availability ---

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
                                    price_per_hour=0.0,  # stock API doesn't return price
                                )
                            )
        offers.sort(key=lambda o: o.gpu_count, reverse=True)
        return offers

    # --- Job submission ---

    async def submit_job(
        self,
        cmd: str,
        gpu_type: str,
        image: str,
        gpu_count: int = 1,
        cuda_v_from: int = 118,
        cuda_v_to: int = 125,
        regions: list[str] | None = None,
        env_vars: dict[str, str] | None = None,
    ) -> Job:
        # Check balance
        balance_data = await self.client.get_balance()
        available = balance_data.get("assets", 0) / 1000
        if available < 5:
            logger.warning("Low balance: %.2f CNY", available)

        # Check GPU stock
        stock = await self.client.get_gpu_stock(gpu_names=[gpu_type])
        total_idle = 0
        for item in stock:
            if isinstance(item, dict):
                for _, info in item.items():
                    if isinstance(info, dict):
                        total_idle += info.get("idle_gpu_num", 0)
        if total_idle == 0:
            raise NoGPUAvailableError(gpu_type)

        # Resolve image
        image_uuid = resolve_image_uuid(image)

        # Build command with env vars if provided
        wrapped_cmd = cmd
        if env_vars:
            # Inline env vars in the command (Phase 1 — file storage approach deferred)
            env_prefix = " ".join(f"{k}={v}" for k, v in env_vars.items())
            wrapped_cmd = f"{env_prefix} {cmd}"

        # Create deployment
        payload = {
            "name": f"gpu-hire-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
            "deployment_type": "Job",
            "replica_num": 1,
            "container_template": {
                "gpu_name_set": [gpu_type],
                "gpu_num": gpu_count,
                "cuda_v_from": cuda_v_from,
                "cuda_v_to": cuda_v_to,
                "cpu_num_from": 4,
                "memory_size_from": 16,
                "price_from": 0,
                "price_to": 300,
                "image_uuid": image_uuid,
                "cmd": wrapped_cmd,
            },
        }
        if regions:
            payload["container_template"]["dc_list"] = regions

        deployment_uuid = await self.client.create_deployment(payload)

        return Job(
            job_id=deployment_uuid,
            status=JobStatus.PENDING,
            gpu_type=gpu_type,
            gpu_count=gpu_count,
            cmd=cmd,
            created_at=datetime.now(timezone.utc),
        )

    # --- Job status ---

    async def get_job_status(self, job_id: str) -> Job:
        events = await self.client.get_container_events(job_id)
        status = JobStatus.PENDING
        finished_at = None

        if events:
            latest = events[-1] if isinstance(events, list) else events
            event_type = latest.get("type", "") if isinstance(latest, dict) else ""

            if event_type in EVENT_TO_STATUS:
                status = EVENT_TO_STATUS[event_type]
            elif event_type.startswith("container_exited_"):
                status = JobStatus.FAILED

            if status in (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.STOPPED):
                ts = latest.get("timestamp") if isinstance(latest, dict) else None
                if ts:
                    finished_at = datetime.fromtimestamp(ts, tz=timezone.utc)
                else:
                    finished_at = datetime.now(timezone.utc)

        return Job(
            job_id=job_id,
            status=status,
            gpu_type="",
            gpu_count=0,
            cmd="",
            created_at=datetime.now(timezone.utc),
            finished_at=finished_at,
        )

    # --- Wait for completion ---

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

    # --- Active instances ---

    async def list_active_instances(self) -> list[dict]:
        results: list[dict] = []

        deployments = await self.client.list_deployments(status="running")
        for dep in deployments:
            if isinstance(dep, dict):
                results.append({
                    "id": dep.get("deployment_uuid", dep.get("uuid", "")),
                    "type": "job",
                    "gpu_type": dep.get("gpu_type", ""),
                    "status": dep.get("status", ""),
                    "cost_per_hour": dep.get("cost_per_hour", 0),
                })

        instances = await self.client.list_instances()
        for inst in instances:
            if isinstance(inst, dict):
                results.append({
                    "id": inst.get("instance_uuid", inst.get("uuid", "")),
                    "type": "instance",
                    "gpu_type": inst.get("gpu_type", ""),
                    "status": inst.get("status", ""),
                    "cost_per_hour": inst.get("cost_per_hour", 0),
                })

        return results

    # --- Balance ---

    async def get_balance(self) -> Balance:
        data = await self.client.get_balance()
        return Balance(
            available_cny=data.get("assets", 0) / 1000,
            voucher_cny=data.get("voucher_balance", 0) / 1000,
            total_spent_cny=data.get("accumulate", 0) / 1000,
        )
