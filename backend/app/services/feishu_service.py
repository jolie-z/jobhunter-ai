import json
import time
from typing import Any

from app.core.config import settings

# 🌟 1. 引入刚才写好的强健底层
from app.core.feishu_utils import (
    extract_feishu_text,
    extract_job_grade,
    feishu_field_to_plain_str,
    get_tenant_access_token,
    is_custom_record,
    safe_feishu_request,
)
from app.core.testing_guard import is_testing_env, log_feishu_mock_intercept
from app.core.utils import is_greeting_supported_platform, normalize_platform_code


# 🌟 2. 环境变量/常量配置
# 凭证/表 ID 不再模块级冻结（冻结快照会让配置页热保存的值读不到）：
# 模块内使用统一走 settings.X 动态读取；历史上有多处 `from app.services.feishu_service
# import TABLE_ID/APP_TOKEN` 的函数级导入，经 PEP 562 __getattr__ 保持兼容且每次导入
# 都返回当前最新值
def __getattr__(name: str):
    if name == "TABLE_ID":
        return settings.FEISHU_TABLE_ID_JOBS
    if name == "APP_TOKEN":
        return settings.FEISHU_APP_TOKEN
    if name == "FEISHU_TABLE_ID_RESUMES":
        return settings.FEISHU_TABLE_ID_RESUMES
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

# 🌟 3. 工具函数迁移
def extract_record_id(job_id: str) -> str:
    if not job_id:
        return job_id
    if "-" in job_id:
        parts = job_id.split("-")
        for part in reversed(parts):
            if part.startswith("rec"):
                return part
        return parts[-1]
    return job_id

def get_active_resume_from_feishu() -> str:
    """从飞书配置中心读取【启用】状态的简历内容。"""
    try:
        token = get_tenant_access_token()
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}/tables/{settings.FEISHU_TABLE_ID_RESUMES}/records/search"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = {
            "filter": {
                "conjunction": "and",
                "conditions": [{"field_name": "当前状态", "operator": "is", "value": ["启用"]}]
            }
        }
        resp = safe_feishu_request("POST", url, headers=headers, json=payload, timeout=15)
        resp.raise_for_status()
        items = resp.json().get("data", {}).get("items", [])
        if items:
            import json
            raw_text = feishu_field_to_plain_str(items[0].get("fields", {}).get("结构化数据", ""))
            try:
                data_dict = json.loads(raw_text)
                data_dict.pop("personalInfo", None)
                return json.dumps(data_dict, ensure_ascii=False)
            except json.JSONDecodeError:
                return raw_text.strip()
        return ""
    except Exception as e:
        print(f"❌ 读取飞书云端简历失败: {e}")
        return ""

def get_active_resume_record_id() -> str:
    """取【启用】状态简历的记录 ID（与 get_active_resume_from_feishu 同一搜索条件）。

    用于「海投简历」未配置时回退渲染启用简历；读不到返回空串。
    """
    try:
        token = get_tenant_access_token()
        if not token:
            return ""
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}/tables/{settings.FEISHU_TABLE_ID_RESUMES}/records/search"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = {
            "filter": {
                "conjunction": "and",
                "conditions": [{"field_name": "当前状态", "operator": "is", "value": ["启用"]}]
            }
        }
        resp = safe_feishu_request("POST", url, headers=headers, json=payload, timeout=15)
        resp.raise_for_status()
        items = resp.json().get("data", {}).get("items", [])
        return items[0].get("record_id", "") if items else ""
    except Exception as e:
        print(f"❌ 读取启用简历记录 ID 失败: {e}")
        return ""

def get_active_resume_meta() -> dict[str, Any]:
    """返回当前启用的简历元信息：ID、版本名称、字数、状态等"""
    try:
        token = get_tenant_access_token()
        if not token:
            return {"record_id": "", "title": "默认基准简历", "word_count": 0, "status": "未连接飞书"}
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}/tables/{settings.FEISHU_TABLE_ID_RESUMES}/records/search"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = {
            "filter": {
                "conjunction": "and",
                "conditions": [{"field_name": "当前状态", "operator": "is", "value": ["启用"]}]
            }
        }
        resp = safe_feishu_request("POST", url, headers=headers, json=payload, timeout=10)
        items = resp.json().get("data", {}).get("items", [])
        if items:
            fields = items[0].get("fields", {})
            title = feishu_field_to_plain_str(fields.get("简历版本", "默认基准简历"))
            content = feishu_field_to_plain_str(fields.get("结构化数据", "") or fields.get("简历全文", ""))
            return {
                "record_id": items[0].get("record_id", ""),
                "title": title or "默认基准简历",
                "word_count": len(content),
                "status": "启用",
            }
        return {"record_id": "", "title": "未找到启用简历", "word_count": 0, "status": "未设置"}
    except Exception:
        return {"record_id": "", "title": "默认基准简历", "word_count": 0, "status": "读取异常"}

def get_all_resumes_meta() -> list[dict[str, Any]]:
    """返回简历库中所有简历的列表元信息：ID、版本名称、字数、状态等"""
    try:
        token = get_tenant_access_token()
        if not token:
            return []
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}/tables/{settings.FEISHU_TABLE_ID_RESUMES}/records"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        resp = safe_feishu_request("GET", url, headers=headers, timeout=15, params={"page_size": 100})
        resp.raise_for_status()
        items = resp.json().get("data", {}).get("items", [])
        result = []
        for it in items:
            fields = it.get("fields", {})
            title = feishu_field_to_plain_str(fields.get("简历版本", ""))
            if not title:
                continue
            st = fields.get("当前状态", "停用")
            status_str = "启用" if (isinstance(st, list) and "启用" in st) or st == "启用" else "停用"
            content = feishu_field_to_plain_str(fields.get("结构化数据", "") or fields.get("简历全文", ""))
            result.append({
                "record_id": it.get("record_id", ""),
                "title": title,
                "word_count": len(content),
                "status": status_str,
            })
        return result
    except Exception as e:
        print(f"❌ 读取所有简历列表元信息失败: {e}")
        return []

