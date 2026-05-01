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
from aiogram.types import  (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    WebAppInfo,
    Message,
    CallbackQuery
)

import uvicorn
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel

from utils.search import MessagesVectorizer
from utils.binance_data_collector import RatesDataCollector
from utils.db_manager import DBManager
from utils.llm_helper import LLMHelper
from subscription_manager.subscription_manager import SubscriptionManager

from typing import Callable, Optional

from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext



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

WAITING_FOR_QUERY_TIMEOUT = 60  # Таймаут ожидания в секундах


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

# Создаем объект SubscriptionManager
manager = SubscriptionManager(
    db_config=settings["db_config"],
    vectorizer=mv,  # Передаем объект MessagesVectorizer
    bot_webhook_url=f"{settings['fastapi_host']}:{settings['fastapi_port']}/send_message",
    bot_webhook_token=settings['fastapi_token'] 
)

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

def make_kb( chat_id: int ):
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
            types.KeyboardButton(text="/subscriptions"),
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
• <i>Помогаю с подписками:</i> Создай подписку на интересующую тебя тему, и я буду присылать уведомления о новых релевантных сообщениях.

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
    • /subscriptions - управление подписками:
        • Создать подписку
        • Посмотреть список активных подписок
        • Изменить или удалить подписку
        • Подробнее о подписках - /subscription_help
    • /feedback - оставить отзыв о боте

