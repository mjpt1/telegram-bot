"""AI helpers (Claude API): smart AFK replies, chat summaries, .ai command.

Settings live in store "ai" and are edited from the panel:
  key     -> Anthropic API key (console.anthropic.com)
  model   -> model id
  afk_ai  -> when AFK is on, answer private messages with AI instead of fixed text
  prompt  -> extra instruction for the AFK assistant

.ai سوال          -> ask Claude, answer is edited into your message
.ai (reply)       -> ask about the replied message
"""
import logging

from pyrogram import Client
from pyrogram.types import Message

from core import args_text, command, edit, store
from core.http import session

log = logging.getLogger("userbot.ai")
API_URL = "https://api.anthropic.com/v1/messages"
cfg = store.get("ai", {"key": "", "model": "claude-haiku-5-5", "afk_ai": False,
                       "prompt": "کوتاه و مؤدبانه جواب بده و بگو صاحب اکانت بعداً پاسخ می‌دهد."})


def ready() -> bool:
    return bool(cfg.get("key"))


async def ask(prompt: str, system: str = "", max_tokens: int = 800) -> str:
    """One Claude call. Raises RuntimeError with a Persian message on failure."""
    if not ready():
        raise RuntimeError("کلید API هوش مصنوعی در پنل تنظیم نشده")
    body = {"model": cfg.get("model") or "claude-haiku-5-5", "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}]}
    if system:
        body["system"] = system
    headers = {"x-api-key": cfg["key"], "anthropic-version": "2023-06-01", "content-type": "application/json"}
    async with session(timeout=90) as s, s.post(API_URL, json=body, headers=headers) as r:
        data = await r.json(content_type=None)
    if r.status != 200:
        msg = (data.get("error") or {}).get("message", str(data))[:200]
        raise RuntimeError(f"خطای API ({r.status}): {msg}")
    return "".join(b.get("text", "") for b in data.get("content", [])).strip()


async def afk_reply(message: Message, reason: str) -> str:
    """Text for an AI-powered AFK reply."""
    system = ("تو منشی تلگرام صاحب این اکانت هستی. او الان در دسترس نیست. "
              f"دلیل غیبت: {reason}. {cfg.get('prompt', '')} "
              "هرگز قول یا تصمیمی از طرف او نده و اطلاعات شخصی او را فاش نکن. به زبان پیام جواب بده.")
    return await ask(message.text or message.caption or "(پیام بدون متن)", system, max_tokens=300)


async def summarize(lines: list[str]) -> str:
    text = "\n".join(lines)[-12000:]
    return await ask(text, "این پیام‌های یک چت تلگرام است. خلاصه‌ای فارسی، کوتاه و نکته‌وار بنویس: "
                           "موضوعات اصلی، تصمیم‌ها، و هر چیزی که به صاحب اکانت مربوط است.", max_tokens=1000)


@command("ai", "پرسش از هوش مصنوعی: .ai سوال (یا ریپلای روی پیام)")
async def ai_cmd(client: Client, message: Message):
    q = args_text(message).strip()
    reply = message.reply_to_message
    ctx = (reply.text or reply.caption) if reply else ""
    if not q and not ctx:
        return await edit(message, "استفاده: `.ai سوالت`  یا روی پیام ریپلای کن: `.ai خلاصه کن`")
    await edit(message, "🧠 ...")
    prompt = f"{ctx}\n\n{q}" if ctx else q
    answer = await ask(prompt, "به فارسی و کوتاه جواب بده مگر اینکه خلافش خواسته شود.")
    await edit(message, f"🧠 {answer}"[:4000])