def get_mass_apply_resume_record_id() -> str:
    """优先获取「简历版本」为【海投简历】的记录 ID；若未单独配置则回退到当前【启用】状态的简历。"""
    try:
        token = get_tenant_access_token()
        if not token:
            return ""
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}/tables/{settings.FEISHU_TABLE_ID_RESUMES}/records"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        resp = safe_feishu_request("GET", url, headers=headers, timeout=15, params={"page_size": 50})
        resp.raise_for_status()
        items = resp.json().get("data", {}).get("items", [])

        # 1. 优先精准寻找「海投简历」
        for it in items:
            f = it.get("fields", {})
            ver = feishu_field_to_plain_str(f.get("简历版本", ""))
            if "海投" in ver:
                return it.get("record_id", "")

        # 2. 兜底寻找「当前状态=启用」
        for it in items:
            f = it.get("fields", {})
            st = f.get("当前状态")
            if (isinstance(st, list) and "启用" in st) or st == "启用":
                return it.get("record_id", "")

        return items[0].get("record_id", "") if items else ""
    except Exception as e:
        print(f"❌ 读取海投简历记录 ID 失败: {e}")
        return get_active_resume_record_id()

def get_full_active_resume_from_feishu() -> str:
    """从飞书配置中心读取【启用】状态的简历，返回缝合后的完整 Markdown（包含个人信息和正文）。"""
    try:
        token = get_tenant_access_token()
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}/tables/{settings.FEISHU_TABLE_ID_RESUMES}/records/search"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = {
            "filter": {
                "conjunction": "and",
                "conditions": [{"field_name": "当前状态", "operator": "is", "value": ["启用"]}]
            }
        }
        resp = safe_feishu_request("POST", url, headers=headers, json=payload, timeout=15)
        resp.raise_for_status()
        items = resp.json().get("data", {}).get("items", [])
        if items:
            fields = items[0].get("fields", {})
            structured_data = feishu_field_to_plain_str(fields.get("结构化数据", ""))
            return structured_data.strip()
        return ""
    except Exception as e:
        print(f"❌ 读取飞书云端简历失败: {e}")
        return ""

def get_resume_text_by_id(record_id: str) -> str:
    """按记录 ID 读取简历库指定简历的内容（格式与 get_active_resume_from_feishu 一致）。

    用于「海投简历」等按配置指定简历的场景；读取失败返回空串，由调用方回退到启用简历。
    """
    if not record_id:
        return ""
    try:
        token = get_tenant_access_token()
        if not token:
            return ""
        url = (f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}"
               f"/tables/{settings.FEISHU_TABLE_ID_RESUMES}/records/{record_id}")
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        resp = safe_feishu_request("GET", url, headers=headers, timeout=15)
        data = resp.json()
        if data.get("code") != 0:
            print(f"⚠️ 读取指定简历失败 {record_id}: {data.get('msg')}")
            return ""
        fields = data.get("data", {}).get("record", {}).get("fields", {})
        raw_text = feishu_field_to_plain_str(fields.get("结构化数据", ""))
        try:
            data_dict = json.loads(raw_text)
            data_dict.pop("personalInfo", None)
            return json.dumps(data_dict, ensure_ascii=False)
        except json.JSONDecodeError:
            return raw_text.strip()
    except Exception as e:
        print(f"⚠️ 读取指定简历异常 {record_id}: {e}")
        return ""


