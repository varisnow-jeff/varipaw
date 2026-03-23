import asyncio
import tempfile
import unittest

from varipaw.capabilities.tools.shell import ShellConfig, ShellTool


class TestShellTool(unittest.TestCase):
    def test_validate_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tool = ShellTool(ShellConfig(sandbox_dir=tmp))
            tool.validate_arguments({"argv": ["echo", "hi"]})
            with self.assertRaises(ValueError):
                tool.validate_arguments({"argv": []})
            with self.assertRaises(ValueError):
                tool.validate_arguments({"argv": ["echo"], "cwd": "/abs/path"})

    def test_run_requires_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = ShellConfig(
                sandbox_dir=tmp,
                whitelist=frozenset({"echo"}),
                blacklist_patterns=(r"\becho\b",),
            )
            tool = ShellTool(config)
            result = asyncio.run(tool.run({"argv": ["echo", "x"]}))
            self.assertEqual(result["status"], "REQUIRES_CONFIRMATION")


if __name__ == "__main__":
    unittest.main()
