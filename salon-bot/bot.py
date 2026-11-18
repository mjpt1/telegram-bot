"""بات تلگرام سالن زیبایی: ارسال لیست قیمت + رزرو نوبت + یادآوری خودکار."""
import os
import sqlite3
from datetime import datetime, timedelta

import jdatetime
from dotenv import load_dotenv
from telegram import (InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton,
                      ReplyKeyboardMarkup, Update)
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, filters)

import config as C

load_dotenv()
TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
DB = os.path.join(os.path.dirname(__file__), "salon.db")

BTN_PRICES = "💅 لیست قیمت"
BTN_BOOK = "📅 رزرو نوبت"
BTN_MINE = "🗂 نوبت‌های من"
MAIN_KB = ReplyKeyboardMarkup([[BTN_PRICES, BTN_BOOK], [BTN_MINE]], resize_keyboard=True)
WEEKDAYS_FA = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه", "شنبه", "یکشنبه"]
SERVICE_NAMES = list(C.SERVICES)


# ---------- دیتابیس ----------
def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS appointments(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, name TEXT, phone TEXT,
            service TEXT, start TEXT, end TEXT,
            status TEXT DEFAULT 'active', reminded INTEGER DEFAULT 0)""")
        con.execute("CREATE TABLE IF NOT EXISTS customers(user_id INTEGER PRIMARY KEY, name TEXT, phone TEXT)")


def is_free(start: datetime, end: datetime) -> bool:
    with db() as con:
        row = con.execute(
            "SELECT 1 FROM appointments WHERE status='active' AND start < ? AND end > ?",
            (end.isoformat(), start.isoformat())).fetchone()
    return row is None


def free_slots(day: datetime, minutes: int):
    t = day.replace(hour=C.OPEN_HOUR, minute=0, second=0, microsecond=0)
    close = day.replace(hour=C.CLOSE_HOUR, minute=0, second=0, microsecond=0)
    now = datetime.now()
    while t + timedelta(minutes=minutes) <= close:
        if t > now and is_free(t, t + timedelta(minutes=minutes)):
            yield t
        t += timedelta(minutes=C.SLOT_MINUTES)


def fa_date(dt: datetime, short: bool = False) -> str:
    """تاریخ شمسی با نام روز هفته."""
    j = jdatetime.datetime.fromgregorian(datetime=dt)
    d = f"{j.month:02d}/{j.day:02d}" if short else f"{j.year}/{j.month:02d}/{j.day:02d}"
    return f"{WEEKDAYS_FA[dt.weekday()]} {d}"


def fa_when(dt: datetime) -> str:
    return f"{fa_date(dt)} ساعت {dt:%H:%M}"


def money(n: int) -> str:
    return f"{n:,}".replace(",", "٬") + " تومان"


def price_text() -> str:
    lines = [f"✨ لیست قیمت {C.SALON_NAME} ✨\n"]
    for name, (price, mins) in C.SERVICES.items():
        lines.append(f"▫️ {name}: {money(price)}  ({mins} دقیقه)")
    lines.append("\nبرای رزرو، دکمه «رزرو نوبت» را بزنید.")
    return "\n".join(lines)


# ---------- هندلرها ----------
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"سلام! به {C.SALON_NAME} خوش آمدید 🌸\nاز منوی پایین انتخاب کنید.", reply_markup=MAIN_KB)


async def prices(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(price_text())


async def book(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton(f"{n} — {money(p)}", callback_data=f"s|{i}")]
          for i, (n, (p, _)) in enumerate(C.SERVICES.items())]
    await update.message.reply_text("کدام خدمت را می‌خواهید؟", reply_markup=InlineKeyboardMarkup(kb))


async def my_appts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    with db() as con:
        rows = con.execute(
            "SELECT * FROM appointments WHERE user_id=? AND status='active' AND start>? ORDER BY start",
            (update.effective_user.id, datetime.now().isoformat())).fetchall()
    if not rows:
        await update.message.reply_text("نوبت فعالی ندارید.")
        return
    for r in rows:
        s = datetime.fromisoformat(r["start"])
        await update.message.reply_text(
            f"🗓 {r['service']}\n{fa_when(s)}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ لغو نوبت", callback_data=f"x|{r['id']}")]]))


async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    kind, *args = q.data.split("|")

    if kind == "s":  # انتخاب خدمت -> انتخاب روز
        si = int(args[0])
        today = datetime.now()
        kb = []
        for d in range(C.DAYS_AHEAD):
            day = today + timedelta(days=d)
            if day.weekday() in C.CLOSED_WEEKDAYS:
                continue
            kb.append([InlineKeyboardButton(fa_date(day, short=True),
                                            callback_data=f"d|{si}|{day:%Y-%m-%d}")])
        await q.edit_message_text(f"خدمت: {SERVICE_NAMES[si]}\nروز را انتخاب کنید:",
                                  reply_markup=InlineKeyboardMarkup(kb))

    elif kind == "d":  # انتخاب روز -> انتخاب ساعت
        si, day_s = int(args[0]), args[1]
        mins = C.SERVICES[SERVICE_NAMES[si]][1]
        slots = list(free_slots(datetime.strptime(day_s, "%Y-%m-%d"), mins))
        if not slots:
            await q.edit_message_text("این روز وقت خالی ندارد. روز دیگری انتخاب کنید.")
            return
        row, kb = [], []
        for t in slots:
            row.append(InlineKeyboardButton(f"{t:%H:%M}", callback_data=f"t|{si}|{t:%Y-%m-%dT%H:%M}"))
            if len(row) == 4:
                kb.append(row); row = []
        if row:
            kb.append(row)
        await q.edit_message_text("ساعت را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(kb))

    elif kind == "t":  # انتخاب ساعت -> گرفتن شماره تماس
        ctx.user_data["pending"] = (int(args[0]), args[1])
        with db() as con:
            cust = con.execute("SELECT * FROM customers WHERE user_id=?", (q.from_user.id,)).fetchone()
        if cust:
            await finalize(update, ctx, cust["name"], cust["phone"])
        else:
            await q.message.reply_text(
                "برای ثبت نهایی، شماره تماس خود را بفرستید:",
                reply_markup=ReplyKeyboardMarkup([[KeyboardButton("📱 ارسال شماره", request_contact=True)]],
                                                 resize_keyboard=True, one_time_keyboard=True))

    elif kind == "x":  # لغو
        with db() as con:
            r = con.execute("SELECT * FROM appointments WHERE id=? AND user_id=?",
                            (int(args[0]), q.from_user.id)).fetchone()
            con.execute("UPDATE appointments SET status='cancelled' WHERE id=? AND user_id=?",
                        (int(args[0]), q.from_user.id))
        await q.edit_message_text("نوبت لغو شد ✅")
        if r and ADMIN_ID:
            await ctx.bot.send_message(ADMIN_ID, f"❌ لغو نوبت: {r['name']} — {r['service']} — {fa_when(datetime.fromisoformat(r['start']))}")


async def on_contact(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    c = update.message.contact
    name = update.effective_user.full_name
    with db() as con:
        con.execute("INSERT OR REPLACE INTO customers VALUES(?,?,?)", (update.effective_user.id, name, c.phone_number))
    await finalize(update, ctx, name, c.phone_number)


async def finalize(update: Update, ctx: ContextTypes.DEFAULT_TYPE, name: str, phone: str):
    pending = ctx.user_data.pop("pending", None)
    chat = update.effective_chat
    if not pending:
        await chat.send_message("ثبت شد.", reply_markup=MAIN_KB)
        return
    si, start_s = pending
    service = SERVICE_NAMES[si]
    start_t = datetime.fromisoformat(start_s)
    end_t = start_t + timedelta(minutes=C.SERVICES[service][1])
    if not is_free(start_t, end_t):
        await chat.send_message("متأسفانه این ساعت همین الان پر شد. دوباره امتحان کنید.", reply_markup=MAIN_KB)
        return
    with db() as con:
        con.execute("INSERT INTO appointments(user_id,name,phone,service,start,end) VALUES(?,?,?,?,?,?)",
                    (update.effective_user.id, name, phone, service, start_t.isoformat(), end_t.isoformat()))
    when = fa_when(start_t)
    await chat.send_message(f"✅ نوبت شما ثبت شد\n{service}\n{when}\n\n{C.REMINDER_HOURS_BEFORE} ساعت قبل یادآوری می‌کنیم.",
                            reply_markup=MAIN_KB)
    if ADMIN_ID:
        await ctx.bot.send_message(ADMIN_ID, f"🆕 نوبت جدید\n👤 {name} ({phone})\n💇 {service}\n🕒 {when}")


# ---------- مدیر ----------
async def admin_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    day = datetime.now().strftime("%Y-%m-%d")
    with db() as con:
        rows = con.execute("SELECT * FROM appointments WHERE status='active' AND start LIKE ? ORDER BY start",
                           (day + "%",)).fetchall()
    text = "\n".join(f"{r['start'][11:16]} — {r['name']} ({r['phone']}) — {r['service']}" for r in rows)
    await update.message.reply_text(text or "امروز نوبتی نیست.")


async def broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """ارسال لیست قیمت به همه مشتریان: /broadcast"""
    if update.effective_user.id != ADMIN_ID:
        return
    with db() as con:
        ids = [r[0] for r in con.execute("SELECT user_id FROM customers")]
    ok = 0
    for uid in ids:
        try:
            await ctx.bot.send_message(uid, price_text()); ok += 1
        except Exception:
            pass
    await update.message.reply_text(f"لیست قیمت برای {ok} مشتری ارسال شد.")


# ---------- یادآوری خودکار ----------
async def reminder_job(ctx: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    limit = now + timedelta(hours=C.REMINDER_HOURS_BEFORE)
    with db() as con:
        rows = con.execute("SELECT * FROM appointments WHERE status='active' AND reminded=0 AND start>? AND start<=?",
                           (now.isoformat(), limit.isoformat())).fetchall()
        for r in rows:
            s = datetime.fromisoformat(r["start"])
            try:
                await ctx.bot.send_message(r["user_id"], f"⏰ یادآوری: نوبت {r['service']} امروز ساعت {s:%H:%M} در {C.SALON_NAME}")
            except Exception:
                pass
            con.execute("UPDATE appointments SET reminded=1 WHERE id=?", (r["id"],))


def main():
    init_db()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("prices", prices))
    app.add_handler(CommandHandler("today", admin_today))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(MessageHandler(filters.Text([BTN_PRICES]), prices))
    app.add_handler(MessageHandler(filters.Text([BTN_BOOK]), book))
    app.add_handler(MessageHandler(filters.Text([BTN_MINE]), my_appts))
    app.add_handler(MessageHandler(filters.CONTACT, on_contact))
    app.add_handler(MessageHandler(filters.Regex("قیمت|تعرفه|هزینه"), prices))  # پاسخ خودکار به سوال قیمت
    app.add_handler(CallbackQueryHandler(on_callback))
    app.job_queue.run_repeating(reminder_job, interval=600, first=10)
    print("Bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()
