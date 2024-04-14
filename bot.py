# Импортируем необходимые библиотеки
import asyncio, logging, json
from random import randint
import aiogram
from aiogram import Bot, Dispatcher, types
from aiogram.filters.command import Command
from aiogram.filters import CommandObject
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram import F

from search import MessagesVectorizer

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
<code>/resume</code> - обобщить текущую беседу 📝
<code>/search</code> - поиск по сообщениям в тематических чатах/каналах 🔎
<code>/news</code> - подборка новостей по ключевым словам и без 📢
<code>/currency</code> - получить актуальные курсы валют на популярных торговых площадках(ARS, RUB, USDT...)💱

Я надеюсь, что вы будете довольны моим сервисом и найдете то, что ищете. 😊
""", parse_mode='HTML')

    builder = ReplyKeyboardBuilder()
    # метод row позволяет явным образом сформировать ряд
    # из одной или нескольких кнопок.
    kb = [
        [
            types.KeyboardButton(text="/start"),
            types.KeyboardButton(text="/resume"),
            types.KeyboardButton(text="/currency")
        ],
    ]
    keyboard = types.ReplyKeyboardMarkup(
        keyboard=kb,
        resize_keyboard=True,
        input_field_placeholder="Выберите способ подачи"
    )

    # await message.answer(
    #     "Вы можете написать мне зарос, команду или выберать действие в меню(⌘):",
    #     reply_markup=builder.as_markup(resize_keyboard=True),
    # )

    await message.answer(
        "Вы можете написать мне зарос, команду или выберать действие в меню(⌘):", reply_markup=keyboard,
    )

# @dp.message(F.text.lower() == "с пюрешкой")
# async def with_puree(message: types.Message):
#     await message.reply("Отличный выбор!")

# @dp.message(F.text.lower() == "без пюрешки")
# async def without_puree(message: types.Message):
#     await message.reply("Так невкусно!")


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
    results = mv.search_query(command.args)
    # Выведите результаты поиску на экран или в файл
    results_text = mv.interpret_vector_search_result(results)
    await message.reply(f"Вы искали: <pre>{command.args}</pre>\n\nНайдено:\n{results_text}", parse_mode='HTML')

@dp.message(Command("news"))
async def cmd_news(message: types.Message):
    await message.reply("Команда <code>/news</code> пока ещё в разработке", parse_mode='HTML')

@dp.message(Command("currency"))
async def cmd_currency(message: types.Message):
    await message.reply("Команда <code>/currency</code> пока ещё в разработке", parse_mode='HTML')


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