def get_job_record_from_feishu(record_id: str, table_id: str) -> dict[str, Any] | None:
    """获取具体岗位记录"""
    token = get_tenant_access_token()
    if not token:
        return None

    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}/tables/{table_id}/records/{record_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    try:
        resp = safe_feishu_request("GET", url, headers=headers, timeout=15)
        data = resp.json()
        if data.get("code") == 0:
            return data.get("data", {}).get("record", {})
        else:
            return None
    except Exception as e:
        print(f"❌ 获取岗位记录失败: {e}")
        return None


def get_my_preferences() -> str:
    """
    统一使用 SQLite 存储的偏好配置
    """
    try:
        from ai_agents.ai_scorer import get_user_preferences
        return get_user_preferences()
    except Exception as e:
        print(f"⚠️ 读取本地偏好失败: {e}")
        return ""


def update_feishu_record(record_id: str, fields_to_update: dict, table_id: str = None) -> bool:
    """更新飞书岗位记录"""
    token = get_tenant_access_token()
    if not token:
        return False

    app_token = settings.FEISHU_APP_TOKEN
    target_table_id = table_id if table_id else settings.FEISHU_TABLE_ID_JOBS

    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{target_table_id}/records/{record_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    processed_fields = {}
    for field_name, field_value in fields_to_update.items():
        if field_name in ["我的复核", "跟进状态"]:
            processed_fields[field_name] = str(field_value).strip() if field_value is not None else ""
        else:
            processed_fields[field_name] = field_value

    payload = {"fields": processed_fields}

    try:
        response = safe_feishu_request("PUT", url, headers=headers, json=payload, timeout=15)
        data = response.json()
        if data.get("code") == 0:
            from app.core.cache import JobCache
            JobCache.mark_dirty()
            if "跟进状态" in processed_fields:
                JobCache.patch_record_fields(record_id, {"follow_status": processed_fields["跟进状态"]})
            return True
        else:
            print(f"    ❌ 更新飞书记录失败: code={data.get('code')} msg={data.get('msg')}")
            print(f"    📋 尝试写入的字段 Keys（共 {len(processed_fields)} 个）:")
            for k in processed_fields.keys():
                print(f"       · '{k}'")
            return False
    except Exception as e:
        print(f"    ⚠️ 更新飞书记录报错: {e}")
        return False



def send_feishu_message(
    receive_id: str,
    text: str,
    receive_id_type: str = "open_id",
    reply_message_id: str = None,
    reply_in_thread: bool = True,
) -> None:
    """向飞书发送纯文本消息（带详细错误日志暴露）。"""
    if is_testing_env():
        log_feishu_mock_intercept("feishu_service.send_feishu_message")
        return

    try:
        token = get_tenant_access_token()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        if reply_message_id:
            url = f"https://open.feishu.cn/open-apis/im/v1/messages/{reply_message_id}/reply"
            payload = {
                "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
                "reply_in_thread": bool(reply_in_thread),
            }
        else:
            url = f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={receive_id_type}"
            payload = {
                "receive_id": receive_id,
                "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            }

        # 发消息是 POST 非幂等操作：服务端可能已发出但响应丢失（504/超时典型），
        # 网关层重试=同一消息重复投递，故禁用重试（宁可失败重试上层，不可双发）
        resp = safe_feishu_request("POST", url, headers=headers, json=payload, timeout=10, max_retries=1)
        resp_data = resp.json()
        if resp.status_code != 200 or resp_data.get("code") != 0:
            print(f"⚠️ 飞书消息发送失败: HTTP {resp.status_code}, 详情: {resp_data}")
        else:
            print(f"✉️ 飞书消息发送成功: {text[:20]}...")
    except Exception as e:
        print(f"⚠️ 发送飞书消息网络/代码异常: {e}")

def get_jobs_to_deliver(target_platform="猎聘", target_status="待投递"):
    """获取所有已准备好投递的岗位（提取链接、PDF Token和打招呼语）"""
    token = get_tenant_access_token()
    if not token:
        return []

    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}/tables/{settings.FEISHU_TABLE_ID_JOBS}/records/search"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    payload = {
        "filter": {
            "conjunction": "and",
            "conditions": [
                {"field_name": "跟进状态", "operator": "is", "value": [target_status]},
                {"field_name": "招聘平台", "operator": "contains", "value": [target_platform]}
            ]
        },
        "page_size": 100
    }

    try:
        response = safe_feishu_request("POST", url, headers=headers, json=payload)
        data = response.json()
        if data.get("code") != 0:
            print(f"❌ 拉取待投递岗位失败: {data.get('msg')}")
            return []

        current_ts = int(time.time() * 1000)
        jobs = []
        for record in data.get("data", {}).get("items", []):
            fields = record.get("fields", {})

            # 🌟 Python 内进行定时投递时间拦截：空=立即投递；非空则需 <= 当前时间
            scheduled_time = fields.get("定时投递时间")
            if scheduled_time:
                try:
                    if int(scheduled_time) > current_ts:
                        print(f"⏰ 记录 {record.get('record_id')} 定时投递时间未到，已跳过")
                        continue
                except Exception:
                    pass  # 时间解析失败时不阻塞，照常投递

            # 1. 解析 PDF 附件 Token 和名字
            pdf_attachments = fields.get("PDF备份", [])
            file_token = ""
            pdf_name = "专属简历"
            if pdf_attachments and isinstance(pdf_attachments, list):
                file_token = pdf_attachments[0].get("file_token", "")
                pdf_name = pdf_attachments[0].get("name", "专属简历").replace(".pdf", "")

            # 2. 解析岗位链接
            job_link_obj = fields.get("岗位链接", {})
            job_url = ""
            if isinstance(job_link_obj, dict):
                job_url = job_link_obj.get("link", "")
            else:
                job_url = str(job_link_obj)

            # 3. 获取打招呼语
            greeting = extract_feishu_text(fields.get("打招呼语", ""))

            # 提取图片版简历附件列表（供 BOSS 投递引擎使用）
            image_attachments = fields.get("图片保存", [])
            image_items = []
            if image_attachments and isinstance(image_attachments, list):
                for att in image_attachments:
                    token = att.get("file_token", "")
                    if token:
                        image_items.append({"file_token": token, "name": att.get("name", "image.jpg")})

            # 只有当必备要素齐全时，才认为该岗位合法
            # 51job 不支持打招呼语，不强制要求 greeting
            is_51job = "51job" in extract_feishu_text(fields.get("招聘平台", "")).lower() or "前程无忧" in extract_feishu_text(fields.get("招聘平台", ""))
            has_required = job_url and (file_token or image_items)
            if is_51job:
                valid = has_required
            else:
                valid = has_required and greeting

            if valid:
                # 🌟 统一精投判定口径（与 delivery_node / 批量编排预扫描共用 is_custom_record）
                grade = extract_job_grade(fields).upper()
                is_custom = is_custom_record(fields)
                mass_apply = not is_custom
                jobs.append({
                    "record_id": record.get("record_id"),
                    "job_url": job_url,
                    "file_token": file_token,
                    "pdf_name": pdf_name,
                    "greeting": greeting,
                    "image_items": image_items,
                    "company": extract_feishu_text(fields.get("公司名称", "")),
                    "job_title": extract_feishu_text(fields.get("岗位名称", "")),
                    "scheduled_at": fields.get("定时投递时间"),
                    "grade": grade,
                    "is_custom": is_custom,
                    "mass_apply": mass_apply,
                })
            else:
                print(f"⚠️ 记录 {record.get('record_id')} 数据不全(缺URL/PDF或图片/开场白)，已跳过")

        return jobs
    except Exception as e:
        print(f"❌ 请求拉取待投递岗位时异常: {e}")
        return []

def send_feishu_card(receive_id: str, card_content: dict, receive_id_type: str = "open_id") -> None:
    """向飞书发送富文本卡片消息"""
    if is_testing_env():
        log_feishu_mock_intercept("feishu_service.send_feishu_card")
        return

    try:
        token = get_tenant_access_token()
        url = f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={receive_id_type}"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = {
            "receive_id": receive_id,
            "msg_type": "interactive",
            "content": json.dumps(card_content, ensure_ascii=False)
        }
        # 非幂等 POST：禁用网关层重试，防超时场景同一卡片重复投递
        safe_feishu_request("POST", url, headers=headers, json=payload, timeout=10, max_retries=1)
    except Exception as e:
        print(f"⚠️ 发送飞书卡片异常: {e}")

