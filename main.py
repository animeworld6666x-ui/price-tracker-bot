import logging
import sqlite3
import re
import requests
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import asyncio
from datetime import datetime

# ========== НАСТРОЙКИ ==========
TOKEN = "8924965576:AAFDrB6Tdb0s_NExdT-ZBtUht5WdGI6slWM"
CHECK_INTERVAL = 1800  # 30 минут
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
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            email TEXT,
            email_enabled INTEGER DEFAULT 0,
            telegram_enabled INTEGER DEFAULT 1
        )
    """)
    conn.commit()
    conn.close()
    logger.info("База данных инициализирована")

def add_user(user_id):
    conn = sqlite3.connect("prices.db")
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO users (user_id, email_enabled, telegram_enabled) VALUES (?, 0, 1)", (user_id,))
    conn.commit()
    conn.close()

def add_item(user_id, url, offer_id, name="", price=None):
    conn = sqlite3.connect("prices.db")
    cur = conn.cursor()
    cur.execute("INSERT INTO items (user_id, url, offer_id, last_price, name) VALUES (?, ?, ?, ?, ?)",
                (user_id, url, offer_id, price, name))
    conn.commit()
    conn.close()

def get_items(user_id):
    conn = sqlite3.connect("prices.db")
    cur = conn.cursor()
    cur.execute("SELECT url, offer_id, last_price, name, id FROM items WHERE user_id=?", (user_id,))
    items = cur.fetchall()
    conn.close()
    return items

def get_all_items():
    conn = sqlite3.connect("prices.db")
    cur = conn.cursor()
    cur.execute("SELECT user_id, url, offer_id, last_price, name FROM items")
    items = cur.fetchall()
    conn.close()
    return items

def update_price(offer_id, price):
    conn = sqlite3.connect("prices.db")
    cur = conn.cursor()
    cur.execute("UPDATE items SET last_price=? WHERE offer_id=?", (price, offer_id))
    conn.commit()
    conn.close()

def delete_item(user_id, item_id):
    conn = sqlite3.connect("prices.db")
    cur = conn.cursor()
    cur.execute("DELETE FROM items WHERE user_id=? AND id=?", (user_id, item_id))
    conn.commit()
    conn.close()

def extract_offer_id(url):
    match = re.search(r'/product/(\d+)', url)
    return match.group(1) if match else None

# ========== ПАРСИНГ ЦЕНЫ ==========
def get_price(url):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Cache-Control": "max-age=0"
        }
        
        session = requests.Session()
        session.cookies.set("yandexuid", "1234567890")
        session.cookies.set("yuidss", "1234567890")
        
        r = session.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        
        soup = BeautifulSoup(r.text, "html.parser")
        
        # Способ 1: data-auto="price"
        price_tag = soup.find("span", {"data-auto": "price"})
        if price_tag:
            raw = price_tag.text.replace(" ", "").replace("₽", "").replace(",", ".").strip()
            numbers = re.findall(r'[\d.]+', raw)
            if numbers:
                return float(numbers[0])
        
        # Способ 2: класс price
        price_tag = soup.find("span", class_="price")
        if price_tag:
            raw = price_tag.text.replace(" ", "").replace("₽", "").replace(",", ".").strip()
            numbers = re.findall(r'[\d.]+', raw)
            if numbers:
                return float(numbers[0])
        
        # Способ 3: meta property
        meta_price = soup.find("meta", {"property": "product:price:amount"})
        if meta_price and meta_price.get("content"):
            try:
                return float(meta_price["content"])
            except:
                pass
        
        # Способ 4: ищем любые числа в span
        all_spans = soup.find_all("span")
        for span in all_spans:
            text = span.text.replace(" ", "").replace("₽", "").replace(",", ".").strip()
            if re.match(r'^\d+\.?\d*$', text) and len(text) > 2:
                try:
                    price = float(text)
                    if price > 10:
                        return price
                except:
                    pass
        
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
    user_id = update.effective_user.id
    add_user(user_id)
    await update.message.reply_text(
        "🛍️ <b>Price Tracker</b>\n\n"
        "Я слежу за ценами на Яндекс.Маркете.\n"
        "Просто добавь ссылку на товар, и я буду отслеживать изменение цены!\n\n"
        "👇 Выберите действие:",
        parse_mode="HTML",
        reply_markup=main_menu()
    )

async def add_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🔗 <b>Отправьте ссылку на товар</b>\n\n"
        "Пример:\n"
        "<code>https://market.yandex.ru/product/1234567890</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel")]
        ])
    )

async def cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("✅ Действие отменено", reply_markup=main_menu())

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    url = update.message.text.strip()
    offer_id = extract_offer_id(url)
    
    if not offer_id:
        await update.message.reply_text(
            "❌ <b>Не удалось распознать товар</b>\n"
            "Убедитесь, что ссылка правильная.",
            parse_mode="HTML",
            reply_markup=main_menu()
        )
        return
    
    # Проверяем, есть ли уже такой товар
    items = get_items(user_id)
    for item in items:
        if item[1] == offer_id:
            await update.message.reply_text(
                "⚠️ <b>Товар уже добавлен!</b>",
                parse_mode="HTML",
                reply_markup=main_menu()
            )
            return
    
    status_msg = await update.message.reply_text("🔄 <b>Получаю информацию...</b>", parse_mode="HTML")
    
    price = get_price(url)
    
    if price:
        add_item(user_id, url, offer_id, f"Товар {offer_id}", price)
        await status_msg.delete()
        await update.message.reply_text(
            f"✅ <b>Товар добавлен!</b>\n\n"
            f"💰 <b>Цена:</b> {price:.2f} ₽\n"
            f"🆔 <b>ID:</b> <code>{offer_id}</code>",
            parse_mode="HTML",
            reply_markup=main_menu()
        )
    else:
        await status_msg.edit_text(
            "❌ <b>Не удалось получить цену</b>\n\n"
            "Возможно, Яндекс.Маркет временно недоступен.\n"
            "Попробуйте позже.",
            parse_mode="HTML",
            reply_markup=main_menu()
        )

async def list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    items = get_items(user_id)
    
    if not items:
        await query.edit_message_text(
            "📭 <b>У вас нет товаров</b>",
            parse_mode="HTML",
            reply_markup=main_menu()
        )
        return
    
    text = "📋 <b>Ваши товары</b>\n\n"
    keyboard = []
    
    for url, offer_id, price, name, item_id in items:
        price_text = f"{price:.2f} ₽" if price else "❓ не проверена"
        name_text = name[:30] if name else "Без названия"
        text += f"▫️ <b>{name_text}</b>\n   💰 {price_text}\n   🆔 <code>{offer_id}</code>\n\n"
        keyboard.append([InlineKeyboardButton(f"🗑️ Удалить {name_text}", callback_data=f"delete_{item_id}")])
    
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back")])
    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    item_id = int(query.data.split("_")[1])
    delete_item(user_id, item_id)
    await query.edit_message_text(
        "✅ <b>Товар удалён</b>",
        parse_mode="HTML",
        reply_markup=main_menu()
    )

async def back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📋 <b>Главное меню</b>",
        parse_mode="HTML",
        reply_markup=main_menu()
    )

async def check_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🔄 <b>Проверяю цены...</b>", parse_mode="HTML")
    
    # Проверяем цены для всех товаров пользователя
    user_id = query.from_user.id
    items = get_items(user_id)
    
    if not items:
        await query.edit_message_text(
            "📭 <b>У вас нет товаров</b>",
            parse_mode="HTML",
            reply_markup=main_menu()
        )
        return
    
    changes = 0
    for url, offer_id, last_price, name, item_id in items:
        current_price = get_price(url)
        if current_price and last_price and current_price != last_price:
            update_price(offer_id, current_price)
            changes += 1
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🚨 <b>Цена изменилась!</b>\n\n"
                     f"📦 <b>Товар:</b> {name or 'Без названия'}\n"
                     f"📉 <b>Было:</b> {last_price:.2f} ₽\n"
                     f"📈 <b>Стало:</b> {current_price:.2f} ₽\n"
                     f"📊 <b>Разница:</b> {current_price - last_price:+.2f} ₽",
                parse_mode="HTML"
            )
        elif current_price and not last_price:
            update_price(offer_id, current_price)
    
    await query.edit_message_text(
        f"✅ <b>Проверка завершена!</b>\n\n"
        f"📊 Проверено товаров: {len(items)}\n"
        f"🔄 Изменений: {changes}",
        parse_mode="HTML",
        reply_markup=main_menu()
    )

# ========== МОНИТОРИНГ ЦЕН (ФОН) ==========
async def monitor_loop():
    """Фоновый цикл проверки цен для всех пользователей"""
    await asyncio.sleep(30)  # Ждём, пока бот запустится
    while True:
        try:
            logger.info(f"🔄 Запуск фоновой проверки цен... {datetime.now().strftime('%H:%M:%S')}")
            
            items = get_all_items()
            if items:
                logger.info(f"📊 Всего товаров в базе: {len(items)}")
                
                for user_id, url, offer_id, last_price, name in items:
                    current_price = get_price(url)
                    
                    if current_price is None:
                        continue
                    
                    if last_price is None:
                        update_price(offer_id, current_price)
                        logger.info(f"Первая цена для {offer_id}: {current_price} ₽")
                    elif current_price != last_price:
                        logger.info(f"⚠️ Цена изменилась! {offer_id}: {last_price} -> {current_price}")
                        
                        # Отправляем уведомление пользователю
                        try:
                            await application.bot.send_message(
                                chat_id=user_id,
                                text=f"🚨 <b>Цена изменилась!</b>\n\n"
                                     f"📦 <b>Товар:</b> {name or 'Без названия'}\n"
                                     f"📉 <b>Было:</b> {last_price:.2f} ₽\n"
                                     f"📈 <b>Стало:</b> {current_price:.2f} ₽\n"
                                     f"📊 <b>Разница:</b> {current_price - last_price:+.2f} ₽",
                                parse_mode="HTML"
                            )
                        except Exception as e:
                            logger.error(f"Ошибка отправки уведомления: {e}")
                        
                        update_price(offer_id, current_price)
            
            logger.info(f"⏳ Следующая проверка через {CHECK_INTERVAL // 60} минут")
            await asyncio.sleep(CHECK_INTERVAL)
            
        except Exception as e:
            logger.error(f"Ошибка в мониторинге: {e}")
            await asyncio.sleep(60)

# ========== ЗАПУСК ==========
if __name__ == "__main__":
    init_db()
    
    app = ApplicationBuilder().token(TOKEN).build()
    
    # Регистрируем обработчики
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(add_callback, pattern="^add$"))
    app.add_handler(CallbackQueryHandler(cancel_callback, pattern="^cancel$"))
    app.add_handler(CallbackQueryHandler(list_callback, pattern="^list$"))
    app.add_handler(CallbackQueryHandler(delete_callback, pattern="^delete_"))
    app.add_handler(CallbackQueryHandler(back_callback, pattern="^back$"))
    app.add_handler(CallbackQueryHandler(check_callback, pattern="^check$"))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'market\.yandex\.ru'), handle_url))
    
    logger.info("🤖 Бот запущен!")
    
    # Запускаем фоновый мониторинг
    loop = asyncio.get_event_loop()
    loop.create_task(monitor_loop())
    
    app.run_polling()
