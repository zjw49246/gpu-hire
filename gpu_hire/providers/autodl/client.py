"""AutoDL HTTP client with auth, retries, and structured error handling."""

from __future__ import annotations

import httpx

# --- Exceptions ---


class AutoDLAPIError(Exception):
    def __init__(self, code: str, msg: str):
        self.code = code
        self.msg = msg
        super().__init__(f"AutoDL API error [{code}]: {msg}")


class InsufficientBalanceError(AutoDLAPIError):
    def __init__(self, msg: str, balance: float | None = None):
        self.balance = balance
        super().__init__("BALANCE_NOT_ENOUGH", msg)


class NoGPUAvailableError(AutoDLAPIError):
    def __init__(self, gpu_name: str, region: str | None = None):
        self.gpu_name = gpu_name
        self.region = region
        detail = f"{gpu_name} in {region}" if region else gpu_name
        super().__init__("GPU_STOCK_NOT_ENOUGH", f"No idle GPUs: {detail}")


class InstanceNotFoundError(AutoDLAPIError):
    def __init__(self, instance_id: str):
        super().__init__("INSTANCE_NOT_FOUND", f"Instance not found: {instance_id}")


class AutoDLNetworkError(Exception):
    pass


# --- Client ---

_MAX_RETRIES = 3
_TIMEOUT = 30.0


