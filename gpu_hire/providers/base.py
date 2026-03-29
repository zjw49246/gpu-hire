"""Shared data models for all GPU providers."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class GPUOffer(BaseModel):
    gpu_name: str
    gpu_count: int
    region: str
    price_per_hour: float


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    STOPPED = "stopped"


class Job(BaseModel):
    job_id: str
    provider: str = "autodl"
    status: JobStatus
    gpu_type: str
    gpu_count: int
    cmd: str
    created_at: datetime
    finished_at: datetime | None = None
    cost_cny: float | None = None
    ssh_command: str | None = None   # e.g. "ssh -p 12345 root@connect.westd.seetacloud.com"
    ssh_password: str | None = None


class Instance(BaseModel):
    instance_id: str
    provider: str = "autodl"
    status: str
    gpu_type: str
    gpu_count: int
    ssh_host: str
    ssh_port: int
    ssh_password: str
    cost_per_hour: float
    created_at: datetime


class Balance(BaseModel):
    available_cny: float
    voucher_cny: float
    total_spent_cny: float
