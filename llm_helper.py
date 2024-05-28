from groq import Groq
import json

# Импортируем модуль logging
import logging
root_logger = logging.getLogger("bot")
# Создаем дочерний логгер с именем scaner.tv
logger = logging.getLogger("bot.llm")
logger.propagate = True
# Устанавливаем уровень логирования для дочернего логгера
logger.setLevel(logging.DEBUG)

class LLMHelper:
    def __init__(self, api_key, model, bot_description):
        self.client = Groq(api_key=api_key)
        self.model = model
        self.bot_description = bot_description
        self.tools = [
            {
                "type": "function",
                "function": {
                    "name": "search_information",
                    "description": "Ищет информацию об в Телеграм чатах по Аргентине.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Текст поискового запроса.",
                            },
                            # ... (другие параметры) ...
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "about_bot",
                    "description": "Описание бота, что умеет, как пользоваться,кие есть команды и т.п.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Текст поискового запроса.",
                            },
                            # ... (другие параметры) ...
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "currency",
                    "description": "Сводка текущих курсах валют",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Текст поискового запроса.",
                            },
                            # ... (другие параметры) ...
                        },
                        "required": ["query"],
                    },
                },
            },
            # ... (другие функции) ...
        ]

    async def process_user_input(self, message_text):
        try:
            messages=[
                {"role": "system", "content": self.bot_description},
                {"role": "user", "content": message_text},
            ]

            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=self.tools,
                tool_choice="auto", # Модель сама решает, вызывать ли функцию
                max_tokens=4096  # Ограничение количества токенов в ответе
            )

            response_message = response.choices[0].message

            # Проверяем, был ли сделан вызов функции
            tool_calls = response_message.tool_calls
            if tool_calls:
                # Вызываем функцию и получаем результат
                function_response = await self.call_function(tool_calls[0], messages)
                # Отправляем результат функции обратно в модель для формирования окончательного ответа
                # messages.append(function_response)
                # second_response = self.client.chat.completions.create(
                #     model=self.model,
                #     messages=messages,
                # )
                # return second_response.choices[0].message.content
                return function_response
            else:
                return response_message.content

        except Exception as e:
            logger.error(f"Ошибка при вызове LLM: {e}")
            return None

    async def call_function(self, tool_call, messages):
        function_name = tool_call.function.name
        function_args = json.loads(tool_call.function.arguments)
        
        # Вызываем соответствующую функцию бота 
        if function_name == "search_information":
            query = function_args.get("query")
            # ... (код для вызова функции поиска и получения результата)
            results = "Здесь будет результат поиска" # Замените на реальный результат
            return {
                "tool_call_id": tool_call.id,
                "role": "tool",
                "name": function_name,
                "content": query, 
            }
        # ... (обработка других функций) ...

        # Если функция не найдена
        return {
            "tool_call_id": tool_call.id,
            "role": "tool",
            "name": function_name,
            "content": f"Ошибка: функция '{function_name}' не найдена.", 
        }