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

from search import MessagesVectorizer
from binance_data_collector import RatesDataCollector
from db_manager import DBManager

# Импортируем настроки журналирования из файла logger.py
from logger import logger
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
else:
    TOKEN = settings["bot_key"]

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

# Объект бота
bot = Bot(token=TOKEN)
# Диспетчер
dp = Dispatcher()

mv = MessagesVectorizer(settings=settings, url='http://host.docker.internal:5123/vectorize', vector_size=1024, bot=bot)
rdc = RatesDataCollector(settings["db_config"])

# Создаем объект DBManager
# для тестового бота дабаз: "exchange_rates_dev"
db_manager = DBManager( settings["db_config"], dbname="exchange_rates_dev" if settings["DEV"] else "exchange_rates" )

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


# Создаем функцию-обработчик для команды /start
@dp.message(Command("start")) # Используем фильтр Command вместо декоратора command_handler
async def start(message: aiogram.types.Message):
    # Приветствуем пользователя
    start_text = f"""<b>Хочешь быть в курсе всех событий в Аргентине? 🇦🇷</b>

<b>ARS Inform — это твой личный гид по всему, что происходит в Аргентине!</b>

<b>Я найду для тебя:</b>

* <b>Самые свежие новости и обсуждения:</b> От футбола до политики,  узнай все, что тебя интересует! ⚽️📰
* <b>Отзывы о лучших ресторанах, достопримечательностях и многом другом:</b>  Ищешь идеальное место для ужина в Буэнос-Айресе или хочешь узнать, как получить визу? Я помогу! 🍽️🗺️
* <b>Актуальный курс аргентинского песо:</b>  Следи за выгодными предложениями по обмену валют! 💸

<b>ARS Inform использует передовые технологии векторного поиска, чтобы находить информацию, даже если ты не знаешь точных ключевых слов.  Например, вместо того, чтобы искать "лучшие рестораны Буэнос-Айреса", ты можешь просто написать "вкусные места в Буэнос-Айресе" и я пойму, что ты хочешь!</b>

<b>Не трать время на долгий поиск в интернете! ARS Inform  найдет информацию за тебя!</b>

<b>Начни использовать меня прямо сейчас!</b>

* <b>Введи свой вопрос:</b>  Задай мне вопрос об Аргентине! 🤔
* <b>Используй команду /search:</b>  Например, `/search лучшие рестораны Буэнос-Айреса`  или `/search как получить визу в Аргентину` 🔎
* <b>Попробуй также команды:</b> `/news`, `/currency`.

<b>Я буду рад тебе помочь! 😊</b>"""

    # метод row позволяет явным образом сформировать ряд
    # из одной или нескольких кнопок.
    chat_id = message.chat.id

    await check_cache( chat_id, message )

    encoded_settings = base64.urlsafe_b64encode(json.dumps(cache[chat_id]["settings"]).encode()).decode()
    url = f"https://denser-ru.github.io/ars_bot_webapp/settings.html?settings={encoded_settings}"
    # web_app_button = InlineKeyboardButton(text="Открыть настройки",
    #                                   web_app=WebAppInfo(url="https://your-web-app-url.com"))
    kb = [
        [
            types.KeyboardButton(text="/start"),
            types.KeyboardButton(text="/search"),
            types.KeyboardButton(text="/settings", web_app=WebAppInfo(url=url)),
            types.KeyboardButton(text="/currency")
        ],
    ]
    keyboard = types.ReplyKeyboardMarkup(
        keyboard=kb,
        resize_keyboard=True,
        input_field_placeholder="Выберите команду"
    )

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
    encoded_settings = base64.urlsafe_b64encode(json.dumps(cache[chat_id]["settings"]).encode()).decode()
    url = f"https://denser-ru.github.io/ars_bot_webapp/settings.html?settings={encoded_settings}"
    kb = [
        [
            types.KeyboardButton(text="/start"),
            types.KeyboardButton(text="/search"),
            types.KeyboardButton(text="/settings", web_app=WebAppInfo(url=url)),
            types.KeyboardButton(text="/currency")
        ],
    ]
    keyboard = types.ReplyKeyboardMarkup(
        keyboard=kb,
        resize_keyboard=True,
        input_field_placeholder="Выберите команду"
    )

        # Сохраняем настройки пользователя в базу данных
    db_manager.update_user_settings(chat_id, json.dumps(data))

    db_manager.log_user_action(message.from_user.id, "settings", json.dumps(data))

    # await message.answer(f"Новые настройки сохранены": {message.web_app_data.data}", reply_markup=keyboard)
    await message.answer("Новые настройки сохранены", reply_markup=keyboard)

@dp.message(Command("resume"))
async def cmd_resume(message: types.Message):
    db_manager.log_user_action(message.from_user.id, "resume")
    await message.reply("Команда <code>/resume</code> пока ещё в разработке", parse_mode='HTML')

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
    else:
        # Обрабатываем другие типы сообщений
        content_type = message.content_type
        db_manager.log_user_action(message.from_user.id, content_type)


@dp.callback_query(F.data == "random_value")
async def send_random_value(callback: types.CallbackQuery):
    await callback.message.answer(str(randint(1, 10)))

# Запуск процесса поллинга новых апдейтов
async def main():
    # Сначала проверяем соединение бота
    await bot_test(bot)
    # Затем начинаем поллинг
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())