def upload_file_to_feishu(file_bytes: bytes, file_name: str, file_type: str = "stream") -> str:
    """上传文件到飞书服务器，返回 file_key"""
    if is_testing_env():
        log_feishu_mock_intercept("feishu_service.upload_file_to_feishu", "")
        return ""

    try:
        token = get_tenant_access_token()
        url = "https://open.feishu.cn/open-apis/im/v1/files"
        headers = {"Authorization": f"Bearer {token}"}
        files = {
            "file_type": (None, file_type),
            "file_name": (None, file_name),
            "file": (file_name, file_bytes)
        }
        resp = safe_feishu_request("POST", url, headers=headers, files=files, timeout=30)
        data = resp.json()
        if data.get("code") == 0:
            return data["data"]["file_key"]
        print(f"⚠️ 飞书上传文件失败: {data}")
        return ""
    except Exception as e:
        print(f"⚠️ 飞书文件上传通信异常: {e}")
        return ""

def send_feishu_file(receive_id: str, file_key: str, receive_id_type: str = "open_id") -> None:
    """向飞书发送文件消息"""
    if is_testing_env():
        log_feishu_mock_intercept("feishu_service.send_feishu_file")
        return

    try:
        token = get_tenant_access_token()
        url = f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={receive_id_type}"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = {
            "receive_id": receive_id,
            "msg_type": "file",
            "content": json.dumps({"file_key": file_key})
        }
        # 非幂等 POST：禁用网关层重试，防超时场景同一文件消息重复投递
        safe_feishu_request("POST", url, headers=headers, json=payload, timeout=10, max_retries=1)
    except Exception as e:
        print(f"⚠️ 发送飞书文件消息异常: {e}")

def get_new_leads_from_feishu(platform: str = ""):
    """获取所有处于【新线索】状态的待评估岗位；传 platform（如 "boss"）时只拉取该平台"""
    token = get_tenant_access_token()
    if not token:
        return []

    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}/tables/{settings.FEISHU_TABLE_ID_JOBS}/records/search"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    conditions = [{"field_name": "跟进状态", "operator": "is", "value": ["新线索"]}]
    if platform:
        conditions.append({"field_name": "招聘平台", "operator": "is", "value": [platform]})
    payload = {
        "filter": {
            "conjunction": "and",
            "conditions": conditions
        },
        "page_size": 100
    }

    try:
        response = safe_feishu_request("POST", url, headers=headers, json=payload)
        data = response.json()
        if data.get("code") != 0:
            print(f"❌ 拉取新线索失败: {data.get('msg')}")
            return []

        leads = []
        for record in data.get("data", {}).get("items", []):
            fields = record.get("fields", {})
            leads.append({
                "record_id": record.get("record_id"),
                "company": extract_feishu_text(fields.get("公司名称", "")) or "未知公司",
                "job_title": extract_feishu_text(fields.get("岗位名称", "")) or "未知岗位",
                "jd_text": extract_feishu_text(fields.get("岗位详情", "")),
                "salary": extract_feishu_text(fields.get("薪资", "")) or "未知",
                "city": extract_feishu_text(fields.get("城市", "")) or "未知",
                "experience": extract_feishu_text(fields.get("经验要求", "")) or "未知",
                "education": extract_feishu_text(fields.get("学历要求", "")) or "未知",
                "platform": extract_feishu_text(fields.get("招聘平台", "")) or "未知渠道",
                "job_url": extract_feishu_text(fields.get("岗位链接", "")),
                "_created_time": record.get("created_time", 0),
                "_raw_fields": fields,
            })
        return leads
    except Exception as e:
        print(f"❌ 请求拉取新线索时异常: {e}")
        return []


