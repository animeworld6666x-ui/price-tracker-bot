import logging
import io
import qrcode
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = "8924965576:AAFDrB6Tdb0s_NExdT-ZBtUht5WdGI6slWM"
logging.basicConfig(level=logging.INFO)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отправь текст, и я сделаю QR-код!")

async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    img = qrcode.make(text)
    bio = io.BytesIO()
    img.save(bio, 'PNG')
    bio.seek(0)
    await update.message.reply_photo(bio, caption=f"QR-код для: {text[:50]}")

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, generate))
    print("✅ Бот запущен!")
    app.run_polling()
