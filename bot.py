# Импортируем необходимые библиотеки
import asyncio, logging, json, time, base64
from datetime import datetime, timedelta
from random import randint
import aiogram
from aiogram import Bot, Dispatcher, types
from aiogram.filters.command import Command
from aiogram.filters import CommandObject
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram import F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

import uvicorn
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel

from utils.search import MessagesVectorizer
from utils.binance_data_collector import RatesDataCollector
from utils.db_manager import DBManager
from utils.llm_helper import LLMHelper


# Импортируем настроки журналирования из файла logger.py
from utils.logger import logger
# Устанавливаем минимальный уровень важности для логгера равным DEBUG
logger.setLevel(logging.DEBUG)

def get_conf():
    # Открываем файл settings.json в режиме чтения
    logger.debug("Открываем файл settings.json в режиме чтения...")
    with open( "./settings.json", "r" ) as f:
        # Десериализуем JSON-строку в словарь с помощью функции loads
        logger.debug("Десериализуем JSON-строку в словарь с помощью функции loads...")
        settings = json.loads(f.read())
    # Закрываем файл
    f.close()
    return settings

settings = get_conf()

# Получаем токен бота из @BotFather
if settings["DEV"]:
    TOKEN = settings["bot_dev_key"]
    GROQ_API_KEY = settings["GROQ_API_KEY_DEV"]
else:
    TOKEN = settings["bot_key"]
    GROQ_API_KEY = settings["GROQ_API_KEY"]

# Словарь для кэширования результатов поиска
cache = {}
# Время жизни кэша (в секундах)
CACHE_TTL = settings["CACHE_TTL"]
# Начальные настройки бота
settings_def = {
    "start_date": "*",
	"end_date": "*",
	"sort_by": 'relevance'
}


async def bot_test(bot):
    try:
        user = await bot.get_me()
        logger.debug(f"Бот успешно подключен. Имя бота: {user.first_name}, username: @{user.username}")
    except Exception as e:
        logger.debug(f"Ошибка подключения бота: {e}")

# API для отправки сообщений через бота
app = FastAPI()
# Объект бота
bot = Bot(token=TOKEN)
# Диспетчер
dp = Dispatcher()

mv = MessagesVectorizer(settings=settings, url='http://host.docker.internal:5123/vectorize', vector_size=1024, bot=bot)
rdc = RatesDataCollector(settings["db_config"])

# Создаем объект DBManager
# для тестового бота дабаз: "exchange_rates_dev"
db_manager = DBManager( settings["db_config"], dbname="exchange_rates_dev" if settings["DEV"] else "exchange_rates" )

# Описание бота для LLM
bot_description = """\
You are a helpful assistant. You always answer in Russian.
Ты - ARS Inform, Telegram-бот, созданный для предоставления информации об Аргентине. 
Твоя задача - помогать пользователям получать информацию об Аргентине, 
отвечая на их вопросы и выполняя релевантные действия. 

**Всегда будь вежливым и дружелюбным в общении с пользователями.**
"""
# Инициализация LLMHelper
llm_helper = LLMHelper(GROQ_API_KEY, settings["GROQ_MODEL"], bot_description)

async def check_cache( chat_id, message ):
    if chat_id in cache:
        return
    else:
        user = await bot.get_chat(chat_id) # Получаем информацию о пользователе
        # Проверяем наличие пользователя в базе данных
        user_data = db_manager.get_user(user.id)
        if user_data and user_data[5] is not None: # Проверяем наличие настроек
            # Загружаем настройки пользователя из базы данных
            cache[chat_id] = {
                "settings": user_data[5],
                "current_page": 0,
                "is_new": True,
                "wait": None,
                "timestamp": time.time()
            }
        else:
            # Создаем новую запись для пользователя в базе данных, если его нет
            if not user_data:
                db_manager.add_user(user.id, user.username, user.first_name, user.last_name, message.from_user.language_code)
            db_manager.add_user_settings(user.id, json.dumps(settings_def))
            cache[chat_id] = {
                "settings": settings_def,
                "current_page": 0,
                "is_new": True,
                "wait": None,
                "timestamp": time.time()
            }