def get_pending_review_jobs_from_feishu(max_pages: int = 3):
    """获取处于【简历人工复核】、【已完成初步评估】或【待投递】状态的待审批岗位，并提取物料就绪状态与公司规模。

    注意：跟进状态是单选字段，is 过滤每条 condition 只能带 1 个值，
    多值必须拆成多条 condition 用 or 连接。
    使用 while has_more 分页循环，杜绝单页截断海投/待审岗位。
    """
    token = get_tenant_access_token()
    if not token:
        return []

    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}/tables/{settings.FEISHU_TABLE_ID_JOBS}/records/search"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    payload_filter = {
        "conjunction": "or",
        "conditions": [
            {"field_name": "跟进状态", "operator": "is", "value": ["简历人工复核"]},
            {"field_name": "跟进状态", "operator": "is", "value": ["海投人工复核"]},
            {"field_name": "跟进状态", "operator": "is", "value": ["已完成初步评估"]},
            {"field_name": "跟进状态", "operator": "is", "value": ["待投递"]}
        ]
    }

    jobs = []
    page_token = None
    page_count = 0

    try:
        while page_count < max_pages:
            payload = {
                "filter": payload_filter,
                "page_size": 100
            }
            if page_token:
                payload["page_token"] = page_token

            response = safe_feishu_request("POST", url, headers=headers, json=payload)
            data = response.json()
            if data.get("code") != 0:
                print(f"❌ 拉取待审批岗位失败: {data.get('msg')}")
                break

            items = data.get("data", {}).get("items", []) or []
            for record in items:
                fields = record.get("fields", {})
                grade = extract_job_grade(fields)
                raw_plat = extract_feishu_text(fields.get("招聘平台", "")) or "boss"
                plat = "boss"
                if "猎聘" in raw_plat or "liepin" in raw_plat.lower():
                    plat = "liepin"
                elif "51" in raw_plat or "前程" in raw_plat or "job51" in raw_plat.lower():
                    plat = "51job"
                elif "智联" in raw_plat or "zhilian" in raw_plat.lower():
                    plat = "zhilian"

                img_att = fields.get("图片保存", []) or []
                pdf_att = fields.get("PDF 备份", []) or fields.get("PDF备份", []) or []
                greeting_val = extract_feishu_text(fields.get("打招呼语", ""))
                follow_status = extract_feishu_text(fields.get("跟进状态", "")) or "简历人工复核"
                company_scale = extract_feishu_text(fields.get("公司规模", "")) or ""
                education = extract_feishu_text(fields.get("学历要求", "")) or extract_feishu_text(fields.get("学历", "")) or ""
                experience = extract_feishu_text(fields.get("经验要求", "")) or extract_feishu_text(fields.get("经验", "")) or ""
                score_val = fields.get("初评总分") or fields.get("初步评估得分")
                failure_reason = extract_feishu_text(fields.get("自动投递失败日志", "")) or extract_feishu_text(fields.get("异常原因", ""))
                try:
                    score_num = float(score_val) if score_val is not None else None
                except (ValueError, TypeError):
                    score_num = None

                # 🌟 精投/海投统一判定口径（is_custom_record：AI改写JSON/评级AB），
                # 与投递编排 delivery_node、批量预扫描同源；此前仅按评级 A/B 硬算，
                # 曾把 AI初评漏斗放行（score≥70）的 C 级定制改写岗误标成海投规则审批
                is_custom = is_custom_record(fields)

                failure_info = None
                if failure_reason:
                    failure_info = {
                        "stage": "delivery",
                        "step": "自动投递阶段",
                        "reason": failure_reason,
                        "suggestion": "已自动修复微聊标签页捕获逻辑，可点击重新投递。" if "tab" in failure_reason.lower() else "建议检查对应平台浏览器登录态是否过期，或点击右侧按钮重试。",
                        "can_retry": True,
                    }

                jobs.append({
                    "job_id": record.get("record_id"),
                    "job_name": extract_feishu_text(fields.get("岗位名称", "")) or "未知岗位",
                    "company_name": extract_feishu_text(fields.get("公司名称", "")) or "未知公司",
                    "platform": plat,
                    "grade": grade.upper(),
                    "score": score_num,
                    "salary": extract_feishu_text(fields.get("薪资", "")) or "",
                    "city": extract_feishu_text(fields.get("城市", "")) or "",
                    "education": education,
                    "experience": experience,
                    "job_url": extract_feishu_text(fields.get("岗位链接", "")),
                    "company_scale": company_scale,
                    "has_image": bool(len(img_att) > 0 if isinstance(img_att, list) else img_att),
                    "has_pdf": bool(len(pdf_att) > 0 if isinstance(pdf_att, list) else pdf_att),
                    "has_greeting": bool(greeting_val and len(greeting_val.strip()) > 5),
                    "greeting_text": greeting_val,
                    "greeting_msg": greeting_val or "",
                    "is_custom": is_custom,
                    "follow_status": follow_status,
                    "failure_info": failure_info,
                    "status": "error" if failure_info else "waiting",
                    "node": "error" if failure_info else "manual_review_node",
                })

            has_more = data.get("data", {}).get("has_more", False)
            page_token = data.get("data", {}).get("page_token")
            page_count += 1
            if not has_more or not page_token:
                break

        return jobs
    except Exception as e:
        print(f"❌ 请求拉取待审批岗位时异常: {e}")
        return jobs


