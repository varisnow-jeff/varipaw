from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

from varipaw.app.bootstrap import AppContainer, bootstrap_app
from varipaw.core.contracts import ToolCall, UserMessage

try:
    from telegram import Update
    from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
except Exception:
    Update = object
    Application = None
    CommandHandler = None
    ContextTypes = None
    MessageHandler = None
    filters = None

__all__ = ["run_telegram", "main"]


@dataclass(slots=True)
class PendingConfirmation:
    user_message: UserMessage
    tool_call: ToolCall


def _find_pending_confirmation(response) -> ToolCall | None:
    for step in response.steps:
        if step.observation == "confirmation required" and step.action is not None:
            return step.action
    return None


def _is_yes(text: str) -> bool:
    return text.strip().lower() in {"yes", "y", "是", "确认", "同意"}


def _is_no(text: str) -> bool:
    return text.strip().lower() in {"no", "n", "否", "取消"}


async def _handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("VariPaw Telegram Bot 已启动。直接发送消息即可。")


async def _handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("发送问题开始对话。若工具需要确认，请回复 yes/no。")


async def _handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.effective_user is None or update.message is None:
        return
    text = (update.message.text or "").strip()
    if not text:
        return

    container: AppContainer = context.application.bot_data["container"]
    pending: PendingConfirmation | None = context.chat_data.get("pending_confirmation")
    if pending is not None:
        if _is_yes(text):
            try:
                response = await container.loop.resume_confirmed_tool(
                    user_message=pending.user_message,
                    original_call=pending.tool_call,
                )
            except Exception as exc:
                await update.message.reply_text(f"[internal error] {exc}")
                return
            context.chat_data.pop("pending_confirmation", None)
            await update.message.reply_text(response.text)
            return
        if _is_no(text):
            context.chat_data.pop("pending_confirmation", None)
            await update.message.reply_text("已取消。")
            return
        await update.message.reply_text("当前有待确认操作，请回复 yes 或 no。")
        return

    session_id = f"tg_{update.effective_chat.id}"
    user_id = f"tg_{update.effective_user.id}"
    message = UserMessage(session_id=session_id, user_id=user_id, text=text)
    try:
        response = await container.loop.run(message)
    except Exception as exc:
        await update.message.reply_text(f"[internal error] {exc}")
        return

    pending_call = _find_pending_confirmation(response)
    if pending_call is not None:
        context.chat_data["pending_confirmation"] = PendingConfirmation(
            user_message=message,
            tool_call=pending_call,
        )
        await update.message.reply_text(f"{response.text}\n\n检测到高风险操作，请回复 yes 或 no。")
        return
    await update.message.reply_text(response.text)


async def run_telegram(container: AppContainer, token: str) -> None:
    if Application is None:
        raise RuntimeError("python-telegram-bot is required, install with: pip install python-telegram-bot")

    app = Application.builder().token(token).build()
    app.bot_data["container"] = container
    app.add_handler(CommandHandler("start", _handle_start))
    app.add_handler(CommandHandler("help", _handle_help))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), _handle_text))
    
    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        print("✅ Telegram bot is running. Press Ctrl+C to stop.")
        stop_event = asyncio.Event()
        try:
            await stop_event.wait()
        except asyncio.CancelledError:
            pass
        finally:
            await app.updater.stop()
            await app.stop()
            await app.shutdown()


def main() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv()

        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
        container = bootstrap_app()
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(run_telegram(container, token))
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
