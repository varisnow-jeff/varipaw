from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from varipaw.core.contracts import ToolCall, UserMessage
if TYPE_CHECKING:
    from varipaw.app.bootstrap import AppContainer

try:
    import websockets
    from websockets.client import WebSocketClientProtocol
except Exception:
    websockets = None
    WebSocketClientProtocol = object

__all__ = ["run_qq", "main"]

logger = logging.getLogger(__name__)

RECONNECT_INTERVAL = 5


@dataclass(slots=True)
class PendingConfirmation:
    user_message: UserMessage
    tool_call: ToolCall


# --------------- helpers ---------------

def _find_pending_confirmation(response) -> ToolCall | None:
    for step in response.steps:
        if step.observation == "confirmation required" and step.action is not None:
            return step.action
    return None


def _is_yes(text: str) -> bool:
    return text.strip().lower() in {"yes", "y", "是", "确认", "同意"}


def _is_no(text: str) -> bool:
    return text.strip().lower() in {"no", "n", "否", "取消"}


def _extract_text(message: Any) -> str:
    """从 OneBot v11 message 数组中提取纯文本。"""
    if isinstance(message, str):
        return message.strip()
    if isinstance(message, list):
        parts: list[str] = []
        for seg in message:
            if isinstance(seg, dict) and seg.get("type") == "text":
                t = seg.get("data", {}).get("text", "")
                if t:
                    parts.append(t)
        return "".join(parts).strip()
    return ""


def _parse_event(event: dict[str, Any]) -> tuple[str, str, str, dict[str, Any]] | None:
    """
    解析 OneBot v11 事件，返回 (session_id, user_id, text, send_payload) 或 None。
    """
    if event.get("post_type") != "message":
        return None

    message_type = event.get("message_type")
    raw_user_id = event.get("user_id")
    if not isinstance(raw_user_id, int):
        return None

    text = _extract_text(event.get("message", ""))
    if not text:
        # fallback to raw_message
        text = str(event.get("raw_message", "")).strip()
    if not text:
        return None

    user_id = f"qq_{raw_user_id}"

    if message_type == "private":
        session_id = f"qq_private_{raw_user_id}"
        send_payload = {
            "action": "send_private_msg",
            "params": {"user_id": raw_user_id, "message": ""},
        }
        return session_id, user_id, text, send_payload

    if message_type == "group":
        group_id = event.get("group_id")
        if not isinstance(group_id, int):
            return None
        session_id = f"qq_group_{group_id}"
        send_payload = {
            "action": "send_group_msg",
            "params": {"group_id": group_id, "message": ""},
        }
        return session_id, user_id, text, send_payload

    return None


def _build_ws_url(base_url: str, access_token: str) -> str:
    if access_token:
        sep = "&" if "?" in base_url else "?"
        return f"{base_url}{sep}access_token={access_token}"
    return base_url


# --------------- core ---------------

async def _send_message(
    ws: WebSocketClientProtocol,
    send_payload: dict[str, Any],
    text: str,
) -> None:
    """通过 WebSocket 发送 OneBot v11 API 调用。"""
    payload = json.loads(json.dumps(send_payload))  # deep copy
    payload["params"]["message"] = text
    await ws.send(json.dumps(payload, ensure_ascii=False))


async def _handle_event(
    ws: WebSocketClientProtocol,
    event: dict[str, Any],
    container: "AppContainer",
    pending_store: dict[str, PendingConfirmation],
) -> None:
    parsed = _parse_event(event)
    if parsed is None:
        return

    session_id, user_id, text, send_payload = parsed

    # --- 确认流 ---
    pending = pending_store.get(session_id)
    if pending is not None:
        if _is_yes(text):
            try:
                response = await container.loop.resume_confirmed_tool(
                    user_message=pending.user_message,
                    original_call=pending.tool_call,
                )
            except Exception as exc:
                await _send_message(ws, send_payload, f"[internal error] {exc}")
                return
            pending_store.pop(session_id, None)
            await _send_message(ws, send_payload, response.text)
            return
        if _is_no(text):
            pending_store.pop(session_id, None)
            await _send_message(ws, send_payload, "已取消。")
            return
        await _send_message(ws, send_payload, "当前有待确认操作，请回复 yes 或 no。")
        return

    # --- 普通消息 ---
    user_message = UserMessage(session_id=session_id, user_id=user_id, text=text)
    try:
        response = await container.loop.run(user_message)
    except Exception as exc:
        await _send_message(ws, send_payload, f"[internal error] {exc}")
        return

    pending_call = _find_pending_confirmation(response)
    if pending_call is not None:
        pending_store[session_id] = PendingConfirmation(
            user_message=user_message,
            tool_call=pending_call,
        )
        await _send_message(
            ws, send_payload,
            f"{response.text}\n\n检测到高风险操作，请回复 yes 或 no。",
        )
        return

    await _send_message(ws, send_payload, response.text)


async def run_qq(container: "AppContainer", ws_url: str, access_token: str = "") -> None:
    if websockets is None:
        raise RuntimeError(
            "websockets is required, install with: pip install 'varipaw[qq]'"
        )

    url = _build_ws_url(ws_url, access_token)
    pending_store: dict[str, PendingConfirmation] = {}

    while True:
        try:
            logger.info("Connecting to %s ...", ws_url)
            print(f"✅ QQ bot connecting to {ws_url} ...")
            async with websockets.connect(url) as ws:
                print(f"✅ QQ bot connected to {ws_url}")
                logger.info("Connected to %s", ws_url)
                async for raw in ws:
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    # 不阻塞接收循环，后台处理事件
                    asyncio.create_task(
                        _handle_event(ws, event, container, pending_store)
                    )
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("WebSocket disconnected: %s. Reconnecting in %ds...", exc, RECONNECT_INTERVAL)
            print(f"⚠️  WebSocket disconnected: {exc}. Reconnecting in {RECONNECT_INTERVAL}s...")
            await asyncio.sleep(RECONNECT_INTERVAL)


def main() -> None:
    try:
        from dotenv import load_dotenv
        from varipaw.app.bootstrap import bootstrap_app
        load_dotenv()

        ws_url = os.environ.get("QQ_WS_URL", "ws://localhost:3001/ws").strip()
        access_token = os.environ.get("QQ_ACCESS_TOKEN", "").strip()

        container = bootstrap_app()
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(run_qq(container, ws_url, access_token))
        except KeyboardInterrupt:
            print("\nBye.")
        finally:
            loop.close()
    except KeyboardInterrupt:
        print("\nBye.")
    except Exception as exc:
        print(f"[startup error] {exc}")


if __name__ == "__main__":
    main()
