import logging
import sqlite3
import re
import requests
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# ========== НАСТРОЙКИ ==========
TOKEN = "8924965576:AAFDrB6Tdb0s_NExdT-ZBtUht5WdGI6slWM"
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== БАЗА ДАННЫХ ==========
def init_db():
    conn = sqlite3.connect("prices.db")
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            url TEXT,
            offer_id TEXT,
            last_price REAL,
            name TEXT
        )
    """)
    conn.commit()
    conn.close()

def add_item(user_id, url, offer_id, name=""):
    conn = sqlite3.connect("prices.db")
    cur = conn.cursor()
    cur.execute("INSERT INTO items (user_id, url, offer_id, last_price, name) VALUES (?, ?, ?, ?, ?)",
                (user_id, url, offer_id, None, name))
    conn.commit()
    conn.close()

def get_items(user_id):
    conn = sqlite3.connect("prices.db")
    cur = conn.cursor()
    cur.execute("SELECT url, offer_id, last_price, name, id FROM items WHERE user_id=?", (user_id,))
    items = cur.fetchall()
    conn.close()
    return items

def delete_item(user_id, item_id):
    conn = sqlite3.connect("prices.db")
    cur = conn.cursor()
    cur.execute("DELETE FROM items WHERE user_id=? AND id=?", (user_id, item_id))
    conn.commit()
    conn.close()

def extract_offer_id(url):
    match = re.search(r'/product/(\d+)', url)
    return match.group(1) if match else None

def get_price(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        r = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        price_tag = soup.find("span", {"data-auto": "price"})
        if not price_tag:
            price_tag = soup.find("span", class_="price")
        if price_tag:
            raw = price_tag.text.replace(" ", "").replace("₽", "").replace(",", ".").strip()
            numbers = re.findall(r'[\d.]+', raw)
            if numbers:
                return float(numbers[0])
        return None
    except Exception as e:
        logger.error(f"Ошибка парсинга: {e}")
        return None

# ========== КЛАВИАТУРЫ ==========
def main_menu():
    keyboard = [
        [InlineKeyboardButton("➕ Добавить товар", callback_data="add")],
        [InlineKeyboardButton("📋 Мои товары", callback_data="list")],
        [InlineKeyboardButton("🔄 Проверить сейчас", callback_data="check")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ========== БОТ ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    init_db()
    await update.message.reply_text(
        "🛍️ <b>Price Tracker</b>\n\nДобавьте ссылку на товар с Яндекс.Маркета.",
        parse_mode="HTML",
        reply_markup=main_menu()
    )

async def add_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🔗 Отправьте ссылку на товар:\n<code>https://market.yandex.ru/product/1234567890</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="cancel")]])
    )

async def cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("✅ Отменено", reply_markup=main_menu())

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    url = update.message.text.strip()
    offer_id = extract_offer_id(url)
    
    if not offer_id:
        await update.message.reply_text("❌ Неверная ссылка", reply_markup=main_menu())
        return
    
    price = get_price(url)
    if price:
        add_item(user_id, url, offer_id, f"Товар {offer_id}")
        await update.message.reply_text(f"✅ Товар добавлен!\n💰 Цена: {price} ₽", reply_markup=main_menu())
    else:
        await update.message.reply_text("❌ Не удалось получить цену", reply_markup=main_menu())

async def list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    items = get_items(user_id)
    
    if not items:
        await query.edit_message_text("📭 Нет товаров", reply_markup=main_menu())
        return
    
    text = "📋 Ваши товары:\n\n"
    keyboard = []
    for url, offer_id, price, name, item_id in items:
        text += f"▪️ {name or offer_id}\n   💰 {price or '?'} ₽\n   🆔 {offer_id}\n\n"
        keyboard.append([InlineKeyboardButton(f"🗑️ Удалить {item_id}", callback_data=f"delete_{item_id}")])
    
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    item_id = int(query.data.split("_")[1])
    delete_item(user_id, item_id)
    await query.edit_message_text("✅ Товар удалён", reply_markup=main_menu())

async def back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("📋 Главное меню", reply_markup=main_menu())

async def check_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🔄 Проверка цен...", reply_markup=main_menu())
    # Здесь можно добавить логику проверки цен

# ========== ЗАПУСК ==========
if __name__ == "__main__":
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(add_callback, pattern="^add$"))
    app.add_handler(CallbackQueryHandler(cancel_callback, pattern="^cancel$"))
    app.add_handler(CallbackQueryHandler(list_callback, pattern="^list$"))
    app.add_handler(CallbackQueryHandler(delete_callback, pattern="^delete_"))
    app.add_handler(CallbackQueryHandler(back_callback, pattern="^back$"))
    app.add_handler(CallbackQueryHandler(check_callback, pattern="^check$"))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'market\.yandex\.ru'), handle_url))
    
    logger.info("🤖 Бот запущен!")
    app.run_polling()