def get_scheduled_delivery_jobs_from_feishu(max_pages: int = 5, respect_scheduled_time: bool = False):
    """获取所有【待投递】（已人工放行或海投免审放行、等待定时发射）的岗位。

    respect_scheduled_time=True 时（供每日发射波次），岗位若登记了「定时投递时间」且未到点会被跳过；
    指挥中心看板等展示场景保持 False，未到点的岗位照常出现在待投递 tab。
    """
    token = get_tenant_access_token()
    if not token:
        return []

    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}/tables/{settings.FEISHU_TABLE_ID_JOBS}/records/search"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    jobs = []
    page_token = None
    page_count = 0
    current_ts = int(time.time() * 1000)

    try:
        while page_count < max_pages:
            payload = {
                "filter": {
                    "conjunction": "and",
                    "conditions": [
                        {"field_name": "跟进状态", "operator": "is", "value": ["待投递"]}
                    ]
                },
                "page_size": 100
            }
            if page_token:
                payload["page_token"] = page_token

            response = safe_feishu_request("POST", url, headers=headers, json=payload)
            data = response.json()
            if data.get("code") != 0:
                print(f"❌ 拉取待投递岗位失败: {data.get('msg')}")
                break

            items = data.get("data", {}).get("items", []) or []
            for record in items:
                fields = record.get("fields", {})

                # 定时投递时间拦截（与 get_jobs_to_deliver 同口径）：空=立即投递；非空则需 <= 当前时间
                if respect_scheduled_time:
                    scheduled_time = fields.get("定时投递时间")
                    if scheduled_time:
                        try:
                            if int(scheduled_time) > current_ts:
                                print(f"⏰ 记录 {record.get('record_id')} 定时投递时间未到，本轮波次跳过")
                                continue
                        except Exception:
                            pass  # 时间解析失败时不阻塞，照常进入发射队列

                grade = extract_job_grade(fields)
                raw_plat = extract_feishu_text(fields.get("招聘平台", "")) or "boss"
                plat = "boss"
                if "猎聘" in raw_plat or "liepin" in raw_plat.lower():
                    plat = "liepin"
                elif "51" in raw_plat or "前程" in raw_plat or "job51" in raw_plat.lower():
                    plat = "51job"
                elif "智联" in raw_plat or "zhilian" in raw_plat.lower():
                    plat = "zhilian"
                pdf_att = fields.get("PDF 备份", []) or fields.get("PDF备份", []) or []
                greeting_val = extract_feishu_text(fields.get("打招呼语", ""))
                company_scale = extract_feishu_text(fields.get("公司规模", "")) or ""
                jobs.append({
                    "job_id": record.get("record_id"),
                    "job_name": extract_feishu_text(fields.get("岗位名称", "")) or "未知岗位",
                    "company_name": extract_feishu_text(fields.get("公司名称", "")) or "未知公司",
                    "platform": plat,
                    "grade": grade.upper(),
                    # 🌟 统一精投判定口径（is_custom_record），供看板 review_type 与发射前海投物料刷新共用
                    "is_custom": is_custom_record(fields),
                    "salary": extract_feishu_text(fields.get("薪资", "")) or "",
                    "city": extract_feishu_text(fields.get("城市", "")) or "",
                    "company_scale": company_scale,
                    "job_url": extract_feishu_text(fields.get("岗位链接", "")),
                    "has_pdf": bool(len(pdf_att) > 0 if isinstance(pdf_att, list) else pdf_att),
                    "has_greeting": bool(greeting_val and len(greeting_val.strip()) > 5),
                    "greeting_msg": greeting_val or "",
                    "greeting_text": greeting_val or "",
                })

            has_more = data.get("data", {}).get("has_more", False)
            page_token = data.get("data", {}).get("page_token")
            page_count += 1
            if not has_more or not page_token:
                break

        return jobs
    except Exception as e:
        print(f"❌ 请求拉取待投递岗位时异常: {e}")
        return jobs


def get_manual_rejected_jobs_from_feishu(max_pages: int = 3):
    """获取所有处于【已拒绝】状态的岗位（老板在审批环节手动否决：区别于机器清洗淘汰，仅归档展示于全部岗位）"""
    token = get_tenant_access_token()
    if not token:
        return []

    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}/tables/{settings.FEISHU_TABLE_ID_JOBS}/records/search"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    jobs = []
    page_token = None
    page_count = 0

    try:
        while page_count < max_pages:
            payload = {
                "filter": {
                    "conjunction": "and",
                    "conditions": [
                        {"field_name": "跟进状态", "operator": "is", "value": ["已拒绝"]}
                    ]
                },
                "page_size": 100
            }
            if page_token:
                payload["page_token"] = page_token

            response = safe_feishu_request("POST", url, headers=headers, json=payload, timeout=15)
            data = response.json()
            if data.get("code") != 0:
                print(f"❌ 拉取已拒绝岗位失败: {data.get('msg')}")
                break

            items = data.get("data", {}).get("items", []) or []
            for record in items:
                fields = record.get("fields", {})
                grade = extract_job_grade(fields)
                raw_plat = extract_feishu_text(fields.get("招聘平台", "")) or "boss"
                plat = "boss"
                if "猎聘" in raw_plat or "liepin" in raw_plat.lower():
                    plat = "liepin"
                elif "51" in raw_plat or "前程" in raw_plat or "job51" in raw_plat.lower():
                    plat = "51job"
                elif "智联" in raw_plat or "zhilian" in raw_plat.lower():
                    plat = "zhilian"
                jobs.append({
                    "job_id": record.get("record_id"),
                    "job_name": extract_feishu_text(fields.get("岗位名称", "")) or "未知岗位",
                    "company_name": extract_feishu_text(fields.get("公司名称", "")) or "未知公司",
                    "platform": plat,
                    "grade": grade.upper(),
                    "salary": extract_feishu_text(fields.get("薪资", "")) or "",
                    "city": extract_feishu_text(fields.get("城市", "")) or "",
                    "job_url": extract_feishu_text(fields.get("岗位链接", "")),
                    "company_scale": extract_feishu_text(fields.get("公司规模", "")) or "",
                    "follow_status": "已拒绝",
                })

            has_more = data.get("data", {}).get("has_more", False)
            page_token = data.get("data", {}).get("page_token")
            page_count += 1
            if not has_more or not page_token:
                break

        return jobs
    except Exception as e:
        print(f"❌ 请求拉取已拒绝岗位时异常: {e}")
        return jobs


