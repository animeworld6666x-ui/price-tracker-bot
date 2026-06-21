import asyncio
import re
import logging
from datetime import datetime
from telethon import TelegramClient, events

# ========== ВАШИ КЛЮЧИ ==========
API_ID = 31444839
API_HASH = 'c7518b6ff39204546d5ca2194e020326'

# ========== НАСТРОЙКИ ==========
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Хранилище для стоков
stock_data = {
    'items': [],
    'last_update': None,
    'raw_text': ''
}

# ========== ПАРСИНГ ==========
def parse_stock_text(text):
    items = []
    lines = text.split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        match = re.search(r'([А-Яа-я\s]+)\s*[-:]\s*(\d+)\s*[₽руб]?\s*[,.]?\s*(\d+)?\s*шт', line, re.IGNORECASE)
        if match:
            name = match.group(1).strip()
            price = int(match.group(2))
            amount = int(match.group(3)) if match.group(3) else 0
            items.append({"name": name, "price": price, "amount": amount})
            continue
        
        match = re.search(r'([А-Яа-я\s]+)\s*(\d+)\s*[₽руб]?\s*[,.]?\s*(\d+)?\s*шт', line, re.IGNORECASE)
        if match:
            name = match.group(1).strip()
            price = int(match.group(2))
            amount = int(match.group(3)) if match.group(3) else 0
            items.append({"name": name, "price": price, "amount": amount})
    
    return items

# ========== КЛИЕНТ С QR-ВХОДОМ ==========
client = TelegramClient('session', API_ID, API_HASH)

@client.on(events.NewMessage)
async def handle_new_message(event):
    global stock_data
    
    if not event.sender:
        return
    
    sender_username = event.sender.username
    if sender_username != 'growstoks_bot':
        return
    
    message_text = event.message.text
    if not message_text:
        return
    
    logger.info(f"Получено сообщение от growstoks_bot")
    
    items = parse_stock_text(message_text)
    
    if items:
        stock_data['items'] = items
        stock_data['last_update'] = datetime.now()
        stock_data['raw_text'] = message_text
        logger.info(f"✅ Обновлены стоки: {len(items)} товаров")
        for item in items[:5]:
            logger.info(f"  - {item['name']}: {item['price']}₽, {item['amount']} шт.")
    else:
        logger.warning("⚠️ Не удалось распарсить товары")

# ========== ЗАПУСК С QR-КОДОМ ==========
async def main():
    logger.info("🚀 Запуск клиента...")
    
    # Пытаемся восстановить сессию
    await client.start()
    
    # Если сессия не сохранена — запрашиваем QR-код
    if not await client.is_user_authorized():
        logger.info("📱 Требуется авторизация. Генерирую QR-код...")
        
        # Генерируем QR-код для входа
        qr = await client.qr_login()
        
        logger.info("✅ QR-код создан! Отсканируйте его в Telegram:")
        logger.info("📲 Откройте Telegram → Настройки → Устройства → Сканировать QR-код")
        
        # Показываем ссылку для сканирования (альтернатива QR-коду)
        logger.info(f"🔗 Или перейдите по ссылке: {qr.url}")
        
        try:
            # Ждём сканирования QR-кода
            await qr.wait()
            logger.info("✅ QR-код отсканирован! Вход выполнен.")
        except Exception as e:
            logger.error(f"❌ Ошибка при сканировании QR: {e}")
            logger.info("⏳ Попробуйте другой способ: введите код вручную.")
            # Если QR не сработал, пробуем обычный вход
            await client.start(phone=input("📱 Введите номер телефона: "))
    else:
        logger.info("✅ Сессия уже существует. Вход выполнен.")
    
    logger.info("✅ Клиент запущен. Ожидаю сообщения от @growstoks_bot...")
    
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
