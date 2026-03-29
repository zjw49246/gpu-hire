"""MCP Server exposing AutoDL GPU rental tools."""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from gpu_hire.providers.autodl.provider import AutoDLProvider

mcp = FastMCP(
    "gpu-hire",
    instructions=(
        "GPU rental automation for AutoDL. "
        "Typical workflow: check_balance → check_gpu_availability → submit_job → "
        "poll get_job_status until succeeded/failed. "
        "get_job_log lets you inspect output while the job is running. "
        "All costs are in CNY (Chinese Yuan)."
    ),
)

_provider: AutoDLProvider | None = None


def _get_provider() -> AutoDLProvider:
    global _provider
    if _provider is None:
        token = os.environ.get("AUTODL_TOKEN", "")
        if not token:
            raise RuntimeError(
                "AUTODL_TOKEN environment variable is not set. "
                "Get your token from AutoDL console -> Account Settings -> Developer Token."
            )
        _provider = AutoDLProvider(token)
    return _provider


@mcp.tool()
async def autodl_check_gpu_availability(
    gpu_type: str | None = None,
    region: str | None = None,
) -> list[dict]:
    """Query AutoDL GPU stock across regions.

    Returns available GPUs. Use the gpu_name value for autodl_submit_job.
    Call before submitting jobs to confirm availability.

    Args:
        gpu_type: GPU model (e.g. "RTX 4090"). Omit to list all.
        region: Region code (e.g. "westDC2"). Omit to query all regions.
    """
    provider = _get_provider()
    offers = await provider.list_gpu_availability(gpu_type=gpu_type, region=region)
    return [offer.model_dump() for offer in offers]


@mcp.tool()
async def autodl_submit_job(
    cmd: str,
    gpu_type: str,
    image: str,
    gpu_count: int = 1,
    regions: list[str] | None = None,
    env_vars: dict[str, str] | None = None,
    max_concurrent: int = 3,
) -> dict:
    """Submit a GPU job on AutoDL via Container Instance Pro.

    Creates an instance, waits for it to start (~1 min), SSHs in and runs
    the command in the background. Returns immediately with job_id.
    Poll autodl_get_job_status to track progress.
    Instance is automatically released when the job finishes.

    Raises an error if active instances >= max_concurrent to prevent accidental
    runaway billing.

    WARNING: Incurs cost. RTX 3090 ≈ 1.87 CNY/hr.

    Supported gpu_type values: RTX 3090, RTX 4090, RTX 5090, RTX PRO 6000,
    RTX 4080S, H800, vGPU-32GB, vGPU-48GB, vGPU-48GB-350W.

    Args:
        cmd: Shell command to run, e.g. "python train.py --epochs 10".
        gpu_type: GPU model name (see supported values above).
        image: Image alias (e.g. "pytorch-cuda11.8") or image UUID.
        gpu_count: Number of GPUs (default 1).
        regions: Preferred region codes. Omit for auto-selection.
        env_vars: Environment variables injected into the job.
        max_concurrent: Max allowed active instances before rejecting (default 3).
    """
    provider = _get_provider()
    job = await provider.submit_job(
        cmd=cmd,
        gpu_type=gpu_type,
        image=image,
        gpu_count=gpu_count,
        regions=regions,
        env_vars=env_vars,
        max_concurrent=max_concurrent,
    )
    return job.model_dump(mode="json")


@mcp.tool()
async def autodl_get_job_status(job_id: str) -> dict:
    """Check the current status of an AutoDL job.

    Automatically releases the instance (stops billing) when the job succeeds or fails.

    Args:
        job_id: The job_id returned by autodl_submit_job.
    """
    provider = _get_provider()
    job = await provider.get_job_status(job_id)
    return job.model_dump(mode="json")


@mcp.tool()
async def autodl_get_job_log(job_id: str, lines: int = 50) -> str:
    """Fetch the last N lines of a running job's output log.

    Useful for checking training progress without waiting for completion.

    Args:
        job_id: The job_id returned by autodl_submit_job.
        lines: Number of log lines to return (default 50).
    """
    provider = _get_provider()
    return await provider.get_job_log(job_id, lines=lines)


@mcp.tool()
async def autodl_stop_job(job_id: str) -> dict:
    """Force-stop a running AutoDL job and release the instance.

    Use this to stop a job early and avoid further billing.

    Args:
        job_id: The job_id returned by autodl_submit_job.
    """
    provider = _get_provider()
    await provider.stop_job(job_id)
    return {"job_id": job_id, "status": "stopped"}


@mcp.tool()
async def autodl_list_instances() -> list[dict]:
    """List all active AutoDL instances (resources currently billing).

    Use this to check for forgotten instances to avoid unexpected charges.
    """
    provider = _get_provider()
    return await provider.list_active_instances()


@mcp.tool()
async def autodl_check_balance() -> dict:
    """Check AutoDL account balance in CNY. Call before submitting jobs.

    Returns available balance and voucher balance.
    """
    provider = _get_provider()
    balance = await provider.get_balance()
    return balance.model_dump()


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
