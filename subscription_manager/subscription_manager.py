import asyncio
from queue import PriorityQueue
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from typing import List, Dict, Tuple
from datetime import datetime, timedelta
from utils.db_manager import DBManager
from utils.search import MessagesVectorizer
import json
import aiohttp
import logging

# Настройка логгера
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SubscriptionManager:
    def __init__(self, db_config: dict, vectorizer: MessagesVectorizer, bot_webhook_url: str):
        """
        Инициализирует SubscriptionManager.

        Args:
            db_config: Словарь с конфигурацией базы данных.
            vectorizer: Объект MessagesVectorizer для сравнения векторов.
            bot_webhook_url: URL вебхука Telegram-бота для отправки уведомлений.
        """
        self.db_manager = DBManager(db_config, dbname='postgres')
        self.vectorizer = vectorizer
        self.bot_webhook_url = bot_webhook_url
        self.notification_queue = PriorityQueue()
        self.scheduler = AsyncIOScheduler()
        self.scheduler.add_job(self.process_notifications, "interval", seconds=10)
        self.scheduler.start()
        self.rate_limits = {
            1: timedelta(seconds=10),
            2: timedelta(minutes=1),
            3: timedelta(minutes=5),
            4: timedelta(hours=1),
            5: timedelta(hours=24)
        }
        self.last_notification_times = {}

    async def process_new_messages(self, new_messages: List[Dict[str, int]]):
        """
        Обрабатывает новые сообщения и добавляет уведомления в очередь.

        Args:
            new_messages: Список новых сообщений в формате [{"message_id": 1234, "group_id": -5678}, ...]
        """
        subscriptions = self.db_manager.get_all_subscriptions()
        for subscription in subscriptions:
            relevant_messages = await self.find_relevant_messages(subscription, new_messages)
            if relevant_messages:
                self.add_notification_to_queue(subscription["user_id"], relevant_messages, subscription["priority"])

    async def find_relevant_messages(self, subscription: dict, new_messages: List[dict]) -> list:
        """
        Ищет релевантные сообщения для данной подписки.

        Args:
            subscription: Данные подписки из базы данных.
            new_messages: Список новых сообщений.

        Returns:
            Список релевантных сообщений или пустой список, если таковых нет.
        """
        relevant_messages = []
        for new_message in new_messages:
            message_data = self.db_manager.get_message(new_message["message_id"], new_message["group_id"])
            if message_data:
                logger.debug(f"message_data: {message_data}")
                message_vector = self.db_manager.get_vector(new_message["message_id"], new_message["group_id"])  #  Получаем вектор
                if message_vector:
                    similarity = self.vectorizer.calculate_similarity(subscription["query_vector"], message_vector)
                    if similarity >= subscription["threshold"]:
                        relevant_messages.append(message_data)
        return relevant_messages

    def add_notification_to_queue(self, user_id: int, messages: list, priority: int):
        """
        Добавляет уведомление в очередь с учетом лимитов частоты.

        Args:
            user_id: ID пользователя.
            messages: Список релевантных сообщений.
            priority: Приоритет уведомления.
        """
        current_time = datetime.now()
        last_notification_time = self.last_notification_times.get(user_id)

        if last_notification_time is None or (current_time - last_notification_time) >= self.rate_limits[priority]:
            self.notification_queue.put((priority, {"user_id": user_id, "messages": messages}))
            self.last_notification_times[user_id] = current_time
        else:
            logger.info(f"Уведомление для пользователя {user_id} пропущено из-за лимита частоты.")

    async def process_notifications(self):
        """Обрабатывает очередь уведомлений и отправляет их боту."""
        while not self.notification_queue.empty():
            priority, package = self.notification_queue.get()
            user_id = package["user_id"]
            messages = package["messages"]

            try:
                # Форматирование сообщения с результатами
                formatted_messages = self.vectorizer.interpret_vector_search_result(messages)

                # Отправка уведомления пользователю
                await self.send_message_to_user(user_id, f"Новые релевантные сообщения:\n{formatted_messages}")
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления пользователю {user_id}: {e}")

    async def send_message_to_user(self, user_id: int, message: str):
        """Отправляет сообщение пользователю через вебхук бота."""
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(self.bot_webhook_url, json={"user_id": user_id, "message": message})
            logger.info(f"Уведомление отправлено пользователю {user_id}")
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления пользователю {user_id}: {e}")

    async def add_subscription(self, user_id: int, chat_id: int, query: str, priority: int = 5, threshold: float = 0.8):
        """
        Добавляет новую подписку для пользователя.

        Args:
            user_id: ID пользователя.
            chat_id: ID чата.
            query: Поисковая фраза.
            priority: Приоритет (по умолчанию 5).
            threshold: Порог сходства (по умолчанию 0.8).
        """
        query_vector = self.vectorizer.vectorize_message(query)
        try:
            self.db_manager.add_subscription(user_id, chat_id, query, query_vector, priority, threshold)
            logger.info(f"Подписка добавлена для пользователя {user_id}: {query}")
        except Exception as e:
            logger.error(f"Ошибка при добавлении подписки: {e}")

# тестовая функция
async def test_send_notification(manager: SubscriptionManager, user_id: int, message: str):
    """Отправляет тестовое уведомление пользователю."""
    try:
        await manager.send_message_to_user(user_id, message)
        logger.info(f"Тестовое уведомление отправлено пользователю {user_id}")
    except Exception as e:
        logger.error(f"Ошибка при отправке тестового уведомления: {e}")

# Пример запуска менеджера рассылки 
async def main():
    with open("./settings.json", "r") as f:
        settings = json.loads(f.read())
    db_config = settings["db_config"]
    vectorizer = MessagesVectorizer(settings=settings, url='http://host.docker.internal:5123/vectorize', vector_size=1024, bot=None)
    bot_webhook_url = f"{settings['webhook_host']}:{settings['webhook_port']}/notification"  # Замените на ваш URL
    
    manager = SubscriptionManager(db_config, vectorizer, bot_webhook_url)
    
    # Запускаем планировщик задач
    # В нашем случае он уже был запущен в __init__
    # manager.scheduler.start()  
    
    # Обработка тестового сообщения
    await manager.process_new_messages([{'message_id': 1028, 'group_id': -1001496846806}]) 
    
    # Тестовое добавление подписки
    await manager.add_subscription(user_id=383856771, chat_id=-1001496846806, query="поиск телеграм", priority=3, threshold=0.7)
    
    # Тестовая отправка уведомления
    await test_send_notification(manager, user_id=123456789, message="Это тестовое уведомление!")
    
    while True:
        await asyncio.sleep(1)  # Просто ждем

if __name__ == "__main__":
    asyncio.run(main())