def get_delivered_jobs_from_feishu(max_pages: int = 5, today_only: bool = True):
    """获取所有处于【已投递】状态的岗位（默认仅限当天投递的战报记录，避免历史堆积）"""
    token = get_tenant_access_token()
    if not token:
        return []

    from datetime import date, datetime
    today_str = date.today().strftime("%Y-%m-%d")

    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}/tables/{settings.FEISHU_TABLE_ID_JOBS}/records/search"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    jobs = []
    page_token = None
    page_count = 0

    try:
        while page_count < max_pages:
            payload = {
                "filter": {
                    "conjunction": "or",
                    "conditions": [
                        {"field_name": "跟进状态", "operator": "is", "value": ["已投递"]},
                    ]
                },
                "page_size": 100
            }
            if page_token:
                payload["page_token"] = page_token

            response = safe_feishu_request("POST", url, headers=headers, json=payload)
            data = response.json()
            if data.get("code") != 0:
                break

            items = data.get("data", {}).get("items", []) or []
            for record in items:
                fields = record.get("fields", {})
                deliver_ts = fields.get("投递日期") or fields.get("投递时间")
                is_today = False
                delivered_at = ""
                if deliver_ts:
                    try:
                        delivered_at = datetime.fromtimestamp(int(deliver_ts) / 1000).strftime("%Y-%m-%d %H:%M:%S")
                        d_date = delivered_at[:10]
                        if d_date == today_str:
                            is_today = True
                    except Exception:
                        pass

                # 默认仅拉取当天的已投递记录
                if today_only and not is_today:
                    continue

                grade = extract_job_grade(fields)
                raw_plat = extract_feishu_text(fields.get("招聘平台", "")) or "boss"
                plat = "boss"
                if "猎聘" in raw_plat or "liepin" in raw_plat.lower():
                    plat = "liepin"
                elif "51" in raw_plat or "前程" in raw_plat or "job51" in raw_plat.lower():
                    plat = "51job"
                elif "智联" in raw_plat or "zhilian" in raw_plat.lower():
                    plat = "zhilian"

                img_att = fields.get("图片保存", []) or []
                pdf_att = fields.get("PDF 备份", []) or fields.get("PDF备份", []) or []
                greeting_val = extract_feishu_text(fields.get("打招呼语", ""))
                status_val = extract_feishu_text(fields.get("跟进状态", ""))
                err_val = extract_feishu_text(fields.get("自动投递失败日志", "")) or extract_feishu_text(fields.get("异常原因", ""))
                company_scale = extract_feishu_text(fields.get("公司规模", "")) or ""

                # 各平台真实物料与打招呼语判定（彻底摒弃假阳性硬编码）
                # 🌟 长图简历仅 BOSS 微聊专属物料；智联/51job/猎聘均为纯附件 PDF 投递，一律屏蔽
                has_image = False if plat in ("zhilian", "51job", "liepin") else bool(len(img_att) > 0 if isinstance(img_att, list) else img_att)
                # 🌟 PDF 简历仅附件投递平台真实外发；BOSS 微聊只发长图，「PDF 备份」在 BOSS
                # 记录里仅为归档母本，不得反推为已送达回执（与 has_image 互为对称屏蔽）
                has_pdf = False if plat == "boss" else bool(len(pdf_att) > 0 if isinstance(pdf_att, list) else pdf_att)
                # 🌟 打招呼语送达判定：仅限具备微聊外发能力的平台（白名单：BOSS/智联/猎聘），51job等纯附件平台严格置 False
                has_greeting = bool(is_greeting_supported_platform(plat) and greeting_val and len(greeting_val.strip()) > 5)
                # 🌟 真实回执判定：已投递记录仅当有打招呼语且失败日志无微聊受阻标记才判已送达；
                # 防御 err_val 为 None，并在 has_greeting 为 False 时自洽为 False
                err_str = str(err_val or "")
                greeting_delivered = bool(has_greeting and not any(marker in err_str for marker in ("微聊受阻", "打招呼语未")))

                jobs.append({
                    "job_id": record.get("record_id"),
                    "job_name": extract_feishu_text(fields.get("岗位名称", "")) or "未知岗位",
                    "company_name": extract_feishu_text(fields.get("公司名称", "")) or "未知公司",
                    "platform": plat,
                    "grade": grade.upper(),
                    "salary": extract_feishu_text(fields.get("薪资", "")) or "",
                    "city": extract_feishu_text(fields.get("城市", "")) or "",
                    "company_scale": company_scale,
                    "job_url": extract_feishu_text(fields.get("岗位链接", "")),
                    # 🌟 与待投递/投递编排同口径：is_custom_record 统一判定精投/海投
                    "is_custom": bool(is_custom_record(fields)),
                    "greeting_msg": greeting_val,
                    "has_image": has_image,
                    "has_pdf": has_pdf,
                    "has_greeting": has_greeting,
                    "greeting_delivered": greeting_delivered,
                    "status": "delivered" if "已投递" in status_val else "error",
                    "error_msg": err_val,
                    "delivered_at": delivered_at,
                })

            has_more = data.get("data", {}).get("has_more", False)
            page_token = data.get("data", {}).get("page_token")
            page_count += 1
            if not has_more or not page_token:
                break

        return jobs
    except Exception as e:
        print(f"❌ 拉取已投递记录异常: {e}")
        return jobs


def is_quota_exhausted_error(error: str) -> bool:
    """判断是否为 51job 附件上传日配额耗尽（720721 / 今日上传次数已达上限）。
    此类错误属于当日暂缓发射，飞书门牌应保持「待投递」，以便次日波次拉起并跨天自愈。
    """
    err_str = str(error or "")
    return "720721" in err_str or "今日上传次数" in err_str


