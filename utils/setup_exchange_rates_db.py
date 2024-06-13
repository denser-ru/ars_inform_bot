import json
import psycopg2

# Загрузка данных конфигурации из файла JSON
def get_conf():
    # Открываем файл settings.json в режиме чтения
    with open( "./settings.json", "r" ) as f:
        # Десериализуем JSON-строку в словарь с помощью функции loads
        settings = json.loads(f.read())
    # Закрываем файл
    f.close()
    return settings
config = get_conf()["db_config"]
config["dbname"] = "exchange_rates_dev"

# Функция для создания таблиц
def setup_database():
    # Устанавливаем соединение с базой данных
    conn = psycopg2.connect(**config)
    cursor = conn.cursor()

    # Здесь добавляем SQL скрипт создания таблиц
    create_tables_script = """
-- Создание таблицы для источников данных
CREATE TABLE IF NOT EXISTS Sources (
    SourceID SERIAL PRIMARY KEY,
    SourceName VARCHAR(255) NOT NULL,
    SourceURL VARCHAR(255)
);

-- Создание таблицы для пар валют
CREATE TABLE IF NOT EXISTS CurrencyPairs (
    PairID SERIAL PRIMARY KEY,
    BaseCurrency CHAR(16) NOT NULL,
    QuoteCurrency CHAR(16) NOT NULL,
    UNIQUE(BaseCurrency, QuoteCurrency)
);

-- Создание таблицы для курсов обмена
CREATE TABLE IF NOT EXISTS ExchangeRates (
    RateID SERIAL PRIMARY KEY,
    PairID INT NOT NULL,
    RateType VARCHAR(50) NOT NULL,
    RateSource INT NOT NULL,
    RateValue DECIMAL(20, 6) NOT NULL,
    Timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (PairID) REFERENCES CurrencyPairs(PairID),
    FOREIGN KEY (RateSource) REFERENCES Sources(SourceID)
);

-- Таблица для данных пользователя Telegram
CREATE TABLE IF NOT EXISTS telegram_users (
    user_id BIGINT PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    language_code TEXT,
    -- Другие поля, которые вы хотите хранить о пользователях Telegram
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Таблица для настроек бота
CREATE TABLE IF NOT EXISTS bot_settings (
    setting_id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES telegram_users(user_id) ON DELETE CASCADE,
    settings JSONB
);

CREATE TABLE IF NOT EXISTS user_actions (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    command TEXT NOT NULL,
    parameters TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
    """
    
    # Выполняем SQL скрипт
    cursor.execute(create_tables_script)
    
    # Фиксируем изменения и закрываем соединение
    conn.commit()
    cursor.close()
    conn.close()

# Вызов функции для настройки базы данных
if __name__ == '__main__':
    setup_database()
