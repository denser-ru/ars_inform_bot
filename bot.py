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
TOKEN = "6704611209:AAEPk5dX1NPkqS3RBuC6Q0DeiwsJncR_7U8"

# Словарь для кэширования результатов поиска
cache = {}
# Время жизни кэша (в секундах)
CACHE_TTL = 300
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
db_manager = DBManager(settings["db_config"])


# Создаем функцию-обработчик для команды /start
@dp.message(Command("start")) # Используем фильтр Command вместо декоратора command_handler
async def start(message: aiogram.types.Message):
    # Приветствуем пользователя
    await message.reply("""<b>Добро пожаловать в ARS Inform! 🇦🇷</b>

<i>Меня зовут ARS, можно также обращаться как Арсик, и я поисковый бот Телеграмма, который поможет вам найти интересующую вас информацию по Аргентине. 🗺️</i>

С моей помощью вы можете:
- Искать по тематическим форумам Аргентины, где обсуждаются различные вопросы, связанные с политикой, экономикой, культурой, спортом и т.д. 💬
- Получать свежие и актуальные новости по ключевым словам или без них, чтобы быть в курсе последних событий в стране и мире. 📰
- Собирать тематическую информацию по вашему запросу, например, о достопримечательностях, истории, географии, климате, населении и т.д. 📚

<b><u>Для начала работы с ботом введите одну из следующих команд:</u></b>
<code>/start</code> - начать новую беседу 🆕
<code>/settings</code> - настройки поиска 📝
<code>/search</code> - поиск по сообщениям в тематических чатах/каналах 🔎
<code>/news</code> - подборка новостей по ключевым словам и без 📢
<code>/currency</code> - получить актуальные курсы валют на популярных торговых площадках(ARS, RUB, USDT...)💱

Я надеюсь, что вы будете довольны моим сервисом и найдете то, что ищете. 😊
""", parse_mode='HTML')

    # метод row позволяет явным образом сформировать ряд
    # из одной или нескольких кнопок.
    chat_id = message.chat.id
    user = await bot.get_chat(chat_id) # Получаем информацию о пользователе

    # Проверяем наличие пользователя в базе данных
    user_data = db_manager.get_user(user.id)
    if user_data and user_data[5] is not None: # Проверяем наличие настроек
        # Загружаем настройки пользователя из базы данных
        cache[chat_id] = {
            "settings": user_data[5],
            "current_page": 0,
            "is_new": True,
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
            "timestamp": time.time()
        }
    encoded_settings = base64.urlsafe_b64encode(json.dumps(cache[chat_id]["settings"]).encode()).decode()
    url = f"https://denser-ru.github.io/ars_bot_webapp/settings.html?settings={encoded_settings}"
    # web_app_button = InlineKeyboardButton(text="Открыть настройки",
    #                                   web_app=WebAppInfo(url="https://your-web-app-url.com"))
    kb = [
        [
            types.KeyboardButton(text="/start"),
            types.KeyboardButton(text="/settings", web_app=WebAppInfo(url=url)),
            types.KeyboardButton(text="/currency")
        ],
    ]
    keyboard = types.ReplyKeyboardMarkup(
        keyboard=kb,
        resize_keyboard=True,
        input_field_placeholder="Выберите команду"
    )

    await message.answer(
        "Вы можете написать мне зарос, команду или выберать действие в меню(⌘):", reply_markup=keyboard,
    )

@dp.message(F.web_app_data)
async def handle_web_app_data(message: types.Message):
    # Теперь вы можете использовать web_app_data в вашем коде
    data = json.loads(message.web_app_data.data)
    logger.debug(f"Получены данные:{data}")
    chat_id = message.chat.id
    if chat_id in cache:
        cache[chat_id]["settings"] = data
    else:
        cache[chat_id] = {
            "settings": data,
            "current_page": 0,
            "is_new": True,
            "timestamp": time.time()
        }
    encoded_settings = base64.urlsafe_b64encode(json.dumps(cache[chat_id]["settings"]).encode()).decode()
    url = f"https://denser-ru.github.io/ars_bot_webapp/settings.html?settings={encoded_settings}"
    kb = [
        [
            types.KeyboardButton(text="/start"),
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

    # await message.answer(f"Новые настройки сохранены": {message.web_app_data.data}", reply_markup=keyboard)
    await message.answer("Новые настройки сохранены", reply_markup=keyboard)

@dp.message(Command("random"))
async def cmd_random(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(
        text="Нажми меня",
        callback_data="random_value")
    )
    await message.answer(
        "Нажмите на кнопку, чтобы бот отправил число от 1 до 10",
        reply_markup=builder.as_markup()
    )

@dp.message(Command("resume"))
async def cmd_resume(message: types.Message):
    await message.reply("Команда <code>/resume</code> пока ещё в разработке", parse_mode='HTML')

@dp.message(Command("search"))
async def cmd_search(
        message: types.Message,
        command: CommandObject
        ):
    # Если не переданы никакие аргументы, то
    # command.args будет None
    if command.args is None:
        await message.reply(
            "Ошибка: не переданы аргументы"
        )
        return
    chat_id = message.chat.id

    # Логируем действие пользователя "поиск"
    db_manager.log_user_action(message.from_user.id, "search", command.args)

    results = mv.search_query(
        command.args,
        start_date=cache[chat_id]["settings"]["start_date"],
        end_date=cache[chat_id]["settings"]["end_date"],
        sorting=cache[chat_id]["settings"]["sort_by"],
        limit=50
    )
    # Выведите результаты поиску на экран или в файл

    # Кэширование результатов
    
    if chat_id in cache:
        set_settings = cache[chat_id]["settings"]
    else:
        set_settings = settings_def
    cache[chat_id] = {
        "search_query": command.args,
        "results": results[:50],
        "settings": set_settings,
        "current_page": 0,
        "is_new": True,
        "timestamp": time.time()
    }

    # Отображение первой страницы результатов
    await display_results_page(message, chat_id, 0)

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
    await message.reply("Команда <code>/news</code> пока ещё в разработке", parse_mode='HTML')

@dp.message( Command( "currency" ) )
async def cmd_currency( message: types.Message ):
    rates_sources = rdc.get_sourses()
    # Преобразование в словарь
    # rates_sources_dict = {source: rate for source, rate in rates_sources}
    # rates_sources_dict = dict( rates_sources )
    # logger.debug( f"rates_sources: { rates_sources_dict }" )
    # Проход по словарю

    # Логируем действие пользователя "получение курса валют"
    db_manager.log_user_action(message.from_user.id, "currency")

    rate_txt_line = '' 
    for row in rates_sources:
        source_name, source_id, title = row
        latest_data_sell = rdc.get_data( source_id, 'SELL' )[0]
        latest_data_buy = rdc.get_data( source_id, 'BUY')[0]
        time_delta = timedelta(hours=-3)
        rate_txt_line += f"<blockquote><code>({ title }):</code>\n"
        rate_txt_line += f'<i>д.п. обновления: {(latest_data_sell[5] + time_delta).strftime("%Y-%m-%d %H:%M")}</i></blockquote>'
        rate_txt_line += f'    <b>{round(latest_data_sell[4], 2)}</b> / <b>{round(latest_data_buy[4], 2)}</b>\n\n'
    msg = "<b>Курсы ARS к USD</b> (USDT)\n\n" + rate_txt_line
    await message.reply(msg, parse_mode='HTML')


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