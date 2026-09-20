import asyncio
import logging
import time
from typing import Any

import httpx
from fastapi import HTTPException

from app.core.cache import JobCache
from app.core.config import settings

logger = logging.getLogger(__name__)

ERR_MISSING_APP_TOKEN = "FEISHU_APP_TOKEN is not configured in environment/settings."


class FeishuClient:
    def __init__(self):
        # 凭证不再在 __init__ 捕获（模块级单例会在 import 时冻结启动时刻的值，
        # 配置页保存的新凭证永远读不到）——改为 property 动态读取，保存即生效
        self._token_cache: str | None = None
        self._token_expires_at: float = 0
        # token 与签发凭证绑定：配置页热换 APP_ID/SECRET 后旧 token 立即作废（否则最长 ~2 小时内请求仍打到旧应用）
        self._token_app_id: str | None = None
        self._token_lock = asyncio.Lock()
        self.timeout = httpx.Timeout(60.0)
        # 表字段名清单缓存：table_id -> (过期时间戳, 字段名列表)，供 search 接口裁剪字段用
        self._fields_cache: dict[str, tuple] = {}

    @property
    def app_id(self) -> str | None:
        return settings.FEISHU_APP_ID

    @property
    def app_secret(self) -> str | None:
        return settings.FEISHU_APP_SECRET

    @property
    def app_token(self) -> str | None:
        return settings.FEISHU_APP_TOKEN

    def _check_app_token(self):
        if not self.app_token:
            raise ValueError(ERR_MISSING_APP_TOKEN)

    def _token_fresh(self) -> bool:
        return bool(self._token_cache and self._token_app_id == self.app_id
                    and time.time() < self._token_expires_at - 300)

    async def get_tenant_access_token(self) -> str:
        if not self.app_id or not self.app_secret:
            raise ValueError("FEISHU_APP_ID or FEISHU_APP_SECRET is not configured in environment/settings.")

        if self._token_fresh():
            return self._token_cache

        # 到期/换凭证瞬间并发请求会同时 POST 刷新（请求风暴撞限流），锁内二次检查收敛为一次
        async with self._token_lock:
            if self._token_fresh():
                return self._token_cache

            url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
            req_body = {"app_id": self.app_id, "app_secret": self.app_secret}

            async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
                try:
                    response = await client.post(url, json=req_body)
                    response.raise_for_status()
                    data = response.json()
                except Exception as e:
                    raise HTTPException(status_code=502, detail=f"Request to Feishu failed: {str(e)}")

                if data.get("code") == 0:
                    self._token_cache = data["tenant_access_token"]
                    self._token_expires_at = time.time() + data.get("expire", 7200)
                    self._token_app_id = self.app_id
                    return self._token_cache
                else:
                    raise HTTPException(status_code=502, detail=f"获取飞书 Token 失败: {data}")

    async def _execute_request_with_retry(self, client: httpx.AsyncClient, method: str, url: str, error_prefix: str, max_retries: int = 3, **kwargs) -> dict[str, Any]:
        """封装带有重试机制的 HTTP 请求，并直接返回 JSON 数据"""
        retry_count = 0
        while retry_count < max_retries:
            try:
                response = await client.request(method, url, **kwargs)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                retry_count += 1
                if retry_count >= max_retries:
                    raise HTTPException(status_code=502, detail=f"{error_prefix}请求异常 (HTTP {e.response.status_code}): {e.response.text}")
                await asyncio.sleep(2)
            except Exception as e:
                retry_count += 1
                if retry_count >= max_retries:
                    logger.exception(f"Failed after {max_retries} retries: {e}")
                    raise HTTPException(status_code=502, detail=f"{error_prefix}请求异常(已重试{max_retries}次): {str(e)}")
                await asyncio.sleep(2)
        return {}

    async def fetch_bitable_records(self, table_id: str) -> list[dict[str, Any]]:
        token = await self.get_tenant_access_token()
        self._check_app_token()

        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.app_token}/tables/{table_id}/records"
        headers = {"Authorization": f"Bearer {token}"}

        all_items: list[dict[str, Any]] = []
        page_token: str | None = None

        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
            while True:
                params: dict[str, Any] = {"page_size": 500}
                if page_token:
                    params["page_token"] = page_token

                data = await self._execute_request_with_retry(client, "GET", url, "读取飞书表格", params=params, headers=headers)

                if data.get("code") != 0:
                    raise HTTPException(status_code=502, detail=f"读取飞书表格失败: {data.get('msg')}")

                page_data = data.get("data", {})
                all_items.extend(page_data.get("items", []))

                if not page_data.get("has_more"):
                    break
                next_token = page_data.get("page_token")
                if not next_token or next_token == page_token:
                    # 服务端分页异常（has_more=True 但页码不前进）：必须终止，绝不无限循环拉第一页
                    logger.warning(f"fetch_bitable_records 分页异常（page_token 不前进），提前终止 | table={table_id}")
                    break
                page_token = next_token

        return all_items

    async def list_bitable_fields(self, table_id: str) -> list[str]:
        """获取多维表格全部字段名（内存缓存 10 分钟）。用于 search 接口按需裁剪返回字段。"""
        cached = self._fields_cache.get(table_id)
        if cached and time.time() < cached[0]:
            return cached[1]

        token = await self.get_tenant_access_token()
        self._check_app_token()
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.app_token}/tables/{table_id}/fields"
        headers = {"Authorization": f"Bearer {token}"}

        names: list[str] = []
        page_token: str | None = None
        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
            while True:
                params: dict[str, Any] = {"page_size": 100}
                if page_token:
                    params["page_token"] = page_token
                data = await self._execute_request_with_retry(client, "GET", url, "读取飞书字段清单", params=params, headers=headers)
                if data.get("code") != 0:
                    raise HTTPException(status_code=502, detail=f"读取飞书字段清单失败: {data.get('msg')}")
                page_data = data.get("data", {})
                names.extend(item.get("field_name", "") for item in page_data.get("items", []) if item.get("field_name"))
                if not page_data.get("has_more"):
                    break
                next_token = page_data.get("page_token")
                if not next_token or next_token == page_token:
                    logger.warning(f"list_bitable_fields 分页异常（page_token 不前进），提前终止 | table={table_id}")
                    break
                page_token = next_token

        # 字段清单缓存 2 分钟：字段接口偶发返回已删字段的脏数据，短 TTL 降低踩中概率
        self._fields_cache[table_id] = (time.time() + 120, names)
        return names

    async def search_bitable_records(self, table_id: str, field_names: list[str] | None = None) -> list[dict[str, Any]]:
        """按条件检索记录（POST /records/search）。field_names 指定只返回哪些字段（放 body），
        相比 GET /records 的全字段返回，可把大文本字段裁掉，大幅降低传输量。
        注意：该接口的 page_size/page_token 必须放 query 参数，放 body 会被静默忽略导致死循环。"""
        token = await self.get_tenant_access_token()
        self._check_app_token()

        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.app_token}/tables/{table_id}/records/search"
        headers = {"Authorization": f"Bearer {token}"}

        all_items: list[dict[str, Any]] = []
        page_token: str | None = None
        seen_tokens: set = set()

        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
            while True:
                params: dict[str, Any] = {"page_size": 500}
                if page_token:
                    params["page_token"] = page_token
                body: dict[str, Any] = {"field_names": field_names} if field_names else {}

                data = await self._execute_request_with_retry(client, "POST", url, "检索飞书记录", params=params, headers=headers, json=body)

                if data.get("code") != 0:
                    raise HTTPException(status_code=502, detail=f"检索飞书记录失败: {data.get('msg')}")

                page_data = data.get("data", {})
                all_items.extend(page_data.get("items", []))

                if not page_data.get("has_more"):
                    break
                page_token = page_data.get("page_token")
                # 防御：page_token 缺失或不再前进，说明服务端分页异常。必须抛错而非返回部分数据，
                # 否则调用方（岗位缓存）会把残缺列表当全量写入缓存。
                if not page_token or page_token in seen_tokens:
                    logger.warning(f"[search_bitable_records] table_id={table_id} 分页 token 异常: page_token={page_token!r}（缺失或重复），已取 {len(all_items)} 条，中止且不返回残缺数据")
                    raise HTTPException(status_code=502, detail=f"检索飞书记录失败: 分页 token 未前进（table_id={table_id}，疑似服务端分页异常），已中止，本次不返回残缺数据")
                seen_tokens.add(page_token)

        return all_items

    async def fetch_bitable_record_by_id(self, table_id: str, record_id: str) -> dict[str, Any] | None:
        token = await self.get_tenant_access_token()
        self._check_app_token()

        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.app_token}/tables/{table_id}/records/{record_id}"
        headers = {"Authorization": f"Bearer {token}"}

        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
            data = await self._execute_request_with_retry(client, "GET", url, "读取飞书单条记录", headers=headers)

            if data.get("code") != 0:
                raise HTTPException(status_code=502, detail=f"读取飞书单条记录失败: {data.get('msg')}")

            return data.get("data", {}).get("record")

    async def upload_bitable_attachment(self, file_bytes: bytes, file_name: str, parent_type: str = "bitable_image") -> str:
        token = await self.get_tenant_access_token()
        self._check_app_token()

        url = "https://open.feishu.cn/open-apis/drive/v1/medias/upload_all"
        headers = {"Authorization": f"Bearer {token}"}

        data = {
            "file_name": file_name,
            "parent_type": parent_type,
            "parent_node": self.app_token,
            "size": str(len(file_bytes))
        }
        files = {"file": (file_name, file_bytes)}

        async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
            res_data = await self._execute_request_with_retry(client, "POST", url, "上传附件到飞书", max_retries=1, headers=headers, data=data, files=files)

            if res_data.get("code") != 0:
                raise HTTPException(status_code=502, detail=f"飞书附件上传失败: {res_data.get('msg')}")

            return res_data.get("data", {}).get("file_token")

    async def get_record(self, table_id: str, record_id: str) -> dict[str, Any] | None:
        return await self.fetch_bitable_record_by_id(table_id, record_id)

    async def create_record(self, table_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        token = await self.get_tenant_access_token()
        self._check_app_token()

        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.app_token}/tables/{table_id}/records"
        headers = {"Authorization": f"Bearer {token}"}
        req_body = {"fields": fields}

        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
            data = await self._execute_request_with_retry(client, "POST", url, "创建飞书记录", max_retries=1, headers=headers, json=req_body)

            if data.get("code") != 0:
                raise HTTPException(status_code=502, detail=f"创建飞书记录失败: {data.get('msg')}")

            if table_id == settings.FEISHU_TABLE_ID_JOBS:
                new_record_id = (data.get("data", {}).get("record", {}) or {}).get("record_id", "")
                schedule_job_cache_patch(new_record_id)
            return data

    async def update_record(self, table_id: str, record_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        token = await self.get_tenant_access_token()
        self._check_app_token()

        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.app_token}/tables/{table_id}/records/{record_id}"
        headers = {"Authorization": f"Bearer {token}"}
        req_body = {"fields": fields}

        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
            data = await self._execute_request_with_retry(client, "PUT", url, "更新飞书记录", max_retries=1, headers=headers, json=req_body)

            if data.get("code") != 0:
                raise HTTPException(status_code=502, detail=f"更新飞书记录失败: {data.get('msg')}")

            if table_id == settings.FEISHU_TABLE_ID_JOBS:
                schedule_job_cache_patch(record_id)
            return data

    async def delete_record(self, table_id: str, record_id: str) -> dict[str, Any]:
        token = await self.get_tenant_access_token()
        self._check_app_token()

        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.app_token}/tables/{table_id}/records/{record_id}"
        headers = {"Authorization": f"Bearer {token}"}

        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
            data = await self._execute_request_with_retry(client, "DELETE", url, "删除飞书记录", max_retries=1, headers=headers)

            if data.get("code") != 0:
                raise HTTPException(status_code=502, detail=f"删除飞书记录失败: {data.get('msg')}")

            if table_id == settings.FEISHU_TABLE_ID_JOBS:
                JobCache.remove_records([record_id])
            return data

    # 飞书 batch_delete 单请求有记录数上限（≤500/次），超限整批拒收
    BATCH_DELETE_CHUNK_SIZE = 500

    async def batch_delete_records(self, table_id: str, record_ids: list[str]) -> dict[str, Any]:
        """分块批量删除：超过单请求上限会被飞书整批拒收，这里按小块依次提交，
        单块失败不阻断其余块；返回 {"deleted": [...], "failed": [...], "error": str|None}。"""
        if not record_ids:
            return {"deleted": [], "failed": [], "error": None}

        deleted: list[str] = []
        failed: list[str] = []
        last_error: str | None = None

        for i in range(0, len(record_ids), self.BATCH_DELETE_CHUNK_SIZE):
            chunk = record_ids[i : i + self.BATCH_DELETE_CHUNK_SIZE]
            try:
                await self._delete_records_chunk(table_id, chunk)
                deleted.extend(chunk)
            except Exception as e:
                logger.warning(f"批量删除第 {i // self.BATCH_DELETE_CHUNK_SIZE + 1} 块（{len(chunk)} 条）失败: {e}")
                last_error = str(e)
                failed.extend(chunk)

        if deleted and table_id == settings.FEISHU_TABLE_ID_JOBS:
            JobCache.remove_records(deleted)
        return {"deleted": deleted, "failed": failed, "error": last_error}

    async def _delete_records_chunk(self, table_id: str, record_ids: list[str]) -> None:
        token = await self.get_tenant_access_token()
        self._check_app_token()

        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.app_token}/tables/{table_id}/records/batch_delete"
        headers = {"Authorization": f"Bearer {token}"}
        req_body = {"records": record_ids}

        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
            data = await self._execute_request_with_retry(client, "POST", url, "批量删除记录", max_retries=1, headers=headers, json=req_body)

            if data.get("code") != 0:
                raise HTTPException(status_code=502, detail=f"批量删除记录失败: {data.get('msg')}")


feishu_client = FeishuClient()


async def _refresh_cached_job(record_id: str) -> None:
    """后台重拉单条记录并原地补丁进岗位缓存，替代原先"清空整表缓存、下次全量重拉"。"""
    try:
        record = await feishu_client.fetch_bitable_record_by_id(settings.FEISHU_TABLE_ID_JOBS, record_id)
        if not record:
            JobCache.mark_dirty()
            return
        # 延迟导入避免循环依赖（jobs.service -> feishu_client）
        from app.jobs.service import normalize_job_record

        JobCache.patch_record(normalize_job_record(record, slim=True))
    except Exception as e:
        logger.warning(f"单条缓存补丁失败，降级为脏标记: {e}")
        JobCache.mark_dirty()


def schedule_job_cache_patch(record_id: str) -> None:
    """在事件循环里调度一次单条缓存补丁；无运行中的循环（脚本/线程上下文）时降级为脏标记。"""
    if not record_id:
        return
    try:
        asyncio.get_running_loop().create_task(_refresh_cached_job(record_id))
    except RuntimeError:
        JobCache.mark_dirty()