<b>ARS Inform - твой надежный помощник в мире информации об Аргентине!</b> 
    """
    await message.reply( help_text, parse_mode='HTML' )


async def wait_for_user_input(
    message: types.Message, 
    state: FSMContext,
    state_to_set: State,
    timeout: int = WAITING_FOR_QUERY_TIMEOUT,
    cancel_callback: Optional[Callable] = None,
    input_request_message: str = "Ожидаю ваш ввод:", #  Параметр для текста сообщения 
):
    """Ожидает ввода пользователя с таймаутом и кнопкой отмены.

    Args:
        message: Сообщение, на которое ожидается ответ.
        state: Объект FSMContext.
        state_to_set: Состояние FSM, которое нужно установить.
        timeout: Время ожидания в секундах.
        cancel_callback: Функция, которая будет вызвана при отмене.
        input_request_message: Текст сообщения с запросом ввода от пользователя. 
    """

    # Создаём клавиатуру с кнопкой отмены
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отмена", callback_data="cancel_input")]
    ])

    # Проверяем тип message
    if isinstance(message, Message):
        await message.reply(input_request_message, reply_markup=keyboard)
    elif isinstance(message, CallbackQuery):
        await message.message.edit_text(input_request_message, reply_markup=keyboard)

    await state.set_state(state_to_set)

    # Запускаем таймаут ожидания
    await asyncio.sleep(timeout)

    # Если состояние не изменилось, значит ответа не было
    if await state.get_state() == state_to_set:
        await state.set_state(None)
        # Проверяем тип message
        if isinstance(message, Message):
            await message.reply("Время ожидания ввода истекло.")
        elif isinstance(message, CallbackQuery):
            await message.message.edit_text("Время ожидания ввода истекло.")
        if cancel_callback:
            await cancel_callback(message)  # Вызываем callback-функцию


class SearchStates(StatesGroup):
    WAITING_FOR_QUERY = State()

# Обработчик нажатия кнопки "Отмена" (теперь общий)
@dp.callback_query(F.data.startswith("cancel_input"))
async def cancel_input(callback_query: types.CallbackQuery, state: FSMContext):
    await state.set_state(None)
    await callback_query.message.edit_text("Действие отменено.")

@dp.message(Command("search"))
async def cmd_search(
        message: types.Message,
        command: CommandObject,
        state: FSMContext
        ):

    chat_id = message.chat.id
    await check_cache( chat_id, message )

    # Поиск сообщений
    if command.args: 
        # Текст запроса передан сразу с командой
        await search(chat_id, message, command.args)
    else:
        # Текст запроса не передан, запрашиваем у пользователя
        await wait_for_user_input(
        message, 
        state, 
        SearchStates.WAITING_FOR_QUERY, 
        input_request_message="Напишите ваш поисковый запрос:"
    )

# Обработчик состояния ожидания поискового запроса
@dp.message(F.state == SearchStates.WAITING_FOR_QUERY)
async def process_search_query(message: types.Message, state: FSMContext):
    chat_id = message.chat.id
    await check_cache(chat_id, message)
    await search(chat_id, message, message.text)
    await state.set_state(None)

async def search( chat_id, message, command_args ):
    # Логируем действие пользователя "поиск"
    db_manager.log_user_action(message.from_user.id, "search", command_args)
    if not chat_id in cache:
        await check_cache( chat_id, message )
    cache[chat_id]["is_new"] = True

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

class CurrencyStates(StatesGroup):
    WAITING_FOR_DATE = State()

@dp.message( Command( "currency" ) )
async def cmd_currency( message: types.Message ):
    rates_sources = rdc.get_sourses()
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
    
    # --- НОВЫЙ БЛОК: Кнопка для вызова истории ---
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Узнать курс на выбранную дату", callback_data="history_currency")]
    ])
    await message.reply(msg, parse_mode='HTML', reply_markup=keyboard)


@dp.callback_query(F.data == "history_currency")
async def ask_for_historical_date(callback_query: types.CallbackQuery, state: FSMContext):
    # Вызываем уже существующую функцию запроса ввода
    await wait_for_user_input(
        callback_query,
        state, 
        CurrencyStates.WAITING_FOR_DATE, 
        input_request_message="Введите дату в формате ГГГГ-ММ-ДД (например, 2023-10-25):"
    )

@dp.message(F.state == CurrencyStates.WAITING_FOR_DATE)
async def process_historical_currency(message: types.Message, state: FSMContext):
    target_date = message.text.strip()
    
    try:
        datetime.strptime(target_date, "%Y-%m-%d")
    except ValueError:
        await wait_for_user_input(
            message,
            state,
            CurrencyStates.WAITING_FOR_DATE,
            input_request_message="❌ Неверный формат. Пожалуйста, введите дату строго в формате ГГГГ-ММ-ДД:"
        )
        return

    result = db_manager.get_rate_by_date(target_date=target_date) 
    
    if not result:
        await message.reply("Не удалось выполнить поиск по базе данных.")
    elif result["status"] == "exact":
        rates_by_source = {}
        for row in result["data"]:
            source_name, rate_type, rate_val, dt = row
            if source_name not in rates_by_source:
                rates_by_source[source_name] = {"SELL": None, "BUY": None, "time": dt}
            rates_by_source[source_name][rate_type] = rate_val
            
        response = f"📅 <b>Курсы ARS к USD на {target_date}</b>\n\n"
        for src, data in rates_by_source.items():
            time_delta = timedelta(hours=-3)
            time_str = (data['time'] + time_delta).strftime("%Y-%m-%d %H:%M")
            
            # rate_val уже имеет тип decimal.Decimal, безопасно форматируем
            sell_val = f"{data['SELL']:.2f}" if data['SELL'] is not None else "---"
            buy_val = f"{data['BUY']:.2f}" if data['BUY'] is not None else "---"
            
            response += f"<pre>{src}: [{time_str}]\n    <b>{sell_val}</b> / <b>{buy_val}</b></pre>\n\n"
            
        await message.reply(response, parse_mode='HTML')
    elif result["status"] == "nearest":
        before = result.get("before_date")
        after = result.get("after_date")
        
        response = f"Точных данных за <b>{target_date}</b> не найдено. Ближайшие даты в базе:\n\n"
        if before:
            response += f"⬅️ До: <b>{before.strftime('%Y-%m-%d')}</b>\n"
        if after:
            response += f"➡️ После: <b>{after.strftime('%Y-%m-%d')}</b>\n"
        if not before and not after:
            response += "<i>В базе пока нет исторических данных для сравнения.</i>\n"
            
        await message.reply(response, parse_mode='HTML')
        
    await state.set_state(None)







class SubscriptionStates(StatesGroup):
    WAITING_FOR_QUERY = State()
    WAITING_FOR_THRESHOLD = State()
    EDITING_SUBSCRIPTION = State()

    WAITING_FOR_NEW_TEXT = State()
    WAITING_FOR_NEW_THRESHOLD = State()

class SubscriptionManagerFSM:
    """Класс для управления FSM, связанными с подписками."""

    def __init__(self, manager: SubscriptionManager):
        self.manager = manager

    async def cmd_newsubscription(self, message: types.Message, state: FSMContext):
        """Создает новую подписку."""
        # await state.set_state(SubscriptionStates.WAITING_FOR_QUERY)
        # await message.reply("Введите текст для новой подписки:")
        await wait_for_user_input(
        message, 
        state, 
        SubscriptionStates.WAITING_FOR_QUERY, 
        input_request_message="Введите текст для новой подписки:"
    )

    async def process_query(self, message: types.Message, state: FSMContext):
        """Обрабатывает текст новой подписки."""
        await state.update_data(query=message.text)
        await wait_for_user_input(
            message,
            state,
            SubscriptionStates.WAITING_FOR_THRESHOLD,
            input_request_message="Введите порог для новой подписки (от 0.00 до 0.80):"
        )

    async def process_threshold(self, message: types.Message, state: FSMContext):
        """Обрабатывает порог новой подписки."""
        try:
            threshold = float(message.text)
            if not 0.00 <= threshold <= 0.80:
                raise ValueError
        except ValueError:
            # await message.reply("Некорректный порог. Введите число от 0.00 до 0.80.")
            await wait_for_user_input(
                message,
                state,
                SubscriptionStates.WAITING_FOR_THRESHOLD,
                input_request_message="Некорректный порог. Введите число от 0.00 до 0.80:"
            )
            return

        user_data = await state.get_data()

        await self.manager.add_subscription(
            user_id=message.from_user.id,
            chat_id=message.chat.id,
            query=user_data["query"],
            threshold=threshold
        )
        await message.answer("Подписка успешно создана!")
        await state.set_state(None)

    async def cmd_mysubscriptions(self, message: types.Message):
        """Показывает список активных подписок пользователя."""
        user_id = message.from_user.id
        subscriptions = await self.manager.get_user_subscriptions(user_id)

        if subscriptions:
            message_text = "Ваши подписки:\n\n"
            for sub in subscriptions:
                message_text += (
                    f"ID: {sub[0]}\n"
                    f"Запрос: {sub[1]}\n"
                    f"Порог: {sub[2]:.2f}\n\n"
                )
            await message.reply(message_text)
        else:
            await message.reply("У вас пока нет активных подписок.")

    async def cmd_updatesubscription(self, message: types.Message, state: FSMContext):
        """Начинает процесс редактирования подписки."""
        user_id = message.from_user.id
        subscriptions = await self.manager.get_user_subscriptions(user_id)

        if subscriptions:
            await state.update_data(subscriptions=subscriptions)
            await self.show_subscriptions_for_editing(message, subscriptions)
        else:
            await message.reply("У вас пока нет активных подписок.")

    async def show_subscriptions_for_editing(self, message: types.Message, subscriptions):
        """Отображает кнопки для выбора подписки для редактирования."""
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"ID: {sub[0]}, Запрос: {sub[1]}",
                        callback_data=f"subscription_edit_{sub[0]}"
                    )
                ]
                for sub in subscriptions
            ],
            row_width=1
        )
        await message.reply("Выберите подписку для редактирования:", reply_markup=keyboard)

    async def process_subscription_selection(self, callback_query: types.CallbackQuery, state: FSMContext):
        """Обрабатывает выбор подписки для редактирования."""
        subscription_id = int(callback_query.data.split('_')[2])
        await state.update_data(subscription_id=subscription_id)
        await state.set_state(SubscriptionStates.EDITING_SUBSCRIPTION)
        await self.show_edit_options(callback_query.message, subscription_id)
    
    async def show_edit_options(self, message: types.Message, subscription_id: int):
        """Отображает кнопки для редактирования текста или порога подписки."""
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✏️ Изменить текст", callback_data=f"edit_text_{subscription_id}"),
                    InlineKeyboardButton(text="✏️ Изменить порог", callback_data=f"edit_threshold_{subscription_id}"),
                    InlineKeyboardButton(text="❌ Удалить", callback_data=f"subscription_delete_{subscription_id}")
                ]
            ],
            row_width=1
        )
        await message.edit_text(f"Выберите действие для подписки ID: {subscription_id}", reply_markup=keyboard)

    async def process_edit_text(self, callback_query: types.CallbackQuery, state: FSMContext):
        """Обрабатывает выбор редактирования текста."""
        subscription_id = int(callback_query.data.split('_')[2])
        await state.update_data(subscription_id=subscription_id)
        await state.set_state(SubscriptionStates.WAITING_FOR_NEW_TEXT)
        await callback_query.answer()
        await self.ask_for_new_text(callback_query, subscription_id, state)

    # async def ask_for_new_text(self, message: types.Message, subscription_id: int):
    #     """Запрашивает у пользователя новый текст подписки."""
    #     await message.edit_text(f"Введите новый текст для подписки ID: {subscription_id}")
    async def ask_for_new_text(self, callback_query: CallbackQuery, subscription_id: int, state: FSMContext):
        """Запрашивает у пользователя новый текст подписки."""
        await wait_for_user_input(
            callback_query,
            state, 
            SubscriptionStates.WAITING_FOR_NEW_TEXT, 
            input_request_message=f"Введите новый текст для подписки ID: {subscription_id}"
        )

    async def process_new_text(self, message: types.Message, state: FSMContext):
        """Обрабатывает новый текст подписки."""
        user_data = await state.get_data()
        subscription_id = user_data["subscription_id"]
        new_text = message.text

        try:
            await self.manager.update_subscription(subscription_id, query=new_text)
            await message.answer(f"Текст подписки id={subscription_id} успешно обновлен!")
        except Exception as e:
            logger.error(f"Ошибка при обновлении текста подписки: {e}")
            await message.answer("Произошла ошибка при обновлении подписки. Попробуйте позже.")
        finally:
            await state.set_state(None)

    async def process_edit_threshold(self, callback_query: types.CallbackQuery, state: FSMContext):
        """Обрабатывает выбор редактирования порога."""
        subscription_id = int(callback_query.data.split('_')[2])
        await state.update_data(subscription_id=subscription_id)
        await state.set_state(SubscriptionStates.WAITING_FOR_NEW_THRESHOLD)
        await callback_query.answer()
        await self.ask_for_new_threshold(callback_query, subscription_id, state)

    # async def ask_for_new_threshold(self, message: types.Message, subscription_id: int):
    async def ask_for_new_threshold(self, callback_query: CallbackQuery, subscription_id: int, state: FSMContext):
        """Запрашивает у пользователя новый порог подписки."""
        # await message.edit_text(f"Введите новый порог (от 0.00 до 0.80) для подписки ID: {subscription_id}")
        await wait_for_user_input(
            callback_query,
            state, 
            SubscriptionStates.WAITING_FOR_NEW_THRESHOLD, 
            input_request_message=f"Введите новый порог (от 0.00 до 0.80) для подписки ID: {subscription_id}"
        )

    async def process_new_threshold(self, message: types.Message, state: FSMContext):
        """Обрабатывает новый порог подписки."""
        try:
            new_threshold = float(message.text)
            if not 0.00 <= new_threshold <= 0.80:
                raise ValueError
        except ValueError:
            # await message.reply("Некорректный порог. Введите число от 0.00 до 0.80.")
            await wait_for_user_input(
                message,
                state,
                SubscriptionStates.WAITING_FOR_THRESHOLD,
                input_request_message="Некорректный порог. Введите число от 0.00 до 0.80:"
            )
            return

        user_data = await state.get_data()
        subscription_id = user_data["subscription_id"]

        try:
            await self.manager.update_subscription(subscription_id, threshold=new_threshold)
            await message.answer(f"Порог подписки id={subscription_id} успешно обновлен!")
        except Exception as e:
            logger.error(f"Ошибка при обновлении порога подписки: {e}")
            await message.answer("Произошла ошибка при обновлении подписки. Попробуйте позже.")
        finally:
            await state.set_state(None)

    async def process_delete_subscription(self, callback_query: types.CallbackQuery):
        """Удаляет существующую подписку."""
        subscription_id = int(callback_query.data.split('_')[2])
        try:
            await self.manager.delete_subscription(subscription_id)
            await callback_query.message.answer(f"Подписка id={ subscription_id } удалена.")
            await callback_query.message.delete()
        except Exception as e:
            logger.error(f"Ошибка при удалении подписки: {e}")
            await callback_query.message.answer("Произошла ошибка. Попробуйте позже.")


# Создание экземпляра FSM менеджера
subscription_fsm = SubscriptionManagerFSM(manager)

# Создай экземпляр SubscriptionStates
subscription_states = SubscriptionStates()

# Регистрация обработчиков FSM
dp.message(Command("newsubscription"))(subscription_fsm.cmd_newsubscription)
dp.message(Command("mysubscriptions"))(subscription_fsm.cmd_mysubscriptions)
dp.message(Command("updatesubscription"))(subscription_fsm.cmd_updatesubscription)

# Обработчики для состояний FSM
dp.message(F.state == subscription_states.WAITING_FOR_QUERY)(subscription_fsm.process_query) # ⭐️ Изменен
dp.message(F.state == subscription_states.WAITING_FOR_THRESHOLD)(subscription_fsm.process_threshold) # ⭐️ Изменен
dp.message(F.state == subscription_states.WAITING_FOR_NEW_TEXT)(subscription_fsm.process_new_text) # ⭐️ Изменен
dp.message(F.state == subscription_states.WAITING_FOR_NEW_THRESHOLD)(subscription_fsm.process_new_threshold) # ⭐️ Изменен

# Обработчики callback-запросов
dp.callback_query(lambda c: c.data.startswith("subscription_edit_"))(subscription_fsm.process_subscription_selection)
dp.callback_query(lambda c: c.data.startswith("edit_text_"))(subscription_fsm.process_edit_text)
dp.callback_query(lambda c: c.data.startswith("edit_threshold_"))(subscription_fsm.process_edit_threshold)
dp.callback_query(lambda c: c.data.startswith("subscription_delete_"))(subscription_fsm.process_delete_subscription)








from aiogram.types import ReplyKeyboardRemove

# Добавляем новое состояние для отзыва
class FeedbackStates(StatesGroup):
    WAITING_FOR_FEEDBACK = State()

# Создаем экземпляр FeedbackStates
feedback_states = FeedbackStates()

# Создаем функцию-обработчик для команды /feedback
@dp.message(Command("feedback"))
async def cmd_feedback(message: types.Message, state: FSMContext):
    # await state.set_state(feedback_states.WAITING_FOR_FEEDBACK)
    # await message.answer(
    #     "Оставьте свой отзыв о работе бота ARS Inform:\n\n"
    #     "💬  Опишите, что вам понравилось или не понравилось.\n"
    #     "💡  Предложите идеи для улучшения.\n\n"
    #     "Ваше мнение поможет сделать бота лучше! 🙏",
    #     reply_markup=ReplyKeyboardRemove()
    #     )
    await wait_for_user_input(
        message,
        state,
        feedback_states.WAITING_FOR_FEEDBACK,
        input_request_message=
        "Оставьте свой отзыв о работе бота ARS Inform:\n\n"
        "💬  Опишите, что вам понравилось или не понравилось.\n"
        "💡  Предложите идеи для улучшения.\n\n"
        "Ваше мнение поможет сделать бота лучше! 🙏"
    )

# Обработчик для состояния ожидания отзыва
@dp.message(F.state == feedback_states.WAITING_FOR_FEEDBACK)
async def process_feedback(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    feedback = message.text
    db_manager.log_user_action(user_id, "feedback", feedback)  # Логируем отзыв
    await message.answer("Спасибо за ваш отзыв!")
    await state.clear()





@dp.message(Command("subscriptions"))
async def cmd_subscriptions(message: types.Message):
    """Отображает меню справки по менеджеру подписок."""
    db_manager.log_user_action(message.from_user.id, "subscriptions")

    # Кнопки для меню
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Создать подписку", callback_data="create_subscription"),
            ],
            [
                InlineKeyboardButton(text="Мои подписки", callback_data="my_subscriptions"),
            ],
            [
                InlineKeyboardButton(text="Изменить подписку", callback_data="update_subscription"),
            ],
            [
                InlineKeyboardButton(text="Подробнее", callback_data="subscription_help"),
            ],
        ]
    )

    await message.answer(
        "Менеджер подписок:\n\n"
        "Выберите нужное действие:",
        reply_markup=keyboard,
    )


@dp.callback_query(lambda c: c.data.startswith("create_subscription"))
async def handle_create_subscription(callback_query: types.CallbackQuery, state: FSMContext):
    # await state.set_state(SubscriptionStates.WAITING_FOR_QUERY)
    # await callback_query.message.answer(
    #     "Введите текст для новой подписки:\n\n"
    #     "Например: 'аргентина туризм' \n\n"
    #     "Бот будет отправлять вам сообщения, соответствующие этому запросу.",
    #     reply_markup=ReplyKeyboardRemove(),
    # )
    await wait_for_user_input(
        callback_query, # <-- Передаем CallbackQuery 
        state, 
        SubscriptionStates.WAITING_FOR_QUERY, 
        input_request_message=
            "Введите текст для новой подписки:\n\n"
            "Например: 'аргентина туризм' \n\n"
            "Бот будет отправлять вам сообщения, соответствующие этому запросу."
    )


@dp.callback_query(lambda c: c.data.startswith("my_subscriptions"))
async def handle_my_subscriptions(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    subscriptions = await manager.get_user_subscriptions(user_id)

    if subscriptions:
        message_text = "Ваши подписки:\n\n"
        for sub in subscriptions:
            message_text += (
                f"ID: {sub[0]}\n"
                f"Запрос: {sub[1]}\n"
                f"Порог: {sub[2]:.2f}\n\n"
            )
        await callback_query.message.answer(message_text)
    else:
        await callback_query.message.answer("У вас пока нет активных подписок.")


@dp.callback_query(lambda c: c.data.startswith("update_subscription"))
async def handle_update_subscription(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    subscriptions = await manager.get_user_subscriptions(user_id)

    if subscriptions:
        await state.update_data(subscriptions=subscriptions)
        await subscription_fsm.show_subscriptions_for_editing(callback_query.message, subscriptions)
    else:
        await callback_query.message.answer("У вас пока нет активных подписок.")


@dp.message(Command("subscription_help"))
async def cmd_subscription_help(message: types.Message):
    """Отображает подробную справку о менеджере подписок."""
    db_manager.log_user_action(message.from_user.id, "subscription_help")
    help_text = """\
    <b>Менеджер подписок</b>

    <b>Что такое подписки?</b>
    Подписки позволяют получать уведомления о новых сообщениях в чатах, соответствующих вашим интересам.

    <b>Как работают подписки?</b>
    1. **Создайте подписку:**  Введите поисковый запрос, по которому вы хотите получать уведомления.
    2. **Настройте порог сходства:**  Укажите, насколько точно сообщения должны соответствовать вашему запросу.
    3. **Получайте уведомления:**  Бот будет отправлять вам сообщения, которые соответствуют вашим критериям.

    <i>Порог сходства от 0.00 до 0.80 (чем меньше, тем ближе по смыслу). Рекомендуется подбирать порог для каждой поисковой фразы через поиск (/search) в диапозоне дат от 7 до 30 дней, сортируя по сходству.</i>

    <b>Команды менеджера подписок:</b>
    • **/subscriptions** - главное меню подписок
    • **/newsubscription** - создать новую подписку
    • **/mysubscriptions** - посмотреть список активных подписок
    • **/updatesubscription** - изменить или удалить подписку
    """
    await message.answer(help_text, parse_mode="HTML")

@dp.callback_query(lambda c: c.data.startswith("subscription_help"))
async def handle_subscription_help(callback_query: types.CallbackQuery):
    """Отображает подробную справку о менеджере подписок."""
    await cmd_subscription_help(callback_query.message)  # Вызываем cmd_subscription_help для отображения справки





@dp.message()
async def handle_message(message: types.Message, state: FSMContext):  # Добавляем state
    """Обрабатывает сообщения, не являющиеся командами."""
    chat_id = message.chat.id
    await check_cache(chat_id, message)

    # Проверяем, не находится ли бот в состоянии ожидания данных для подписки
    current_state = await state.get_state()
    if current_state is not None:
        # Если бот в состоянии FSM, обрабатываем сообщение в соответствии с текущим состоянием
        if current_state == SearchStates.WAITING_FOR_QUERY:
            await process_search_query(message, state)
        elif current_state == subscription_states.WAITING_FOR_QUERY: 
            await subscription_fsm.process_query(message, state)
        elif current_state == subscription_states.WAITING_FOR_THRESHOLD:
            await subscription_fsm.process_threshold(message, state)
        elif current_state == subscription_states.WAITING_FOR_NEW_TEXT:
            await subscription_fsm.process_new_text(message, state)
        elif current_state == subscription_states.WAITING_FOR_NEW_THRESHOLD:
            await subscription_fsm.process_new_threshold(message, state)
        elif current_state == feedback_states.WAITING_FOR_FEEDBACK:
            await process_feedback(message, state)
        elif current_state == CurrencyStates.WAITING_FOR_DATE:
            await process_historical_currency(message, state)
        return  # Не обрабатываем сообщение, если бот в состоянии FSM

    # Проверяем тип сообщения
    if message.content_type == 'text':
        # Обрабатываем текстовое сообщение
        if message.text.startswith('/'):
            command = message.text.split()[0]
            db_manager.log_user_action(message.from_user.id, "unknown_command", message.text)
            await message.reply(
                f"Извини, я не знаю такой команды <code>{command}</code>. Попробуй ещё раз.",
                parse_mode='HTML'
            )
        else:
            db_manager.log_user_action(message.from_user.id, "message", message.text)
            # Вызов LLM для обработки текста, не являющегося командой
            llm_response = await llm_helper.process_user_input(message.text)

            # Обработка ответа LLM
            if llm_response is not None:
                # Проверяем, является ли ответ вызовом функции или текстом
                if isinstance(llm_response, dict) and "name" in llm_response:
                    await process_llm_response(message, llm_response, state)
                else:
                    # Ответ - это просто текст
                    await message.reply(llm_response)
            # else:
            # ... (обработка случая, когда LLM вернул None) ..
    else:
        # Обрабатываем другие типы сообщений
        content_type = message.content_type
        db_manager.log_user_action(message.from_user.id, content_type)


async def process_llm_response(message, llm_response, state: FSMContext):
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
    elif function_name == "feedback":
        await cmd_feedback( message, state )
    elif function_name == "subscriptions":
        await cmd_subscriptions( message )
    elif function_name == "my_subscriptions":
        await subscription_fsm.cmd_mysubscriptions( message, state )
    elif function_name == "subscription_help":
        await cmd_subscription_help( message )
    elif function_name == "create_subscription":
        await subscription_fsm.cmd_newsubscription( message, state )
    elif function_name == "update_subscription":
        await subscription_fsm.cmd_updatesubscription( message, state )
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
    manager.scheduler.start()

    # Затем начинаем поллинг
    asyncio.create_task(dp.start_polling(bot)) 

    # Создание конфигурации сервера uvicorn
    config = uvicorn.Config(app, host=settings["fastapi_host"], port=settings["fastapi_port"], log_level="info")
    server = uvicorn.Server(config)

    # Запуск сервера в отдельной задаче asyncio
    await server.serve()

if __name__ == "__main__":
    asyncio.run(main())