class AutoDLClient:
    BASE_URL = "https://api.autodl.com"
    LEGACY_URL = "https://www.autodl.com"

    def __init__(self, token: str):
        self._token = token
        self._http = httpx.AsyncClient(
            headers={"Authorization": token},
            timeout=_TIMEOUT,
        )

    async def close(self):
        await self._http.aclose()

    # --- internal helpers ---

    async def _request(
        self,
        method: str,
        url: str,
        *,
        json: dict | None = None,
    ) -> dict:
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                resp = await self._http.request(method, url, json=json)
                resp.raise_for_status()
                data = resp.json()
                return self._check_response(data)
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES - 1:
                    import asyncio
                    await asyncio.sleep(2 ** attempt)
            except httpx.HTTPStatusError as exc:
                raise AutoDLNetworkError(
                    f"HTTP {exc.response.status_code}: {exc.response.text}"
                ) from exc
        raise AutoDLNetworkError(
            f"Request failed after {_MAX_RETRIES} retries"
        ) from last_exc

    @staticmethod
    def _check_response(data: dict) -> dict:
        code = data.get("code", "")
        if code == "Success":
            return data.get("data", {})
        msg = data.get("msg", data.get("message", str(data)))
        if code == "BALANCE_NOT_ENOUGH":
            raise InsufficientBalanceError(msg)
        if code == "GPU_STOCK_NOT_ENOUGH":
            raise NoGPUAvailableError(msg)
        if code == "INSTANCE_NOT_FOUND":
            raise InstanceNotFoundError(msg)
        raise AutoDLAPIError(code, msg)

    async def _post(self, path: str, json: dict | None = None) -> dict:
        return await self._request("POST", f"{self.BASE_URL}{path}", json=json or {})

    async def _get(self, path: str, params: dict | None = None) -> dict:
        url = f"{self.BASE_URL}{path}"
        if params:
            url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
        return await self._request("GET", url)

    async def _put(self, path: str, json: dict | None = None) -> dict:
        return await self._request("PUT", f"{self.BASE_URL}{path}", json=json or {})

    async def _delete(self, path: str, json: dict | None = None) -> dict:
        return await self._request("DELETE", f"{self.BASE_URL}{path}", json=json)

    # --- Account ---

    async def get_balance(self) -> dict:
        return await self._post("/api/v1/dev/wallet/balance")

    async def send_wechat_notification(self, title: str, content: str) -> None:
        await self._request(
            "POST",
            f"{self.LEGACY_URL}/api/v1/wechat/message/send",
            json={"title": title, "name": title, "content": content},
        )

    # --- Elastic Deployment ---

    async def get_gpu_stock(
        self,
        region: str | None = None,
        gpu_names: list[str] | None = None,
        cuda_v_from: int = 118,
        cuda_v_to: int = 125,
    ) -> list[dict]:
        # region_sign is required by the API; query all known regions when not specified
        from gpu_hire.providers.autodl.constants import REGIONS
        regions = [region] if region else REGIONS

        results: list[dict] = []
        for r in regions:
            payload: dict = {"region_sign": r}
            if cuda_v_from:
                payload["cuda_v_from"] = cuda_v_from
            if cuda_v_to:
                payload["cuda_v_to"] = cuda_v_to
            if gpu_names:
                payload["gpu_name_set"] = gpu_names
            try:
                data = await self._post("/api/v1/dev/machine/region/gpu_stock", json=payload)
                items = data if isinstance(data, list) else []
                for item in items:
                    if isinstance(item, dict):
                        for gpu_name, info in item.items():
                            if isinstance(info, dict):
                                results.append({gpu_name: {**info, "_region": r}})
            except Exception:
                continue
        return results

    async def create_deployment(self, payload: dict) -> str:
        data = await self._post("/api/v1/dev/deployment", json=payload)
        return data.get("deployment_uuid", "")

    async def list_deployments(
        self, page: int = 1, size: int = 20, status: str | None = None
    ) -> list[dict]:
        payload: dict = {"page_index": page, "page_size": size}
        if status:
            payload["status"] = status
        data = await self._post("/api/v1/dev/deployment/list", json=payload)
        return data if isinstance(data, list) else data.get("list", [])

    async def get_deployment_containers(self, deployment_uuid: str) -> list[dict]:
        data = await self._post(
            "/api/v1/dev/deployment/container/list",
            json={"deployment_uuid": deployment_uuid, "page_index": 1, "page_size": 20},
        )
        return data if isinstance(data, list) else data.get("list", [])

    async def get_container_events(self, deployment_uuid: str) -> list[dict]:
        containers = await self.get_deployment_containers(deployment_uuid)
        if not containers:
            return []
        # Return events from the first container
        container = containers[0] if isinstance(containers, list) else containers
        return container.get("events", [])

    async def stop_deployment(self, deployment_uuid: str) -> None:
        await self._put(
            "/api/v1/dev/deployment/operate",
            json={"deployment_uuid": deployment_uuid, "operate": "stop"},
        )

    async def delete_deployment(self, deployment_uuid: str) -> None:
        await self._delete(
            "/api/v1/dev/deployment",
            json={"deployment_uuid": deployment_uuid},
        )

    # --- Instance Pro (Phase 2 stubs) ---

    async def create_instance(self, payload: dict) -> str:
        # API returns instance_uuid as a plain string in data, not a dict
        data = await self._post("/api/v1/dev/instance/pro/create", json=payload)
        return data if isinstance(data, str) else data.get("instance_uuid", "")

    async def get_instance_status(self, instance_uuid: str) -> str:
        # API returns status as a plain string in data, e.g. "running"
        data = await self._get(
            "/api/v1/dev/instance/pro/status",
            params={"instance_uuid": instance_uuid},
        )
        return data if isinstance(data, str) else data.get("status", "unknown")

    async def get_instance_snapshot(self, instance_uuid: str) -> dict:
        return await self._get(
            "/api/v1/dev/instance/pro/snapshot",
            params={"instance_uuid": instance_uuid},
        )

    async def list_instances(self, page: int = 1, size: int = 20) -> list[dict]:
        data = await self._post(
            "/api/v1/dev/instance/pro/list",
            json={"page_index": page, "page_size": size},
        )
        return data if isinstance(data, list) else data.get("list", [])

    async def power_on_instance(self, instance_uuid: str) -> None:
        await self._post(
            "/api/v1/dev/instance/pro/power_on",
            json={"instance_uuid": instance_uuid, "payload": "gpu"},
        )

    async def power_off_instance(self, instance_uuid: str) -> None:
        await self._post(
            "/api/v1/dev/instance/pro/power_off",
            json={"instance_uuid": instance_uuid},
        )

    async def release_instance(self, instance_uuid: str) -> None:
        await self._post(
            "/api/v1/dev/instance/pro/release",
            json={"instance_uuid": instance_uuid},
        )
