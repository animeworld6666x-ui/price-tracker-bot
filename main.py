import asyncio
import sqlite3
import re
import io
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw

# ========== НАСТРОЙКИ ==========
TOKEN = "8924965576:AAFDrB6Tdb0s_NExdT-ZBtUht5WdGI6slWM"
EMAIL_SENDER = "ваша_почта@gmail.com"
EMAIL_PASSWORD = "пароль_приложения"
EMAIL_SMTP_SERVER = "smtp.gmail.com"
EMAIL_SMTP_PORT = 587
CHECK_INTERVAL = 1800

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


def update_user_email(user_id, email):
    conn = sqlite3.connect("prices.db")
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO users (user_id, email, email_enabled) VALUES (?, ?, 1)", (user_id, email))
    conn.commit()
    conn.close()


def get_user_settings(user_id):
    conn = sqlite3.connect("prices.db")
    cur = conn.cursor()
    cur.execute("SELECT email, email_enabled, telegram_enabled FROM users WHERE user_id=?", (user_id,))
    result = cur.fetchone()
    conn.close()
    if result:
        return {"email": result[0], "email_enabled": bool(result[1]), "telegram_enabled": bool(result[2])}
    return {"email": None, "email_enabled": False, "telegram_enabled": True}


def toggle_email(user_id, enabled):
    conn = sqlite3.connect("prices.db")
    cur = conn.cursor()
    cur.execute("UPDATE users SET email_enabled=? WHERE user_id=?", (1 if enabled else 0, user_id))
    conn.commit()
    conn.close()


def toggle_telegram(user_id, enabled):
    conn = sqlite3.connect("prices.db")
    cur = conn.cursor()
    cur.execute("UPDATE users SET telegram_enabled=? WHERE user_id=?", (1 if enabled else 0, user_id))
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


# ========== ОТПРАВКА ПОЧТЫ ==========
def send_email(to_email, subject, body, attachment=None):
    try:
        msg = MIMEMultipart()
        msg["From"] = EMAIL_SENDER
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "html"))
        if attachment:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(attachment)
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename="price.png"')
            msg.attach(part)
        with smtplib.SMTP(EMAIL_SMTP_SERVER, EMAIL_SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.send_message(msg)
        return True
    except Exception as e:
        logger.error(f"Ошибка отправки письма: {e}")
        return False


# ========== ПАРСИНГ ==========
def get_price_and_screenshot(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        r = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        price = None
        name = ""
        price_tag = soup.find("span", {"data-auto": "price"})
        if not price_tag:
            price_tag = soup.find("span", class_="price")
        if price_tag:
            raw = price_tag.text.replace(" ", "").replace("₽", "").replace(",", ".").strip()
            numbers = re.findall(r'[\d.]+', raw)
            if numbers:
                price = float(numbers[0])
        name_tag = soup.find("h1")
        if name_tag:
            name = name_tag.text[:100]
        img = Image.new('RGB', (800, 200), color='white')
        draw = ImageDraw.Draw(img)
        draw.rectangle([10, 10, 790, 190], outline="red", width=3)
        draw.text((50, 50), f"Цена: {price} ₽" if price else "Цена не найдена", fill="black")
        draw.text((50, 100), f"Товар: {name[:50]}", fill="black")
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        screenshot_bytes = buf.getvalue()
        return price, name, screenshot_bytes
    except Exception as e:
        logger.error(f"Ошибка парсинга: {e}")
        return None, "", None


def get_price_simple(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        r = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        price_tag = soup.find("span", {"data-auto": "price"})
        if not price_tag:
            price_tag = soup.find("span", class_="price")
        if not price_tag:
            return None
        raw = price_tag.text.replace(" ", "").replace("₽", "").replace(",", ".").strip()
        numbers = re.findall(r'[\d.]+', raw)
        if numbers:
            return float(numbers[0])
        return None
    except Exception as e:
        logger.error(f"Ошибка получения цены: {e}")
        return None


# ========== КЛАВИАТУРЫ ==========
def main_menu():
    keyboard = [
        [InlineKeyboardButton("➕ Добавить товар", callback_data="add")],
        [InlineKeyboardButton("📋 Мои товары", callback_data="list")],
        [InlineKeyboardButton("⚙️ Настройки", callback_data="settings")],
        [InlineKeyboardButton("🔄 Проверить сейчас", callback_data="check")],
        [InlineKeyboardButton("❓ Помощь", callback_data="help")]
    ]
    return InlineKeyboardMarkup(keyboard)


def settings_menu(email, email_enabled, telegram_enabled):
    email_status = "✅ Включена" if email_enabled else "❌ Выключена"
    tg_status = "✅ Включены" if telegram_enabled else "❌ Выключены"
    keyboard = [
        [InlineKeyboardButton(f"📧 Почта: {email_status}", callback_data="toggle_email")],
        [InlineKeyboardButton(f"📱 Telegram: {tg_status}", callback_data="toggle_telegram")],
        [InlineKeyboardButton("✉️ Изменить email", callback_data="change_email")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)


# ========== БОТ ==========
application = None
bot_instance = None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    add_user(user_id)
    await update.message.reply_text(
        "🛍️ <b>Добро пожаловать в Price Tracker!</b>\n\n"
        "Я слежу за ценами на Яндекс.Маркете и присылаю уведомления\n"
        "при <b>повышении</b> цены.\n\n"
        "👇 Выберите действие:",
        parse_mode="HTML",
        reply_markup=main_menu()
    )


async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    settings = get_user_settings(user_id)
    text = (
        "⚙️ <b>Настройки уведомлений</b>\n\n"
        f"📧 <b>Email:</b> {settings['email'] or 'Не указан'}\n"
        f"📧 <b>Отправка на почту:</b> {'✅ Включена' if settings['email_enabled'] else '❌ Выключена'}\n"
        f"📱 <b>Отправка в Telegram:</b> {'✅ Включена' if settings['telegram_enabled'] else '❌ Выключена'}\n\n"
        "Нажмите на кнопку, чтобы изменить настройку"
    )
    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=settings_menu(settings['email'], settings['email_enabled'], settings['telegram_enabled'])
    )


async def toggle_email_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    settings = get_user_settings(user_id)
    if not settings['email']:
        await query.answer("❌ Сначала укажите email в настройках!", show_alert=True)
        return
    new_state = not settings['email_enabled']
    toggle_email(user_id, new_state)
    await query.answer(f"📧 Почта {'включена' if new_state else 'выключена'}")
    await settings_callback(update, context)


async def toggle_telegram_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    settings = get_user_settings(user_id)
    new_state = not settings['telegram_enabled']
    toggle_telegram(user_id, new_state)
    await query.answer(f"📱 Telegram {'включен' if new_state else 'выключен'}")
    await settings_callback(update, context)


async def change_email_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "✉️ <b>Введите ваш email</b>\n\n"
        "Пример: <code>user@example.com</code>\n\n"
        "Напишите email в чат",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="settings")]])
    )


