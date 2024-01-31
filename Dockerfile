# Используем базовый образ Python 3.10
FROM python:3.10

# Копируем файл requirements.txt в контейнер
COPY requirements.txt /app/requirements.txt

# Устанавливаем зависимости
RUN pip install --upgrade pip
RUN pip install -r /app/requirements.txt

# Копируем все остальные файлы вашего приложения в контейнер
COPY . /app

# Указываем рабочую директорию
WORKDIR /app

# Запускаем скрипт bot.py при запуске контейнера
CMD ["python3", "bot.py"]
