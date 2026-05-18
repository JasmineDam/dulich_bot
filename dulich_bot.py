"""
✈️ Telegram Bot Chi Tiêu Du Lịch - Đơn giản
"""

import os
import json
import logging
import httpx
import base64
from datetime import datetime
from google.oauth2.service_account import Credentials
import gspread
import anthropic
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN_DULICH"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
SHEET_ID = os.environ["SHEET_ID_DULICH"]
GOOGLE_CREDS = json.loads(os.environ["GOOGLE_CREDS"])
TRIP_NAME = os.environ.get("TRIP_NAME", "Du Lich")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SCOPES = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = Credentials.from_service_account_info(GOOGLE_CREDS, scopes=SCOPES)
gc = gspread.authorize(creds)
sh = gc.open_by_key(SHEET_ID)


def get_or_create_sheet():
    try:
        ws = sh.worksheet(TRIP_NAME)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=TRIP_NAME, rows=1000, cols=5)
        ws.append_row(["Thời gian", "Số tiền", "Mô tả", "Người chi", "Tổng cộng"])
    return ws


def add_expense(amount: int, description: str, user_name: str) -> dict:
    ws = get_or_create_sheet()
    records = ws.get_all_values()
    total = 0
    for row in records[1:]:
        if row and len(row) > 1 and row[1]:
            try:
                val = str(row[1]).replace(',', '').replace('đ', '').strip()
                if val.lstrip('-').isdigit():
                    total += int(val)
            except:
                pass
    total += amount
    time_str = datetime.now().strftime("%H:%M %d/%m/%Y")
    count = len(records)
    ws.append_row([time_str, amount, description, user_name, total])
    return {"total": total, "count": count}


def get_summary() -> dict:
    ws = get_or_create_sheet()
    records = ws.get_all_values()[1:]
    total = 0
    by_person = {}
    for row in records:
        if not row or len(row) < 4:
            continue
        try:
            val = str(row[1]).replace(',', '').replace('đ', '').strip()
            if not val.lstrip('-').isdigit():
                continue
            amount = int(val)
            person = row[3] if len(row) > 3 else "?"
            total += amount
            by_person[person] = by_person.get(person, 0) + amount
        except:
            pass
    return {"total": total, "by_person": by_person, "count": len(records)}


def extract_expense_from_image(image_bytes: bytes) -> dict:
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    response = claude.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}},
                {"type": "text", "text": (
                    "Đây là ảnh hóa đơn hoặc giao dịch. "
                    "Tìm TỔNG SỐ TIỀN THANH TOÁN. "
                    "Nếu USD thì quy đổi sang VND (1 USD = 26000 VND). "
                    'Trả về JSON: {"amount": <tổng tiền VND>, "description": "<mô tả ngắn>"}\n'
                    "Chỉ trả về JSON thuần, không markdown."
                )}
            ],
        }]
    )
    text = response.content[0].text.strip().replace("```json", "").replace("```", "").strip()
    return json.loads(text)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"✈️ Bot chi tiêu *{TRIP_NAME}*\n\n"
        "📸 Gửi ảnh hóa đơn → bot tự đọc\n"
        "📸 Gửi ảnh + caption → dùng caption làm mô tả\n"
        "💬 Gõ: `90000 cafe` để ghi nhanh\n\n"
        "📊 Lệnh:\n"
        "/total – Tổng chi tiêu\n"
        "/summary – Tổng kết theo người\n"
        "/history – Lịch sử giao dịch\n"
        "/reset – Xóa toàn bộ dữ liệu",
        parse_mode="Markdown",
    )


async def cmd_total(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = get_summary()
    if data["count"] == 0:
        await update.message.reply_text("📭 Chưa có giao dịch nào.")
        return
    await update.message.reply_text(
        f"✈️ *Tổng chi tiêu {TRIP_NAME}*\n"
        f"💰 `{data['total']:,.0f} VND`\n"
        f"🧾 {data['count']} giao dịch",
        parse_mode="Markdown",
    )


async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = get_summary()
    if data["count"] == 0:
        await update.message.reply_text("📭 Chưa có giao dịch nào.")
        return
    lines = [f"✈️ *Tổng kết {TRIP_NAME}*\n"]
    for person, amt in sorted(data["by_person"].items(), key=lambda x: -x[1]):
        pct = amt / data["total"] * 100 if data["total"] > 0 else 0
        lines.append(f"👤 *{person}*: `{amt:,.0f} VND` ({pct:.0f}%)")
    lines.append(f"\n💰 *Tổng: {data['total']:,.0f} VND*")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ws = get_or_create_sheet()
    records = ws.get_all_values()[1:]
    if not records:
        await update.message.reply_text("📭 Chưa có giao dịch nào.")
        return
    lines = [f"🗂 *Lịch sử {TRIP_NAME}*\n"]
    for i, row in enumerate(records[-20:], 1):
        if row and len(row) >= 4:
            try:
                amt = int(str(row[1]).replace(',', '').strip())
                lines.append(f"{i}. `{amt:,.0f}` – {row[2]} _{row[3]}_ _{row[0]}_")
            except:
                pass
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ws = get_or_create_sheet()
    ws.clear()
    ws.append_row(["Thời gian", "Số tiền", "Mô tả", "Người chi", "Tổng cộng"])
    await update.message.reply_text("🗑 Đã xóa toàn bộ dữ liệu.")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ Đang đọc ảnh...")
    try:
        photo = update.message.photo[-1]
        tg_file = await context.bot.get_file(photo.file_id)
        async with httpx.AsyncClient() as http:
            resp = await http.get(tg_file.file_path)
            image_bytes = resp.content

        caption = update.message.caption
        if caption and caption.strip():
            description = caption.strip()
            result = extract_expense_from_image(image_bytes)
            amount = int(result["amount"])
        else:
            result = extract_expense_from_image(image_bytes)
            amount = int(result["amount"])
            description = result.get("description", "Không rõ")

        user_name = update.effective_user.first_name or "Unknown"
        data = add_expense(amount, description, user_name)
        await msg.edit_text(
            f"✅ *Đã ghi nhận!*\n"
            f"💸 `{amount:,.0f} VND` – {description}\n\n"
            f"✈️ *Tổng chuyến đi:* `{data['total']:,.0f} VND` ({data['count']} giao dịch)",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"Lỗi: {e}")
        await msg.edit_text("❌ Không đọc được ảnh. Thử gõ tay: `90000 cafe`")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        parts = text.split(maxsplit=1)
        amount = int(parts[0].replace(',', '').replace('.', '').replace('-', ''))
        description = parts[1] if len(parts) > 1 else "Không rõ"
        user_name = update.effective_user.first_name or "Unknown"
        data = add_expense(amount, description, user_name)
        await update.message.reply_text(
            f"✅ *Đã ghi nhận!*\n"
            f"💸 `{amount:,.0f} VND` – {description}\n\n"
            f"✈️ *Tổng chuyến đi:* `{data['total']:,.0f} VND` ({data['count']} giao dịch)",
            parse_mode="Markdown",
        )
    except:
        await update.message.reply_text("⚠️ Không hiểu. Thử gõ: `90000 cafe`")


def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("total", cmd_total))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print(f"✈️ Bot du lịch đang chạy: {TRIP_NAME}")
    app.run_polling()


if __name__ == "__main__":
    main()