def make_kb( chat_id ):
    encoded_settings = base64.urlsafe_b64encode(json.dumps(cache[chat_id]["settings"]).encode()).decode()
    url = f"https://denser-ru.github.io/ars_bot_webapp/settings.html?settings={encoded_settings}"
    kb = [
        [
            types.KeyboardButton(text="/start"),
            types.KeyboardButton(text="/search"),
            types.KeyboardButton(text="/currency")
        ],
        [
            types.KeyboardButton(text="/settings", web_app=WebAppInfo(url=url)),
            types.KeyboardButton(text="/help")
        ],
    ]
    keyboard = types.ReplyKeyboardMarkup(
        keyboard=kb,
        resize_keyboard=True,
        input_field_placeholder="Выберите команду"
    )
    return keyboard


# Создаем функцию-обработчик для команды /start
@dp.message(Command("start")) # Используем фильтр Command вместо декоратора command_handler
async def start(message: aiogram.types.Message):
    # Приветствуем пользователя
    start_text = """\
<b>¡Hola! 👋  Я - ARS Inform, твой аргентинский друг в мире информации.</b> 🇦🇷  

🔎 <i>Использую силу искусственного интеллекта, чтобы находить для тебя самую релевантную информацию об Аргентине.</i> 

Хочешь узнать последние новости? 📰 Найти уютный ресторанчик или спланировать путешествие? ✈️  А может, интересуешься курсом песо? 💸  

Просто напиши мне свой вопрос, как другу. 😉

💡 <i>Хочешь узнать больше? Жми /help!</i>
"""

    # метод row позволяет явным образом сформировать ряд
    # из одной или нескольких кнопок.
    chat_id = message.chat.id

    await check_cache( chat_id, message )

    keyboard = make_kb( chat_id )

    db_manager.log_user_action(message.from_user.id, "start")

    await message.answer( start_text, parse_mode='HTML', reply_markup=keyboard, )

@dp.message(F.web_app_data)
async def handle_web_app_data(message: types.Message):
    # Теперь вы можете использовать web_app_data в вашем коде
    data = json.loads(message.web_app_data.data)
    logger.debug(f"Получены данные:{data}")
    chat_id = message.chat.id
    await check_cache( chat_id, message )
    cache[chat_id]["settings"] = data

    keyboard = make_kb( chat_id )

        # Сохраняем настройки пользователя в базу данных
    db_manager.update_user_settings(chat_id, json.dumps(data))

    db_manager.log_user_action(message.from_user.id, "settings", json.dumps(data))

    # await message.answer(f"Новые настройки сохранены": {message.web_app_data.data}", reply_markup=keyboard)
    await message.answer("Новые настройки сохранены", reply_markup=keyboard)

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    db_manager.log_user_action(message.from_user.id, "help")
    help_text = """\
<b>ARS Inform - твой гид по Аргентине!</b> 🇦🇷

<b>Что я умею?</b>

• <i>Нахожу ответы на твои вопросы:</i> Спрашивай меня о чем угодно, связанном с Аргентиной! Я использую искусственный интеллект для понимания твоих запросов и поиска максимально релевантной информации.
• <i>Делюсь последними новостями:</i> Узнай, что происходит в Аргентине прямо сейчас! (в разработке)
• <i>Помогаю спланировать путешествие:</i>  Найду лучшие места для отдыха, расскажу о достопримечательностях и помогу с визой.
• <i>Сообщаю актуальный курс валют:</i>  Будь в курсе последних изменений курса аргентинского песо.

<b>Как пользоваться?</b>

• <i>Просто напиши мне свой вопрос.</i> Не стесняйся использовать естественный язык, я тебя пойму! 
• <i>Используй команды:</i>
    • /start - начать работу с ботом
    • /search - поиск по ключевым словам (например, <code>/search лучшие рестораны Буэнос-Айреса</code>)
    • /news - последние новости (в разработке)
    • /currency - актуальный курс валют 
    • /settings - настройка параметров поиска: 
        • Вы можете указать временной диапазон для поиска информации. 
        • Выберите, как сортировать результаты: по релевантности или по дате.

<b>ARS Inform - твой надежный помощник в мире информации об Аргентине!</b> 
"""
    await message.reply( help_text, parse_mode='HTML' )