async def handle_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    email = update.message.text.strip()
    if re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', email):
        update_user_email(user_id, email)
        await update.message.reply_text(
            f"✅ <b>Email сохранён!</b>\n\n📧 {email}\n\nНе забудьте включить отправку на почту в настройках.",
            parse_mode="HTML",
            reply_markup=main_menu()
        )
    else:
        await update.message.reply_text(
            "❌ <b>Неверный формат email</b>\n\nПопробуйте ещё раз или нажмите «Отмена»",
            parse_mode="HTML"
        )


async def add_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🔗 <b>Отправьте ссылку на товар</b>\n\nПример:\n<code>https://market.yandex.ru/product/1234567890</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="cancel")]])
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
        await update.message.reply_text("❌ <b>Не удалось распознать товар</b>", parse_mode="HTML",
                                        reply_markup=main_menu())
        return
    items = get_items(user_id)
    for item in items:
        if item[1] == offer_id:
            await update.message.reply_text("⚠️ <b>Товар уже добавлен!</b>", parse_mode="HTML",
                                            reply_markup=main_menu())
            return
    status_msg = await update.message.reply_text("🔄 <b>Получаю информацию...</b>", parse_mode="HTML")
    price, name, screenshot = get_price_and_screenshot(url)
    if price and screenshot:
        add_item(user_id, url, offer_id, name)
        update_price(offer_id, price)
        photo = io.BytesIO(screenshot)
        await update.message.reply_photo(
            photo=photo,
            caption=f"✅ <b>Товар добавлен!</b>\n\n📦 <b>Название:</b> {name[:50]}\n💰 <b>Цена:</b> {price:.2f} ₽",
            parse_mode="HTML"
        )
        await status_msg.delete()
        await update.message.reply_text("📋 <b>Главное меню</b>", parse_mode="HTML", reply_markup=main_menu())
    else:
        await status_msg.edit_text("❌ <b>Не удалось получить цену</b>", parse_mode="HTML", reply_markup=main_menu())


async def list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    items = get_items(user_id)
    if not items:
        await query.edit_message_text("📭 <b>У вас нет товаров</b>", parse_mode="HTML", reply_markup=main_menu())
        return
    text = "📋 <b>Ваши товары</b>\n\n"
    for url, offer_id, price, name, item_id in items:
        price_text = f"{price:.2f} ₽" if price else "❓ не проверена"
        name_text = name[:30] if name else "Без названия"
        text += f"▫️ <b>{name_text}</b>\n   💰 {price_text}\n   🆔 <code>{offer_id}</code>\n\n"
    keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu")]]
    for item in items:
        keyboard.append([InlineKeyboardButton(f"🗑️ Удалить {item[3][:20]}", callback_data=f"delete_{item[4]}")])
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))


async def delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    item_id = int(query.data.split("_")[1])
    delete_item(user_id, item_id)
    await query.edit_message_text("✅ <b>Товар удалён</b>", parse_mode="HTML", reply_markup=main_menu())


