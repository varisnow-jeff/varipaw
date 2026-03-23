import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tests._offline_imports import offline_dependencies

with offline_dependencies():
    from varipaw.adapters.channels import cli_channel


class TestCliChannel(unittest.TestCase):
    def test_find_pending_confirmation(self) -> None:
        action = SimpleNamespace(name="shell")
        response = SimpleNamespace(
            steps=[
                SimpleNamespace(observation="ok", action=None),
                SimpleNamespace(observation="confirmation required", action=action),
            ]
        )
        pending = cli_channel._find_pending_confirmation(response)
        self.assertIs(pending, action)

    def test_find_pending_confirmation_none(self) -> None:
        response = SimpleNamespace(steps=[SimpleNamespace(observation="ok", action=None)])
        pending = cli_channel._find_pending_confirmation(response)
        self.assertIsNone(pending)

    def test_main_startup_error(self) -> None:
        with patch.object(cli_channel, "bootstrap_app", side_effect=RuntimeError("boom")):
            with patch("builtins.print") as mocked_print:
                cli_channel.main()
        self.assertTrue(any("[startup error]" in str(call.args[0]) for call in mocked_print.call_args_list))


if __name__ == "__main__":
    unittest.main()