@dp.message(Command("search"))
async def cmd_search(
        message: types.Message,
        command: CommandObject
        ):

    chat_id = message.chat.id
    await check_cache( chat_id, message )

    # Поиск сообщений
    await search( chat_id, message, command.args )

async def search( chat_id, message, command_args ):
    # Если не переданы никакие аргументы, то
    # command.args будет None

    # Логируем действие пользователя "поиск"
    db_manager.log_user_action(message.from_user.id, "search", command_args)
    if not chat_id in cache:
        await check_cache( chat_id, message )
    cache[chat_id]["is_new"] = True

    if command_args is None:
        await message.reply(
            "Напишите ваш текст поискового запроса следующим сообщением:"
        )
        # Установка флага ожидания ввода поискового запроса
        cache[chat_id]["wait"] = "search"
        return

    results = mv.search_query(
        command_args,
        start_date=cache[chat_id]["settings"]["start_date"],
        end_date=cache[chat_id]["settings"]["end_date"],
        sorting=cache[chat_id]["settings"]["sort_by"],
        limit=50
    )
    # Выведите результаты поиску на экран или в файл

    # Кэширование результатов
    cache[chat_id]["search_query"] = command_args
    cache[chat_id]["results"] = results[:50]
    cache[chat_id]["wait"] = None
    cache[chat_id]["timestamp"] = time.time()
    # Отображение первой страницы результатов
    await display_results_page( message, chat_id, 0 )

async def display_results_page(message, chat_id, page_number):
    # Проверка срока жизни кэша
    if chat_id not in cache or time.time() - cache[chat_id]["timestamp"] > CACHE_TTL:
        await message.reply("Результаты поиска устарели. Повторите запрос.")
        return

    results = cache[chat_id]["results"]
    start_index = page_number * 10
    end_index = min(start_index + 10, len(results))

    # Форматирование результатов поиска
    results_text = mv.interpret_vector_search_result(results[start_index:end_index])

    # Клавиатура с кнопками
    buttons = []
    if page_number > 0:
        buttons.append(InlineKeyboardButton(text="Назад", callback_data=f"prev_page:{chat_id}"))
    if end_index < len(results):
        buttons.append(InlineKeyboardButton(text="Вперед", callback_data=f"next_page:{chat_id}"))
    keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons])

    # Отправка/обновление сообщения
    if page_number == 0 and cache[chat_id]["is_new"]:
        cache[chat_id]["is_new"] = False
        await message.reply(text=f"Вы искали: <pre>{cache[chat_id]['search_query']}</pre>\n\nНайдено:\n{results_text}", reply_markup=keyboard, parse_mode='HTML')
    else:
        await message.edit_text(text=f"Вы искали: <pre>{cache[chat_id]['search_query']}</pre>\n\nНайдено:\n{results_text}", reply_markup=keyboard, parse_mode='HTML')


@dp.callback_query(lambda c: c.data.startswith("prev_page:") or c.data.startswith("next_page:"))
async def handle_pagination(callback_query: types.CallbackQuery):
    chat_id = int(callback_query.data.split(":")[1])
    action = callback_query.data.split(":")[0]

    if chat_id not in cache:
        return

    current_page = cache[chat_id]["current_page"]
    if action == "prev_page":
        new_page = max(0, current_page - 1)
    else:
        new_page = min(4, current_page + 1)

    cache[chat_id]["current_page"] = new_page
    await display_results_page(callback_query.message, chat_id, new_page)

@dp.message(Command("news"))
async def cmd_news(message: types.Message):
    db_manager.log_user_action(message.from_user.id, "news")
    await message.reply("Команда <code>/news</code> пока ещё в разработке", parse_mode='HTML')

@dp.message( Command( "currency" ) )
async def cmd_currency( message: types.Message ):
    rates_sources = rdc.get_sourses()

    # Логируем действие пользователя "получение курса валют"
    db_manager.log_user_action(message.from_user.id, "currency")

    rate_txt_line = '' 
    for row in rates_sources:
        source_name, source_id, title = row
        latest_data_sell = rdc.get_data( source_id, 'SELL' )[0]
        latest_data_buy = rdc.get_data( source_id, 'BUY')[0]
        time_delta = timedelta(hours=-3)
        rate_txt_line += f"<pre>{ title }: "
        rate_txt_line += f'[<i>{(latest_data_sell[5] + time_delta).strftime("%Y-%m-%d %H:%M")}</i>]\n'
        rate_txt_line += f'    <b>{round(latest_data_sell[4], 2)}</b> / <b>{round(latest_data_buy[4], 2)}</b></pre>\n\n'
    msg = "<b>Курсы ARS к USD</b> (USDT)\n\n" + rate_txt_line
    await message.reply(msg, parse_mode='HTML')

