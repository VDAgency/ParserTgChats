import requests
import os
from dotenv import load_dotenv
from database import get_message_by_id

load_dotenv()
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# Положительные словосочетания (то, что мы ищем)
POSITIVE_PHRASES = [
    "ищу аренду", "хочу арендовать", "ищу покупку", "хочу купить",
    "ищу квартиру", "хочу квартиру", "ищу виллу", "хочу виллу",
    "ищу коттедж", "хочу коттедж", "ищу кондоминиум", "хочу кондоминиум",
    "looking for rent", "want to rent", "looking to buy", "want to buy",
    "looking for apartment", "want apartment", "looking for villa", "want villa",
    "looking for cottage", "want cottage", "looking for condominium", "want condominium"
]

# Отрицательные словосочетания (то, что нужно исключить)
NEGATIVE_PHRASES = [
    "доступно в аренду", "доступна аренда", "продается", "available for rent",
    "for sale", "available to buy"
]

def filter_message(message_data):
    # Проверяем наличие данных и текста
    if not message_data or "text" not in message_data:
        return False
    text = message_data["text"].lower()
    
    # Проверяем наличие положительных фраз
    has_positive = any(phrase in text for phrase in POSITIVE_PHRASES)
    
    # Проверяем отсутствие отрицательных фраз
    has_negative = any(phrase in text for phrase in NEGATIVE_PHRASES)
    
    # Возвращаем True только если есть положительная фраза и нет отрицательной
    return has_positive and not has_negative

async def process_and_send_webhook(message_id):
    # Читаем сообщение из базы
    message_data = await get_message_by_id(message_id)
    if not message_data:
        print(f"No message found with ID {message_id}")
        return

    # Фильтруем сообщение
    if filter_message(message_data):
        print(f"Message {message_id} matches criteria, sending to webhook")
        try:
            response = requests.post(WEBHOOK_URL, json=message_data)
            if response.status_code == 200:
                print(f"Successfully sent to webhook: {message_id}")
            else:
                print(f"Failed to send to webhook, status code: {response.status_code}")
        except Exception as e:
            print(f"Error sending to webhook: {str(e)}")
    else:
        print(f"Message {message_id} skipped, does not match criteria")