# db_manager.py
import psycopg2

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