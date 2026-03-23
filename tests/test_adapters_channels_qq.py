"""Offline tests for QQ channel (WebSocket / OneBot v11)."""
from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from varipaw.adapters.channels.qq_channel import (
    _build_ws_url,
    _extract_text,
    _parse_event,
    _send_message,
)


class TestExtractText(unittest.TestCase):
    def test_string_message(self) -> None:
        self.assertEqual(_extract_text("hello"), "hello")

    def test_list_message_single(self) -> None:
        msg = [{"type": "text", "data": {"text": "hello"}}]
        self.assertEqual(_extract_text(msg), "hello")

    def test_list_message_multi(self) -> None:
        msg = [
            {"type": "text", "data": {"text": "hello "}},
            {"type": "at", "data": {"qq": "123"}},
            {"type": "text", "data": {"text": "world"}},
        ]
        self.assertEqual(_extract_text(msg), "hello world")

    def test_list_message_no_text(self) -> None:
        msg = [{"type": "image", "data": {"url": "http://x.png"}}]
        self.assertEqual(_extract_text(msg), "")

    def test_empty(self) -> None:
        self.assertEqual(_extract_text(""), "")
        self.assertEqual(_extract_text([]), "")
        self.assertEqual(_extract_text(None), "")


class TestParseEvent(unittest.TestCase):
    def _private_event(self, text: str = "hi") -> dict:
        return {
            "post_type": "message",
            "message_type": "private",
            "user_id": 12345,
            "message": [{"type": "text", "data": {"text": text}}],
        }

    def _group_event(self, text: str = "hi") -> dict:
        return {
            "post_type": "message",
            "message_type": "group",
            "user_id": 12345,
            "group_id": 67890,
            "message": [{"type": "text", "data": {"text": text}}],
        }

    def test_private_message(self) -> None:
        result = _parse_event(self._private_event("hello"))
        self.assertIsNotNone(result)
        session_id, user_id, text, payload = result
        self.assertEqual(session_id, "qq_private_12345")
        self.assertEqual(user_id, "qq_12345")
        self.assertEqual(text, "hello")
        self.assertEqual(payload["action"], "send_private_msg")
        self.assertEqual(payload["params"]["user_id"], 12345)

    def test_group_message(self) -> None:
        result = _parse_event(self._group_event("world"))
        self.assertIsNotNone(result)
        session_id, user_id, text, payload = result
        self.assertEqual(session_id, "qq_group_67890")
        self.assertEqual(user_id, "qq_12345")
        self.assertEqual(text, "world")
        self.assertEqual(payload["action"], "send_group_msg")
        self.assertEqual(payload["params"]["group_id"], 67890)

    def test_non_message_event(self) -> None:
        event = {"post_type": "notice", "notice_type": "group_increase"}
        self.assertIsNone(_parse_event(event))

    def test_empty_text(self) -> None:
        event = self._private_event("")
        event["raw_message"] = ""
        self.assertIsNone(_parse_event(event))

    def test_missing_group_id(self) -> None:
        event = self._group_event("hi")
        del event["group_id"]
        self.assertIsNone(_parse_event(event))

    def test_fallback_raw_message(self) -> None:
        event = {
            "post_type": "message",
            "message_type": "private",
            "user_id": 99,
            "message": [],
            "raw_message": "fallback text",
        }
        result = _parse_event(event)
        self.assertIsNotNone(result)
        self.assertEqual(result[2], "fallback text")


class TestBuildWsUrl(unittest.TestCase):
    def test_no_token(self) -> None:
        self.assertEqual(
            _build_ws_url("ws://localhost:3001/ws", ""),
            "ws://localhost:3001/ws",
        )

    def test_with_token(self) -> None:
        self.assertEqual(
            _build_ws_url("ws://localhost:3001/ws", "mytoken"),
            "ws://localhost:3001/ws?access_token=mytoken",
        )

    def test_with_token_existing_query(self) -> None:
        self.assertEqual(
            _build_ws_url("ws://localhost:3001/ws?foo=bar", "mytoken"),
            "ws://localhost:3001/ws?foo=bar&access_token=mytoken",
        )


class TestSendMessage(unittest.IsolatedAsyncioTestCase):
    async def test_send_private(self) -> None:
        ws = AsyncMock()
        payload = {
            "action": "send_private_msg",
            "params": {"user_id": 12345, "message": ""},
        }
        await _send_message(ws, payload, "hello")
        ws.send.assert_called_once()
        sent = json.loads(ws.send.call_args[0][0])
        self.assertEqual(sent["action"], "send_private_msg")
        self.assertEqual(sent["params"]["user_id"], 12345)
        self.assertEqual(sent["params"]["message"], "hello")

    async def test_send_group(self) -> None:
        ws = AsyncMock()
        payload = {
            "action": "send_group_msg",
            "params": {"group_id": 67890, "message": ""},
        }
        await _send_message(ws, payload, "world")
        ws.send.assert_called_once()
        sent = json.loads(ws.send.call_args[0][0])
        self.assertEqual(sent["action"], "send_group_msg")
        self.assertEqual(sent["params"]["group_id"], 67890)
        self.assertEqual(sent["params"]["message"], "world")

    async def test_send_does_not_mutate_original(self) -> None:
        ws = AsyncMock()
        payload = {
            "action": "send_private_msg",
            "params": {"user_id": 1, "message": ""},
        }
        await _send_message(ws, payload, "test")
        # original payload should not be mutated
        self.assertEqual(payload["params"]["message"], "")


if __name__ == "__main__":
    unittest.main()
