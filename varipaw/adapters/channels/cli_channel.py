"""CLI channel for VariPaw."""

from __future__ import annotations

import asyncio
from uuid import uuid4

from varipaw.app.bootstrap import AppContainer, bootstrap_app
from varipaw.core.contracts import UserMessage

__all__ = ["run_cli", "main"]

_CONFIRMATION_STATUS = "REQUIRES_CONFIRMATION"


async def _input(prompt: str = "") -> str:
    """Non-blocking input that won't stall the event loop."""
    return await asyncio.to_thread(input, prompt)


def _find_pending_confirmation(response) -> tuple | None:
    """Return pending tool call when confirmation is required."""
    for step in response.steps:
        if (
            step.observation == "confirmation required"
            and step.action is not None
        ):
            return step.action
    return None


async def run_cli(container: AppContainer) -> None:
    while True:
        try:
            user_id = (await _input("user_id: ")).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            return
        if user_id:
            break

    session_id = f"cli_{user_id}_{uuid4().hex[:8]}"

    print("\nVariPaw CLI")
    print("Type your message and press Enter.")
    print("Type 'exit' or 'quit' to leave.\n")

    while True:
        try:
            text = await _input("> ")
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if text.strip().lower() in {"exit", "quit"}:
            print("Bye.")
            break

        if not text.strip():
            continue

        message = UserMessage(
            session_id=session_id,
            user_id=user_id,
            text=text,
        )

        try:
            response = await container.loop.run(message)
        except Exception as exc:
            print(f"[internal error] {exc}")
            continue

        print(response.text)

        # --- Confirmation flow ---
        pending_call = _find_pending_confirmation(response)
        if pending_call is not None:
            try:
                answer = (await _input("确认 (yes/no): ")).strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nCancelled.")
                print()
                continue

            if answer in {"yes", "y"}:
                try:
                    response = await container.loop.resume_confirmed_tool(
                        user_message=message,
                        original_call=pending_call,
                    )
                except Exception as exc:
                    print(f"[internal error] {exc}")
                    print()
                    continue
                print(response.text)
            else:
                print("已取消。")

        print()


def main() -> None:
    try:
        container = bootstrap_app()
        asyncio.run(run_cli(container))
    except KeyboardInterrupt:
        print("\nBye.")
    except Exception as exc:
        print(f"[startup error] {exc}")


if __name__ == "__main__":
    main()
