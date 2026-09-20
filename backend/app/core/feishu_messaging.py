import json
import uuid

import httpx

from app.core.feishu_client import feishu_client
from app.core.testing_guard import is_testing_env, log_feishu_mock_intercept


def is_valid_receive_id(receive_id: str) -> bool:
    """飞书接收ID格式校验：群聊 oc_ 开头、个人 ou_ 开头。网页URL等一律判非法。"""
    return bool(receive_id) and (receive_id.startswith("oc_") or receive_id.startswith("ou_"))


def _message_send_url(receive_id_type: str, idempotency_key: str | None = None) -> str:
    """构造发消息接口 URL。idempotency_key 映射为飞书官方 uuid 幂等参数：
    短时间内带相同 uuid 重复提交，飞书只投递一条并返回同一 message_id，
    用于「超时但实际已送达」场景的重试防双发。"""
    url = f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={receive_id_type}"
    if idempotency_key:
        url += f"&uuid={idempotency_key}"
    return url


async def send_feishu_message(
    receive_id: str,
    text: str,
    receive_id_type: str = "open_id",
    reply_message_id: str = None,
    reply_in_thread: bool = True,
    idempotency_key: str | None = None,
) -> bool:
    """发送文本消息。返回 True=送达，False=失败（调用方必须自行降级处理）。"""
    if is_testing_env():
        log_feishu_mock_intercept("send_feishu_message", True)
        return True

    try:
        token = await feishu_client.get_tenant_access_token()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        if reply_message_id:
            url = f"https://open.feishu.cn/open-apis/im/v1/messages/{reply_message_id}/reply"
            payload = {
                "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
                "reply_in_thread": bool(reply_in_thread),
            }
        else:
            url = _message_send_url(receive_id_type, idempotency_key)
            payload = {
                "receive_id": receive_id,
                "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            }

        async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp_data = resp.json()
            if resp.status_code != 200 or resp_data.get("code") != 0:
                print(f"⚠️ 飞书消息发送失败: HTTP {resp.status_code}, 详情: {resp_data}")
                return False
            print(f"✉️ 飞书消息发送成功: {text[:20]}...")
            return True
    except Exception as e:
        print(f"⚠️ 发送飞书消息网络/代码异常: {e}")
        return False

async def upload_image_to_feishu(image_bytes: bytes) -> str:
    if is_testing_env():
        log_feishu_mock_intercept("upload_image_to_feishu", "img_mock_test_key")
        return "img_mock_test_key"

    token = await feishu_client.get_tenant_access_token()
    if not token:
        raise Exception("无法获取飞书 Token")

    url = "https://open.feishu.cn/open-apis/im/v1/images"
    headers = {"Authorization": f"Bearer {token}"}
    data = {"image_type": "message"}
    files = {"image": ("table.png", image_bytes, "image/png")}

    async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
        resp = await client.post(url, headers=headers, data=data, files=files)
        res_json = resp.json()
        if res_json.get("code") == 0:
            image_key = res_json["data"]["image_key"]
            print(f"🖼️ 飞书图片上传成功: image_key={image_key}")
            return image_key
        raise Exception(f"飞书图片上传失败: {res_json}")

async def download_message_image(message_id: str, file_key: str) -> bytes:
    """下载「收到的消息」里的图片（GET /im/v1/messages/{message_id}/resources/{file_key}?type=image）。

    注意：/im/v1/images/{image_key} 仅能下载机器人自己上传的图片，
    用户发在会话里的图片必须走本接口，且需要 message_id。
    """
    if is_testing_env():
        log_feishu_mock_intercept("download_message_image", b"")
        return b""

    token = await feishu_client.get_tenant_access_token()
    url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/resources/{file_key}"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"type": "image"}

    async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
        resp = await client.get(url, headers=headers, params=params)
        if resp.status_code != 200:
            raise Exception(f"HTTP {resp.status_code}: {resp.text[:200]}")
        print(f"🖼️ 飞书消息图片下载成功: message_id={message_id}, file_key={file_key}, {len(resp.content)} bytes")
        return resp.content

async def send_feishu_image(receive_id: str, image_key: str, receive_id_type: str = "chat_id") -> bool:
    """发送图片消息。返回 True=送达，False=失败（调用方据此决定是否补发/标记）。"""
    if is_testing_env():
        log_feishu_mock_intercept("send_feishu_image", True)
        return True

    try:
        token = await feishu_client.get_tenant_access_token()
        url = _message_send_url(receive_id_type)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        payload = {
            "receive_id": receive_id,
            "msg_type": "image",
            "content": json.dumps({"image_key": image_key}),
        }
        async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp_data = resp.json()
            if resp.status_code != 200 or resp_data.get("code") != 0:
                print(f"⚠️ 飞书图片消息发送失败: HTTP {resp.status_code}, 详情: {resp_data}")
                return False
            print(f"🖼️ 飞书图片消息发送成功: image_key={image_key}")
            return True
    except Exception as e:
        print(f"⚠️ 发送飞书图片消息异常: {e}")
        return False

async def upload_file_to_feishu(file_bytes: bytes, file_name: str) -> str:
    if is_testing_env():
        log_feishu_mock_intercept("upload_file_to_feishu", "file_mock_test_key")
        return "file_mock_test_key"

    token = await feishu_client.get_tenant_access_token()
    if not token:
        raise Exception("无法获取飞书 Token")

    url = "https://open.feishu.cn/open-apis/im/v1/files"
    headers = {"Authorization": f"Bearer {token}"}
    data = {"file_type": "stream", "file_name": file_name}
    files = {"file": (file_name, file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}

    async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
        resp = await client.post(url, headers=headers, data=data, files=files)
        res_json = resp.json()
        if res_json.get("code") == 0:
            file_key = res_json["data"]["file_key"]
            print(f"📎 飞书文件上传成功: file_key={file_key}, file_name={file_name}")
            return file_key
        raise Exception(f"飞书文件上传失败: {res_json}")

async def send_feishu_file(receive_id: str, file_key: str, receive_id_type: str = "chat_id") -> bool:
    """发送文件消息。返回 True=送达，False=失败（调用方据此决定是否补发/标记）。"""
    if is_testing_env():
        log_feishu_mock_intercept("send_feishu_file", True)
        return True

    try:
        token = await feishu_client.get_tenant_access_token()
        url = _message_send_url(receive_id_type)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        payload = {
            "receive_id": receive_id,
            "msg_type": "file",
            "content": json.dumps({"file_key": file_key}),
        }
        async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp_data = resp.json()
            if resp.status_code != 200 or resp_data.get("code") != 0:
                print(f"⚠️ 飞书文件消息发送失败: HTTP {resp.status_code}, 详情: {resp_data}")
                return False
            print(f"📎 飞书文件消息发送成功: file_key={file_key}")
            return True
    except Exception as e:
        print(f"⚠️ 发送飞书文件消息异常: {e}")
        return False

async def send_feishu_card(receive_id: str, card_content: dict, receive_id_type: str = "chat_id",
                           idempotency_key: str | None = None):
    if is_testing_env():
        log_feishu_mock_intercept("send_feishu_card", "om_mock_test_card_id")
        return "om_mock_test_card_id"

    token = await feishu_client.get_tenant_access_token()
    url = _message_send_url(receive_id_type, idempotency_key)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "receive_id": receive_id,
        "msg_type": "interactive",
        "content": json.dumps(card_content)
    }
    async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
        resp = await client.post(url, headers=headers, json=payload)
        res_json = resp.json()
        if res_json.get("code") != 0:
            print(f"⚠️ 飞书卡片发送失败: {res_json}")
            raise Exception(f"飞书卡片发送失败: {res_json}")
        message_id = (res_json.get("data") or {}).get("message_id", "")
        print(f"🃏 飞书卡片消息发送成功: message_id={message_id}")
        return message_id


async def send_feishu_card_with_fallback(receive_id: str, card_content: dict,
                                         fallback_text: str = "", receive_id_type: str = "chat_id") -> None:
    """发卡片：失败先同幂等键重试一次（防「已送达但响应丢失」场景双发），仍失败才降级纯文本。

    全仓统一的卡片降级模式——散落的 `try: send_card except: send_text` 会在超时场景
    造成卡+文双份，一律改用本函数。
    """
    key = str(uuid.uuid4())
    try:
        await send_feishu_card(receive_id, card_content, receive_id_type, idempotency_key=key)
        return
    except Exception as e1:
        try:
            await send_feishu_card(receive_id, card_content, receive_id_type, idempotency_key=key)
            print(f"🃏 卡片首次发送异常({type(e1).__name__})，同幂等键重试成功")
            return
        except Exception as e2:
            print(f"⚠️ 卡片发送重试仍失败，降级为普通文本: {e2}")
            if fallback_text:
                try:
                    await send_feishu_message(receive_id, fallback_text, receive_id_type,
                                              idempotency_key=str(uuid.uuid4()))
                except Exception as e3:
                    print(f"⚠️ 卡片降级纯文本亦失败: {e3}")


async def update_feishu_card(message_id: str, card_content: dict) -> bool:
    """原地更新机器人已发送的卡片消息（PATCH /im/v1/messages/:message_id）。

    用于评估进度卡：同一张卡随阶段推进原地变化，不再连发多条新消息。
    返回 True=更新成功；失败打日志返回 False（调用方静默降级）。
    """
    if is_testing_env():
        log_feishu_mock_intercept("update_feishu_card", True)
        return True

    try:
        token = await feishu_client.get_tenant_access_token()
        url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = {"msg_type": "interactive", "content": json.dumps(card_content, ensure_ascii=False)}
        async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
            resp = await client.patch(url, headers=headers, json=payload)
            res_json = resp.json()
            if res_json.get("code") != 0:
                print(f"⚠️ 飞书卡片原地更新失败: {res_json}")
                return False
            return True
    except Exception as e:
        print(f"⚠️ 飞书卡片原地更新异常: {e}")
        return False