async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("📋 <b>Главное меню</b>", parse_mode="HTML", reply_markup=main_menu())


async def check_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🔄 <b>Проверяю цены...</b>", parse_mode="HTML")
    await check_prices(context.bot)
    await query.edit_message_text("✅ <b>Проверка завершена!</b>", parse_mode="HTML", reply_markup=main_menu())


async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "❓ <b>Помощь</b>\n\n"
        "📌 <b>Как добавить товар:</b>\nНажмите «➕ Добавить товар» и отправьте ссылку\n\n"
        "📌 <b>Настройки:</b>\n• Включить/выключить уведомления в Telegram\n"
        "• Включить/выключить отправку на почту\n• Указать email для уведомлений\n\n"
        "📌 <b>Уведомления:</b>\nПри повышении цены придёт фото с ценой\nв Telegram и/или на почту",
        parse_mode="HTML",
        reply_markup=main_menu()
    )


async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 Проверяю цены...")
    await check_prices(context.bot)
    await update.message.reply_text("✅ Проверка завершена!", reply_markup=main_menu())


# ========== МОНИТОРИНГ ==========
async def check_prices(bot):
    items = get_all_items()
    logger.info(f"Проверяю {len(items)} товаров")
    for user_id, url, offer_id, last_price, name in items:
        current_price = get_price_simple(url)
        if current_price is None:
            continue
        if last_price is None:
            update_price(offer_id, current_price)
            logger.info(f"Первая цена для {offer_id}: {current_price} ₽")
        elif current_price > last_price:
            logger.info(f"⚠️ Цена повысилась! {offer_id}: {last_price} -> {current_price}")
            settings = get_user_settings(user_id)
            _, _, screenshot = get_price_and_screenshot(url)
            text = (
                f"🚨 <b>ЦЕНА ПОВЫСИЛАСЬ!</b>\n\n"
                f"📦 <b>Товар:</b> {name[:50]}\n"
                f"📉 <b>Было:</b> {last_price:.2f} ₽\n"
                f"📈 <b>Стало:</b> {current_price:.2f} ₽\n"
                f"📊 <b>Разница:</b> +{current_price - last_price:.2f} ₽\n"
                f"🔗 <a href='{url}'>Перейти к товару</a>"
            )
            if settings['telegram_enabled']:
                try:
                    if screenshot:
                        await bot.send_photo(chat_id=user_id, photo=io.BytesIO(screenshot), caption=text,
                                             parse_mode="HTML")
                    else:
                        await bot.send_message(chat_id=user_id, text=text, parse_mode="HTML")
                except Exception as e:
                    logger.error(f"Ошибка отправки в Telegram: {e}")
            if settings['email_enabled'] and settings['email']:
                try:
                    email_text = text.replace("<b>", "").replace("</b>", "").replace("\n", "<br>")
                    send_email(settings['email'], f"⚠️ Цена повысилась! {name[:30]}", email_text, screenshot)
                except Exception as e:
                    logger.error(f"Ошибка отправки письма: {e}")
            update_price(offer_id, current_price)


async def monitor_loop(bot):
    await asyncio.sleep(10)
    while True:
        logger.info(f"🔄 Запуск проверки цен... {datetime.now().strftime('%H:%M:%S')}")
        await check_prices(bot)
        logger.info(f"⏳ Следующая проверка через {CHECK_INTERVAL // 60} минут")
        await asyncio.sleep(CHECK_INTERVAL)


# ========== ЗАПУСК ==========
def main():
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()

    # Регистрируем обработчики
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("check", check_command))
    app.add_handler(CallbackQueryHandler(settings_callback, pattern="^settings$"))
    app.add_handler(CallbackQueryHandler(toggle_email_callback, pattern="^toggle_email$"))
    app.add_handler(CallbackQueryHandler(toggle_telegram_callback, pattern="^toggle_telegram$"))
    app.add_handler(CallbackQueryHandler(change_email_callback, pattern="^change_email$"))
    app.add_handler(CallbackQueryHandler(add_callback, pattern="^add$"))
    app.add_handler(CallbackQueryHandler(cancel_callback, pattern="^cancel$"))
    app.add_handler(CallbackQueryHandler(list_callback, pattern="^list$"))
    app.add_handler(CallbackQueryHandler(delete_callback, pattern="^delete_"))
    app.add_handler(CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"))
    app.add_handler(CallbackQueryHandler(check_callback, pattern="^check$"))
    app.add_handler(CallbackQueryHandler(help_callback, pattern="^help$"))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'market\.yandex\.ru'), handle_url))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^[\w\.-]+@[\w\.-]+\.\w+$'), handle_email))

    logger.info("🤖 Бот запущен!")

    # Запускаем мониторинг в фоне
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(monitor_loop(app.bot))

    # Запускаем polling
    app.run_polling()


if __name__ == "__main__":
    main()