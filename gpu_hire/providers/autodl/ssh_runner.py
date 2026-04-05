"""SSH-based job runner for AutoDL container instances."""

from __future__ import annotations

import asyncssh

# Scripts run inside the container

_START_SCRIPT = """\
mkdir -p /root/gpu-hire
cat > /root/gpu-hire/run.sh << 'GPU_HIRE_EOF'
{cmd}
GPU_HIRE_EOF
chmod +x /root/gpu-hire/run.sh
nohup bash -c 'bash /root/gpu-hire/run.sh > /root/gpu-hire/output.log 2>&1; echo $? > /root/gpu-hire/exit_code' &
echo $! > /root/gpu-hire/pid
echo "started"
"""

_CHECK_SCRIPT = """\
if [ -f /root/gpu-hire/exit_code ]; then
    echo "done:$(cat /root/gpu-hire/exit_code)"
elif [ -f /root/gpu-hire/pid ] && kill -0 $(cat /root/gpu-hire/pid) 2>/dev/null; then
    echo "running"
elif [ ! -f /root/gpu-hire/pid ]; then
    echo "idle"
else
    echo "unknown"
fi
"""

_TAIL_LOG_SCRIPT = "tail -n {n} /root/gpu-hire/output.log 2>/dev/null || echo '(no output yet)'"


async def start_job(host: str, port: int, password: str, cmd: str) -> None:
    """SSH into the instance and start the job in the background."""
    script = _START_SCRIPT.format(cmd=cmd)
    async with asyncssh.connect(
        host, port=port,
        username="root", password=password,
        known_hosts=None,
        connect_timeout=30,
    ) as conn:
        result = await conn.run(script, check=False)
        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to start job on {host}:{port}\n"
                f"stderr: {result.stderr}\nstdout: {result.stdout}"
            )


async def check_job(host: str, port: int, password: str) -> tuple[str, int | None]:
    """Check job status via SSH.

    Returns:
        ("running", None)          — job still running
        ("done", exit_code)        — job finished; exit_code=0 → success
        ("idle", None)             — no job started yet (no pid file)
        ("unknown", None)          — process died without writing exit code
    """
    async with asyncssh.connect(
        host, port=port,
        username="root", password=password,
        known_hosts=None,
        connect_timeout=30,
    ) as conn:
        result = await conn.run(_CHECK_SCRIPT, check=False)
        output = result.stdout.strip()

    if output.startswith("done:"):
        try:
            code = int(output.split(":", 1)[1])
        except ValueError:
            code = 1
        return "done", code
    if output == "running":
        return "running", None
    if output == "idle":
        return "idle", None
    return "unknown", None


async def get_log_tail(host: str, port: int, password: str, lines: int = 50) -> str:
    """Fetch the last N lines of job output log."""
    script = _TAIL_LOG_SCRIPT.format(n=lines)
    async with asyncssh.connect(
        host, port=port,
        username="root", password=password,
        known_hosts=None,
        connect_timeout=30,
    ) as conn:
        result = await conn.run(script, check=False)
        return result.stdout
