import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tests._offline_imports import offline_dependencies

with offline_dependencies():
    from varipaw.adapters.channels import telegram_channel


class TestTelegramChannel(unittest.TestCase):
    def test_find_pending_confirmation(self) -> None:
        action = SimpleNamespace(name="shell")
        response = SimpleNamespace(
            steps=[
                SimpleNamespace(observation="ok", action=None),
                SimpleNamespace(observation="confirmation required", action=action),
            ]
        )
        self.assertIs(telegram_channel._find_pending_confirmation(response), action)

    def test_yes_no_flags(self) -> None:
        self.assertTrue(telegram_channel._is_yes("yes"))
        self.assertTrue(telegram_channel._is_yes("确认"))
        self.assertTrue(telegram_channel._is_no("no"))
        self.assertTrue(telegram_channel._is_no("取消"))

    def test_main_requires_token(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with patch("dotenv.load_dotenv"), patch("builtins.print") as mocked_print:
                telegram_channel.main()
        self.assertTrue(any("TELEGRAM_BOT_TOKEN is required" in str(c.args[0]) for c in mocked_print.call_args_list))

    def test_handle_text_sends_once_when_confirmation_required(self) -> None:
        class FakeMessage:
            def __init__(self, text: str) -> None:
                self.text = text
                self.sent: list[str] = []

            async def reply_text(self, text: str) -> None:
                self.sent.append(text)

        class FakeLoop:
            async def run(self, user_message):
                return SimpleNamespace(
                    text="需要确认",
                    steps=[SimpleNamespace(observation="confirmation required", action=SimpleNamespace(name="shell"))],
                )

        update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=1),
            effective_user=SimpleNamespace(id=2),
            message=FakeMessage("do it"),
        )
        context = SimpleNamespace(
            application=SimpleNamespace(bot_data={"container": SimpleNamespace(loop=FakeLoop())}),
            chat_data={},
        )
        asyncio.run(telegram_channel._handle_text(update, context))
        self.assertEqual(len(update.message.sent), 1)
        self.assertIn("需要确认", update.message.sent[0])
        self.assertIn("yes 或 no", update.message.sent[0])


if __name__ == "__main__":
    unittest.main()
