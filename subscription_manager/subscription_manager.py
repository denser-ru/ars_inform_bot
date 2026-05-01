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

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# Настройка логгера
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

settings = {}

class SubscriptionManager:
    def __init__(self, db_config: dict, vectorizer: MessagesVectorizer, bot_webhook_url: str, bot_webhook_token: str):
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
        self.bot_webhook_token = bot_webhook_token
        self.notification_queue = PriorityQueue()
        self.scheduler = AsyncIOScheduler()
        self.scheduler.add_job(self.process_notifications, "interval", seconds=60)
        self.rate_limits = {
            1: timedelta(seconds=60),
            2: timedelta(minutes=5),
            3: timedelta(minutes=15),
            4: timedelta(hours=1),
            5: timedelta(hours=3)
        }
        self.last_notification_times = {}

    async def process_new_messages(self, new_messages: List[Dict[str, int]]):
        subscriptions = self.db_manager.get_all_subscriptions()
        
        # Преобразование списка кортежей в список словарей
        subscriptions = [dict(zip([column[0] for column in self.db_manager.db_cursor.description], row)) for row in subscriptions]
        
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
            Список релевантных сообщений (список словарей) или пустой список, если таковых нет.
        """
        logger.debug("Обрабатываем новые сообщения")
        relevant_messages = []
        for new_message in new_messages:
            logger.debug(f"Новое сообщение: { new_message }")
            message_data = self.db_manager.get_message(new_message["message_id"], new_message["group_id"])
            # logger.info(f"message_data: { message_data }")
            if message_data:
                message_vector = self.db_manager.get_vector(new_message["message_id"], new_message["group_id"]) 
                if message_vector:
                    similarity = self.vectorizer.calculate_similarity(subscription["query_vector"], message_vector)
                    logger.debug(f"Сходство: { similarity }")
                    if similarity <= subscription["threshold"]:
                        # Добавляем все необходимые данные в словарь message_data
                        message_data['score'] = similarity # добавляем score в словарь message_data

                        # Добавляем словарь message_data в список relevant_messages
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

        # Инициализация значения для ключа, если его нет в словаре
        if user_id not in self.last_notification_times:
            self.last_notification_times[user_id] = current_time - self.rate_limits[priority]  # Разрешаем первое уведомление

        last_notification_time = self.last_notification_times[user_id] 

        if (current_time - last_notification_time) >= self.rate_limits[priority]:
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
                # Форматирование сообщений с результатами
                formatted_messages = ""
                for message in messages:
                    message_f = [(message['message_id'], message['group_id'], message['topic_id'], message['score'])]
                    # Передаем message как словарь, а не как список
                    formatted_message = self.vectorizer.interpret_vector_search_result( message_f )
                    formatted_messages += formatted_message + "\n"

                # Отправка уведомления пользователю
                await self.send_message_to_user(user_id, f"Новые релевантные сообщения подписки:\n{formatted_messages}")

            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления пользователю {user_id}: {e}")

    async def send_message_to_user(self, user_id: int, message: str):
        """Отправляет сообщение пользователю через новый endpoint бота."""
        try:
            url = self.bot_webhook_url  #  URL вашего endpoint
            headers = {"Authorization": f"Bearer { self.bot_webhook_token }"}
            data = {"chat_id": user_id, "message_text": message}
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=data) as response:
                    response_text = await response.text()
                    if response.status != 200:
                        logger.error(f"Ошибка при отправке уведомления пользователю {user_id}: {response_text}")
                        logger.error(f"url: {url}")
                    else:
                        logger.info(f"Уведомление отправлено пользователю {user_id}")
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления пользователю {user_id}: {e}")

    async def add_subscription(self, user_id: int, chat_id: int, query: str, priority: int = 3, threshold: float = 0.6):
        """
        Добавляет новую подписку для пользователя.

        Args:
            user_id: ID пользователя.
            chat_id: ID чата.
            query: Поисковая фраза.
            priority: Приоритет (по умолчанию 3).
            threshold: Порог сходства (по умолчанию 0.6).
        """
        query_vector = self.vectorizer.vectorize_message(query)
        try:
            self.db_manager.add_subscription(user_id, chat_id, query, query_vector, priority, threshold)
            logger.info(f"Подписка добавлена для пользователя {user_id}: {query}")
        except Exception as e:
            logger.error(f"Ошибка при добавлении подписки: {e}")

    async def get_user_subscriptions(self, user_id: int) -> List[Dict]:
        """
        Возвращает список подписок пользователя.
        """
        subscriptions = self.db_manager.get_user_subscriptions(user_id)
        return subscriptions

    async def update_subscription(self, subscription_id: int, **kwargs):
        """
        Обновляет параметры существующей подписки.
        """
        if "query" in kwargs:
            kwargs["query_vector"] = self.vectorizer.vectorize_message(kwargs["query"])
        self.db_manager.update_subscription(subscription_id, **kwargs)

    async def delete_subscription(self, subscription_id: int):
        """
        Удаляет подписку.
        """
        self.db_manager.delete_subscription(subscription_id)


# тестовая функция
async def test_send_notification(manager: SubscriptionManager, user_id: int, message: str):
    """Отправляет тестовое уведомление пользователю."""
    try:
        await manager.send_message_to_user(user_id, message)
        logger.info(f"Тестовое уведомление отправлено пользователю {user_id}")
    except Exception as e:
        logger.error(f"Ошибка при отправке тестового уведомления: {e}")


app = FastAPI()  # Создаем экземпляр FastAPI

@app.post("/new_messages_webhook")
async def new_messages_webhook(request: Request):
    """
    Веб-хук для получения новых сообщений от сканера.
    Ожидаемый формат данных: 
        [
            {"message_id": 12345, "group_id": -1001234567890}, 
            {"message_id": 12346, "group_id": -1001234567890},
            ...
        ]
    """
    try:
        data = await request.json()  # Получаем данные из тела запроса
        logger.info(f"Получены новые сообщения: {data}")
        
        # Запускаем асинхронную обработку сообщений
        asyncio.create_task(manager.process_new_messages(data)) 
        
        return JSONResponse({"status": "ok"})
    except Exception as e:
        logger.error(f"Ошибка обработки веб-хука: {e}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


# Пример запуска менеджера рассылки 
async def main():
    with open("./settings.json", "r") as f:
        settings = json.loads(f.read())
    db_config = settings["db_config"]
    vectorizer = MessagesVectorizer(settings=settings, url='http://host.docker.internal:5123/vectorize', vector_size=1024, bot=None)
    bot_webhook_url = f"{settings['webhook_host']}:{settings['webhook_port']}/send_message"  # Замените на ваш URL
    bot_webhook_token = settings['webhook_token']
    
    # Создание экземпляра SubscriptionManager
    global manager  # Используем глобальный manager
    manager = SubscriptionManager(db_config, vectorizer, bot_webhook_url, bot_webhook_token)
    
    # Запускаем планировщик задач
    manager.scheduler.start()  
    
    # # Обработка тестового сообщения
    # await manager.process_new_messages([{'message_id': 1028, 'group_id': -1001496846806}]) 
    
    # # Тестовое добавление подписки
    # await manager.add_subscription(user_id=383856771, chat_id=-1001496846806, query="внж рантье", priority=1, threshold=0.6)
    
    # Тестовая отправка уведомления
    await test_send_notification(manager, user_id=383856771, message="Это тестовое уведомление! Менеджер подписок успешно запущен 😎")

    # Создание конфигурации сервера uvicorn
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info")
    server = uvicorn.Server(config)

    # Запуск сервера в отдельной задаче asyncio
    await server.serve()
    
    while True:
        await asyncio.sleep(1)  # Просто ждем

if __name__ == "__main__":
    asyncio.run(main())
