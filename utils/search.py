import psycopg2, requests, json
from datetime import datetime


# Импортируем модуль logging
import logging
root_logger = logging.getLogger("bot")
# Создаем дочерний логгер с именем scaner.tv
logger = logging.getLogger("bot.search")
logger.propagate = True
# Устанавливаем уровень логирования для дочернего логгера
logger.setLevel(logging.DEBUG)

# Функция для проверки корректности даты
def validDates(dates_str):
    dates = [False, False]
    try:
        # Попытка преобразовать строку в дату
        start_date = datetime.strptime(dates_str[0], '%Y-%m-%d')
        # Проверка, что дата не старше 2019-01-01
        if start_date >= datetime(2019, 1, 1) and start_date <= datetime.now():
            dates[0] = start_date
    except ValueError:
        logger.debug("Дата start_date не корректна")
    try:
        # Попытка преобразовать строку в дату
        end_date = datetime.strptime(dates_str[1], '%Y-%m-%d')
        # Проверка, что дата не старше сегодняшней
        if end_date <= datetime.now():
            dates[1] = end_date
    except ValueError:
        logger.debug("Дата end_date не корректна")
    return dates

# Создайте класс для векторизации и хранения сообщений Телеграма
class MessagesVectorizer:
    # Определите конструктор класса
    def __init__(self, settings, url, vector_size, bot):
        # Подключитесь к базе данных Postgres с помощью библиотеки psycopg2 и объекта config
        self.settings = settings
        self.config = settings["db_config"]
        config = self.config
        self.url = url
        self.bot = bot
        try:
            # Попытка подключения к базе данных
            self.conn = psycopg2.connect(**config)
            self.cursor = self.conn.cursor()
            logger.debug("Успешное подключение к базе данных.")
            # # Создайте таблицу для хранения векторов, если ее нет
            # logger.debug("Попытка создать тбалицу векторов, если она отсутствует")
            # self.cursor.execute(f"""CREATE TABLE IF NOT EXISTS vectors (message_id bigint, group_id bigint, topic_id bigint,
            #                             embedding vector ({vector_size}));
            #                     CREATE UNIQUE INDEX IF NOT EXISTS idx_message ON vectors (message_id, group_id);
            #                     CREATE INDEX ON vectors USING hnsw (embedding vector_cosine_ops);""")
            # # Сохраняем изменения в базе данных
            # self.conn.commit()
            # logger.debug("Таблица векторов успешно создана или уже существует.")
        except psycopg2.Error as e:
            logger.error(f"Ошибка подключения к базе данных: {e}")
        except Exception as e:
            logger.error(f"Неизвестная ошибка: {e}")

    
    # Определите деструктор класса
    def __del__(self):
        # Закройте подключение к базе данных
        self.conn.close()

    # Определите метод для векторизации одного сообщения
    def vectorize_message(self, message):
        # Токенизируйте текст сообщения с префиксом "query: "
        message = 'query: ' + message

        # Отправка POST-запроса с сообщением в формате JSON
        response = requests.post(self.url, json=[message])
        
        # Проверка на успешный ответ от сервера
        if response.status_code == 200:
            # Получение и возврат вектора сообщения
            return response.json()[0]
        else:
            # Обработка ошибки, если сервер не вернул успешный ответ
            raise Exception('Ошибка сервера: HTTP статус', response.status_code)

    # Определите метод для поиска по векторному сходству по заданному запросу
    def search_query(self, query, start_date=False, end_date=False, sorting=False, limit=0):
        # Векторизуйте текст запроса
        logger.debug("векторизуем запрос")
        query_vector = self.vectorize_message(query)
        # Преобразование списка в строку, подходящую для SQL-запроса
        query_vector_str = ','.join(str(e) for e in query_vector)
        query_vector_str = '[' + query_vector_str + ']'

        # Выполнение SQL-запроса с использованием курсора
        # Проверка корректности даты
        valid_dates = [start_date, end_date]
        valid_dates = validDates( valid_dates )
        start_date = valid_dates[0]
        end_date = valid_dates[1]
        # Параметризованный запрос SQL с фильтрацией по дате
        query = """
            SELECT v.message_id, v.group_id, v.topic_id, v.embedding <-> %s AS cosine_distance, m.date
            FROM vectors v
            JOIN messages m ON v.message_id = m.message_id AND v.group_id = m.group_id
        """
        # Добавляем условия фильтрации по датам, если они не False
        conditions = []
        params = [query_vector_str]  # Параметры для вектора запроса
        if start_date:
            conditions.append("m.date >= %s")
            params.append(start_date)
        if end_date:
            conditions.append("m.date <= %s")
            params.append(end_date)
        # Если есть условия, добавляем их в запрос
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY v.embedding <-> %s LIMIT %s"
        # Если limit не определен, используем значение по умолчанию из настроек
        params.append(query_vector_str)
        params.append(limit or self.settings["number_msgs"])
        # Выполняем запрос
        self.cursor.execute(query, params)

        # Получите все записи из базы данных
        logger.debug("сохраняем строки векторов в меременную")
        results = self.cursor.fetchall()

        # Сортировка
        if sorting:
            if sorting == 'date_asc':
                # Сортировка прямая списка словарей по ключу 'date'
                results = sorted(results, key=lambda x: x[4])
            elif sorting == 'date_desc':
                # Сортировка обратная списка словарей по ключу 'date'
                results = sorted(results, key=lambda x: x[4], reverse=True)

        # Верните результаты поиска
        return results
    
    # Определяем функцию для интерпретации результата векторного поиска
    def interpret_vector_search_result(self, result):
        # Создаем пустой список для хранения строк с информацией о сообщениях
        number_words = self.settings["number_words"]
        messages_info_txt = ""
        # Проходим по списку кортежей с помощью цикла for
        for entry in result:
            # Распаковываем только первые четыре значения
            message_id, group_id, topic_id, score = entry[:4]
            self.cursor.execute("""SELECT g.title, g.group_entity_id, m.text, m.date FROM messages AS m, groups AS g
                                    WHERE g.id = m.group_id AND m.message_id = %s AND m.group_id = %s AND m.topic_id = %s""",
                                    (message_id, group_id, topic_id))
            # Извлекаем текст сообщения из результата запроса с помощью метода fetchone курсора
            result = self.cursor.fetchone()
            title = result[0]
            group_entity_id = result[1]
            text = result[2]
            date = result[3]
            # Сокращаем текст сообщения до 30 слов, добавляя многоточие в конце, если текст длиннее
            words = text.split()
            if len(words) > number_words:
                text = ' '.join(words[:number_words]) + '...'
            # Сформируем ссылку на сообщение в Телеграме по шаблону https://t.me/c/group_id/message_id
            link = f"https://t.me/c/{abs(group_entity_id)}/{message_id}"
            # link = f"tg://openmessage?chat_id={group_id}&message_id={message_id}"
            # Преобразуем показатель близости в проценты, умножая его на 100 и округляя до двух знаков после запятой
            score = round( score, 2 )
            # Выведем информацию о сообщении в виде строки, содержащей название группы, сокращенный текст, ссылку на сообщение в Телеграме и показатель близости
            text_raw = text
            # text = text.replace('\"', '\\"')
            # text = text.replace('\n', '\\n')
            # message_info = f"""{{
            #         "group_id": "{group_id}",
            #         "group_title": "{title}",
            #         "text": "{text}",
            #         "date": "{date.strftime("%Y-%m-%d %H:%M")}",
            #         "link": "{link}",
            #         "score": "{score}"
            # }}"""
            message_info_txt = f"""<blockquote><pre>group: {title}
date: {date.strftime("%Y-%m-%d %H:%M")}
score: {score}
</pre>
{text_raw}</blockquote>
<a>{link}</a>\n\n"""
            # # logger.debug(f"message_info:\n{message_info}")
            # message_info = json.loads( message_info )
            # # Добавим строку с информацией о сообщении в список messages_info
            # messages_info.append(message_info)
            messages_info_txt += message_info_txt
        # Вернем список messages_info как результат функции
        return messages_info_txt

    # Определяем функцию для интерпретации результата векторного поиска
    def interpret_vector_search_result_text_only(self, result):
        # Создаем пустой список для хранения строк с информацией о сообщениях
        number_words = self.settings["number_words"]
        messages_info = []
        # Проходим по списку кортежей с помощью цикла for
        for message_id, group_id, topic_id, score in result:
            # Получаем текст сообщения из таблицы messages по message_id, group_id и topic_id с помощью метода execute курсора
            self.cursor.execute("""SELECT g.title, m.text FROM messages AS m, groups AS g
                                    WHERE g.id = m.group_id AND m.message_id = %s AND m.group_id = %s AND m.topic_id = %s""",
                                    (message_id, group_id, topic_id))
            # Извлекаем текст сообщения из результата запроса с помощью метода fetchone курсора
            result = self.cursor.fetchone()
            title = result[0]
            text = result[1]
            # Сокращаем текст сообщения до 30 слов, добавляя многоточие в конце, если текст длиннее
            words = text.split()
            if len(words) > number_words:
                text = ' '.join(words[:number_words]) + '...'
            # Добавим строку с информацией о сообщении в список messages_info
            messages_info.append(text)
        # Вернем список messages_info как результат функции
        return messages_info

    def calculate_similarity(self, vector1, vector2) -> float:
        """
        Вычисляет косинусное сходство, используя оператор <-> pgvector.
        Обрабатывает как списки, так и строки в формате pgvector.
        """

        # Преобразование в строковый формат pgvector при необходимости
        if isinstance(vector1, list):
            vector1 = '[' + ','.join(str(e) for e in vector1) + ']'
        if isinstance(vector2, list):
            vector2 = '[' + ','.join(str(e) for e in vector2) + ']'

        # Выполнение SQL-запроса с использованием курсора, параметров и явным приведением типов
        self.cursor.execute("SELECT %s::vector <-> %s::vector AS cosine_distance", (vector1, vector2))

        # Получение результата
        result = self.cursor.fetchone()
        cosine_distance = result[0]

        # Вернуть косинусное расстояние
        return cosine_distance