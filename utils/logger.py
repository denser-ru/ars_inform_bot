# Импортируем модуль logging
import logging

# Создаем объект логгера с именем scaner
logger = logging.getLogger("bot")

# Создаем объект обработчика для вывода лога на экран
console_handler = logging.StreamHandler()

# Устанавливаем формат лога с помощью объекта форматтера
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

# Присваиваем форматтер обработчику
console_handler.setFormatter(formatter)

# Добавляем обработчик к логгеру
logger.addHandler(console_handler)