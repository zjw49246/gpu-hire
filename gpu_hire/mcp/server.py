"""MCP Server exposing AutoDL GPU rental tools."""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from gpu_hire.providers.autodl.provider import AutoDLProvider

mcp = FastMCP(
    "gpu-hire",
    instructions=(
        "GPU rental automation for AutoDL. "
        "Use autodl_check_balance and autodl_check_gpu_availability before submitting jobs. "
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
    """Query AutoDL GPU stock and prices across regions.

    Returns available GPUs with gpu_name (use this value for autodl_submit_job).
    Call before submitting jobs to confirm availability, or to compare GPU options.

    Args:
        gpu_type: GPU model name (e.g. "RTX 4090"). Omit to list all models.
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
) -> dict:
    """Submit a GPU batch job on AutoDL (Elastic Deployment Job mode).

    The job runs to completion and releases resources automatically.
    Billed per second of actual runtime.

    Good for: training, evaluation, batch inference (non-interactive tasks).
    Not for: JupyterLab or interactive debugging.

    WARNING: This incurs costs. RTX 4090 is ~1.98 CNY/hour.

    Args:
        cmd: Command to run, e.g. "python train.py --epochs 10".
        gpu_type: GPU model — must be a gpu_name from autodl_check_gpu_availability.
        image: Image alias (e.g. "pytorch-cuda11.8") or image UUID.
        gpu_count: Number of GPUs (default 1).
        regions: Preferred regions. Omit for auto-selection.
        env_vars: Environment variables injected securely into the job.
    """
    provider = _get_provider()
    job = await provider.submit_job(
        cmd=cmd,
        gpu_type=gpu_type,
        image=image,
        gpu_count=gpu_count,
        regions=regions,
        env_vars=env_vars,
    )
    return job.model_dump(mode="json")


@mcp.tool()
async def autodl_get_job_status(job_id: str) -> dict:
    """Check the current status of an AutoDL job.

    For completed jobs, also returns duration and cost.

    Args:
        job_id: The job_id returned by autodl_submit_job.
    """
    provider = _get_provider()
    job = await provider.get_job_status(job_id)
    return job.model_dump(mode="json")


@mcp.tool()
async def autodl_list_instances() -> list[dict]:
    """List all active AutoDL instances and deployments (resources currently billing).

    Use this to check for forgotten instances that are still incurring costs.
    """
    provider = _get_provider()
    return await provider.list_active_instances()


@mcp.tool()
async def autodl_check_balance() -> dict:
    """Check AutoDL account balance. Call before submitting jobs to confirm sufficient funds.

    Returns balance in CNY (Chinese Yuan).
    """
    provider = _get_provider()
    balance = await provider.get_balance()
    return balance.model_dump()


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