# Обработчик всех сообщений, которое не является командой и не определённых команд
@dp.message()
async def handle_message(message: types.Message):
    chat_id = message.chat.id
    await check_cache( chat_id, message )
    # Проверяем тип сообщения
    if message.content_type == 'text':
        # Обрабатываем текстовое сообщение
        if message.text.startswith('/'):
            command = message.text.split()[0]
            db_manager.log_user_action(message.from_user.id, "unknown_command", message.text)
            await message.reply(f"Извини, я не знаю такой команды <code>{ command }</code>. Попробуй ещё раз.", parse_mode='HTML')
        else:
            if chat_id in cache and cache[chat_id]["wait"] == "search":
                cache[chat_id]["is_new"] = True
                await search( chat_id, message, message.text )
            else:
                db_manager.log_user_action(message.from_user.id, "message", message.text)
                # Вызов LLM для обработки текста, не являющегося командой
                llm_response = await llm_helper.process_user_input(message.text)

                # Обработка ответа LLM
                if llm_response is not None:
                    # Проверяем, является ли ответ вызовом функции или текстом
                    if isinstance(llm_response, dict) and "name" in llm_response:
                        await process_llm_response(message, llm_response) 
                    else:
                        # Ответ - это просто текст
                        await message.reply(llm_response)
                # else:
                    # ... (обработка случая, когда LLM вернул None) ..
    else:
        # Обрабатываем другие типы сообщений
        content_type = message.content_type
        db_manager.log_user_action(message.from_user.id, content_type)


async def process_llm_response(message, llm_response):
    #  Эта функция теперь вызывается только если LLM выбрал функцию
    function_name = llm_response.get("name")
    function_args = llm_response.get("content")

    chat_id = message.chat.id
    if function_name == "search_information":
        await search(chat_id, message, function_args)
    elif function_name == "about_bot":
        await cmd_help( message )
    elif function_name == "currency":
        await cmd_currency( message )
    # ... (обработка других функций) ..

class MessageData(BaseModel):  # Модель для данных сообщения
    chat_id: int
    message_text: str

@app.post("/send_message")
async def send_message(message_data: MessageData, api_token: str = Header(None, alias="Authorization")):  # <-- Принимаем данные сообщения
    # Проверяем наличие заголовка Authorization
    if api_token is None:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    # Извлекаем токен из заголовка
    parts = api_token.split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer": #<-- Добавлена эта проверка
        raise HTTPException(status_code=401, detail="Invalid Authorization header format")

    api_token = parts[1]

    # Сравниваем токен БЕЗ "Bearer "
    if api_token != settings["fastapi_token"]: 
        print(f"api_token: {api_token}")
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        await bot.send_message(chat_id=message_data.chat_id, text=message_data.message_text, parse_mode='HTML')  # <-- Используем данные из объекта
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.on_event("startup") 
async def startup_event():
    """Функция запускается при старте приложения"""
    print("Бот запущен!")

@dp.callback_query( F.data == "random_value" )
async def send_random_value(callback: types.CallbackQuery):
    await callback.message.answer(str(randint(1, 10)))

# Запуск процесса поллинга новых апдейтов
async def main():
    # Сначала проверяем соединение бота
    await bot_test(bot)
    # # Затем начинаем поллинг
    # await dp.start_polling(bot)

    # Затем начинаем поллинг
    asyncio.create_task(dp.start_polling(bot)) 

    # Создание конфигурации сервера uvicorn
    config = uvicorn.Config(app, host=settings["fastapi_host"], port=settings["fastapi_port"], log_level="info")
    server = uvicorn.Server(config)

    # Запуск сервера в отдельной задаче asyncio
    await server.serve()

if __name__ == "__main__":
    asyncio.run(main())