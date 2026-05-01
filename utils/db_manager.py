# db_manager.py
import psycopg2, json
from typing import List, Tuple, Any

# Импортируем модуль logging
import logging
root_logger = logging.getLogger("bot")
# Создаем дочерний логгер с именем scaner.tv
logger = logging.getLogger("bot.dbmanager")
logger.propagate = True
# Устанавливаем уровень логирования для дочернего логгера
logger.setLevel(logging.DEBUG)

class DBManager:
	def __init__(self, config, dbname="exchange_rates"):
		self.config = config
		self.config["dbname"] = dbname
		self.db_connection = psycopg2.connect(**config)
		self.db_cursor = self.db_connection.cursor()

	def __del__(self):
		self.db_connection.close()

	def add_user(self, user_id, username, first_name, last_name, language_code):
		self.db_cursor.execute(
			"INSERT INTO telegram_users (user_id, username, first_name, last_name, language_code) VALUES (%s, %s, %s, %s, %s);",
			(user_id, username, first_name, last_name, language_code)
		)
		self.db_connection.commit()

	def get_user(self, user_id):
		self.db_cursor.execute(
			"""
			SELECT tu.user_id, tu.username, tu.first_name, tu.last_name, tu.language_code, bs.settings
			FROM telegram_users tu
			LEFT JOIN bot_settings bs ON tu.user_id = bs.user_id
			WHERE tu.user_id = %s;
			""",
			(user_id,)
		)
		return self.db_cursor.fetchone()

	def add_user_settings(self, user_id, settings):
		self.db_cursor.execute(
			"INSERT INTO bot_settings (user_id, settings) VALUES (%s, %s);",
			(user_id, settings)
		)
		self.db_connection.commit()

	def update_user_settings(self, user_id, settings):
		self.db_cursor.execute(
			"UPDATE bot_settings SET settings = %s WHERE user_id = %s;", 
			(settings, user_id)
		)
		self.db_connection.commit()

	def log_user_action(self, user_id, command, parameters=None):
		"""Логирует действие пользователя в базе данных.

		Args:
			user_id (int): ID пользователя.
			command (str): Команда, выполненная пользователем.
			parameters (str, optional): Параметры команды. Defaults to None.
		"""
		self.db_cursor.execute(
			"INSERT INTO user_actions (user_id, command, parameters) VALUES (%s, %s, %s);",
			(user_id, command, parameters)
		)
		self.db_connection.commit()

	def get_all_subscriptions(self):
		"""Получает все подписки из базы данных."""
		self.db_cursor.execute("SELECT * FROM subscriptions;")
		return self.db_cursor.fetchall()
	
	def add_subscription(self, user_id: int, chat_id: int, query: str, query_vector: list, priority: int, threshold: float):
		"""
		Добавляет новую подписку в базу данных.

		Args:
			user_id: ID пользователя.
			chat_id: ID чата.
			query: Поисковая фраза.
			query_vector: Векторное представление запроса.
			priority: Приоритет.
			threshold: Порог сходства.
		"""
		self.db_cursor.execute(
			"""
			INSERT INTO subscriptions (user_id, chat_id, query, query_vector, priority, threshold)
			VALUES (%s, %s, %s, %s, %s, %s);
			""",
			(user_id, chat_id, query, query_vector, priority, threshold)
		)
		self.db_connection.commit()

	def get_message(self, message_id: int, group_id: int) -> dict:
		"""
		Получает данные сообщения из базы данных.

		Args:
			message_id: ID сообщения.
			group_id: ID группы.

		Returns:
			Словарь с данными сообщения или None, если сообщение не найдено.
		"""
		self.db_cursor.execute(
			"""
			SELECT * FROM messages 
			WHERE message_id = %s AND group_id = %s;
			""",
			(message_id, group_id)
		)
		row = self.db_cursor.fetchone()

		if row:
			# Преобразование кортежа в словарь
			columns = [desc[0] for desc in self.db_cursor.description]
			message_data = dict(zip(columns, row))
			return message_data
		else:
			return None

	def get_vector(self, message_id: int, group_id: int) -> list:
		"""
		Получает вектор сообщения из базы данных.

		Args:
			message_id: ID сообщения.
			group_id: ID группы.

		Returns:
			Список с вектором сообщения или None, если вектор не найден.
		"""
		self.db_cursor.execute(
			"""
			SELECT embedding FROM vectors 
			WHERE message_id = %s AND group_id = %s;
			""",
			(message_id, group_id)
		)
		row = self.db_cursor.fetchone()

		if row:
			# Преобразование строки в список
			return row[0] 
		else:
			return None

	def get_user_subscriptions(self, user_id: int) -> List[Tuple]:
		"""
		Возвращает список подписок пользователя из базы данных.
		"""
		with self.db_connection:
			self.db_cursor.execute(
				"SELECT id, query, threshold FROM subscriptions WHERE user_id = %s", (user_id,)
			)
			return self.db_cursor.fetchall()

	def update_subscription(self, subscription_id: int, **kwargs: Any) -> None:
		"""
		Обновляет параметры существующей подписки.

		Args:
			subscription_id: ID подписки.
			kwargs: Параметры для обновления (query, query_vector, priority, threshold).
		"""
		# Формируем SQL-запрос для обновления подписки
		set_values = ", ".join([f"{key} = %s" for key in kwargs])
		query = f"UPDATE subscriptions SET {set_values} WHERE id = %s"
		values = list(kwargs.values()) + [subscription_id]  #  Добавляем subscription_id в список

		try:
			with self.db_connection:
				self.db_cursor.execute(query, values)
				logger.info(f"Подписка {subscription_id} обновлена")
		except psycopg2.Error as e:
			logger.error(f"Ошибка обновления подписки: {e}")

	def delete_subscription(self, subscription_id: int) -> None:
		"""
		Удаляет подписку.

		Args:
			subscription_id: ID подписки.
		"""
		try:
			with self.db_connection:
				self.db_cursor.execute(
					"DELETE FROM subscriptions WHERE id = %s", (subscription_id,)
				)
				logger.info(f"Подписка {subscription_id} удалена.")
		except psycopg2.Error as e:
			logger.error(f"Ошибка удаления подписки: {e}")

	def get_rate_by_date(self, pair_id: int, target_date: str) -> dict:
		"""
		Возвращает исторический курс валюты (последнюю запись) на указанную дату. 
		Если совпадения нет, ищет ближайшие доступные записи до и после.
		"""
		try:
			with self.db_connection:
				# 1. Поиск точного совпадения за день (берем самую свежую запись этого дня)
				self.db_cursor.execute(
					"""
					SELECT Timestamp, RateValue, RateType 
					FROM ExchangeRates 
					WHERE PairID = %s AND DATE(Timestamp) = %s
					ORDER BY Timestamp DESC LIMIT 1;
					""",
					(pair_id, target_date)
				)
				exact_match = self.db_cursor.fetchone()
				
				if exact_match:
					return {"status": "exact", "data": exact_match}

				# 2. Поиск ближайшей даты ДО запрошенной
				self.db_cursor.execute(
					"""
					SELECT Timestamp, RateValue, RateType 
					FROM ExchangeRates 
					WHERE PairID = %s AND DATE(Timestamp) < %s 
					ORDER BY Timestamp DESC LIMIT 1;
					""",
					(pair_id, target_date)
				)
				rate_before = self.db_cursor.fetchone()

				# 3. Поиск ближайшей даты ПОСЛЕ запрошенной
				self.db_cursor.execute(
					"""
					SELECT Timestamp, RateValue, RateType 
					FROM ExchangeRates 
					WHERE PairID = %s AND DATE(Timestamp) > %s 
					ORDER BY Timestamp ASC LIMIT 1;
					""",
					(pair_id, target_date)
				)
				rate_after = self.db_cursor.fetchone()

				return {
					"status": "nearest",
					"before": rate_before,
					"after": rate_after
				}
		except psycopg2.Error as e:
			logger.error(f"Ошибка при получении курса по дате (PairID={pair_id}): {e}")
			return None