# 内存级短时防抖去重缓存：record_id -> timestamp
_recent_failed_writes: dict[str, float] = {}

def mark_job_delivery_failed(job_id: str, error: str) -> bool:
    """将岗位在飞书的【跟进状态】写入为【投递失败】，并回写【自动投递失败日志】。

    🌟 配额风控自愈豁免：若命中 51job 日配额限制 (720721)，则不改变「待投递」门牌，
    仅登记失败日志与本地台账，确保次日定时波次能拉入并触发 is_stale_quota_failure 自愈发射。

    遵循全白盒化日志，内部捕获所有异常返回 False，绝不阻断投递主流程。
    内置 15 秒短时间防抖去重保护，杜绝跨层兜底调用导致的重复网络请求与 API 配额浪费。
    """
    clean_id = extract_record_id(job_id)
    if not clean_id:
        print(f"⚠️ [mark_job_delivery_failed] 无法解析有效飞书记录 ID: {job_id}")
        return False
    try:
        import time
        now = time.time()
        err_text = str(error or "自动投递执行失败")[:500]
        # 15 秒纯天然幂等防抖检查（脱敏错误文字差异）
        if clean_id in _recent_failed_writes:
            last_t = _recent_failed_writes[clean_id]
            if now - last_t < 15.0:
                print(f"⏭️ [mark_job_delivery_failed] 命中 15s 防抖幂等缓存，跳过重复写入: record_id={clean_id}")
                return True

        # 内存级防抖缓存自动过期淘汰（防止长时间常驻进程无界膨胀）
        if len(_recent_failed_writes) > 100:
            stale_keys = [k for k, t in _recent_failed_writes.items() if now - t > 60.0]
            for k in stale_keys:
                _recent_failed_writes.pop(k, None)

        is_quota = is_quota_exhausted_error(err_text)
        if is_quota:
            print(f"ℹ️ [mark_job_delivery_failed] 检测到 51job 附件日配额限制(720721)，保留飞书「待投递」门牌以便次日跨天自愈，仅回写失败日志: {clean_id}")
            fields_to_update = {
                "自动投递失败日志": err_text
            }
        else:
            print(f"📝 [mark_job_delivery_failed] 正在回写飞书跟进状态为「投递失败」: record_id={clean_id}, err={err_text[:80]}")
            fields_to_update = {
                # 飞书 Bitable 单选选项「投递失败」对应 Option ID: optaUO94rm
                "跟进状态": "投递失败",
                "自动投递失败日志": err_text
            }
        ok = update_feishu_record(clean_id, fields_to_update)
        if ok:
            _recent_failed_writes[clean_id] = now
            if is_quota:
                print(f"✅ [mark_job_delivery_failed] 成功回写 51job 配额日志 (保持待投递): {clean_id}")
            else:
                print(f"✅ [mark_job_delivery_failed] 成功写入飞书「投递失败」: {clean_id}")
        else:
            print(f"❌ [mark_job_delivery_failed] 写入飞书失败: {clean_id}")
        return ok
    except Exception as e:
        print(f"❌ [mark_job_delivery_failed] 回写飞书异常 (不阻断主流程): {clean_id}, err: {e}")
        return False


def get_failed_jobs_from_feishu(max_pages: int = 5) -> list[dict]:
    """获取飞书上所有【跟进状态】为【投递失败】的岗位列表（供看板展示与双轨聚合）。"""
    token = get_tenant_access_token()
    if not token:
        return []

    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}/tables/{settings.FEISHU_TABLE_ID_JOBS}/records/search"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    jobs = []
    page_token = None
    page_count = 0

    try:
        while page_count < max_pages:
            payload = {
                "filter": {
                    "conjunction": "and",
                    "conditions": [
                        {"field_name": "跟进状态", "operator": "is", "value": ["投递失败"]}
                    ]
                },
                "page_size": 100
            }
            if page_token:
                payload["page_token"] = page_token

            response = safe_feishu_request("POST", url, headers=headers, json=payload)
            data = response.json()
            if data.get("code") != 0:
                print(f"❌ 拉取投递失败岗位失败: {data.get('msg')}")
                break

            items = data.get("data", {}).get("items", []) or []
            for record in items:
                fields = record.get("fields", {})
                grade = extract_job_grade(fields)
                plat = normalize_platform_code(extract_feishu_text(fields.get("招聘平台", "")))
                err_val = feishu_field_to_plain_str(fields.get("自动投递失败日志", ""))
                jobs.append({
                    "job_id": record.get("record_id"),
                    "job_name": extract_feishu_text(fields.get("岗位名称", "")) or "未知岗位",
                    "company_name": extract_feishu_text(fields.get("公司名称", "")) or "未知公司",
                    "platform": plat,
                    "grade": (grade or "C").upper(),
                    "salary": extract_feishu_text(fields.get("薪资", "")) or "",
                    "city": extract_feishu_text(fields.get("城市", "")) or "",
                    "job_url": extract_feishu_text(fields.get("岗位链接", "")),
                    "is_custom": bool(is_custom_record(fields)),
                    "status": "failed",
                    "error_msg": err_val,
                })

            has_more = data.get("data", {}).get("has_more", False)
            page_token = data.get("data", {}).get("page_token")
            page_count += 1
            if not has_more or not page_token:
                break

        return jobs
    except Exception as e:
        print(f"❌ 拉取投递失败记录异常: {e}")
        return jobs
