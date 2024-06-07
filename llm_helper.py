import json, requests

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
        self.api_key = api_key
        self.model = model
        self.bot_description = bot_description
        self.url = 'https://api.groq.com/openai/v1/chat/completions'
        self.headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}'
        }
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
            data = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": self.bot_description},
                    {"role": "user", "content": message_text},
                ],
                "tools": self.tools,
                "tool_choice": "auto",
                "max_tokens": 4096,
            }

            response = requests.post(self.url, headers=self.headers, json=data)
            response.raise_for_status()  # Проверяем на ошибки HTTP

            response_json = response.json()
            response_message = response_json['choices'][0]['message']

            # Проверяем, был ли сделан вызов функции
            tool_calls = response_message.get('tool_calls')
            if tool_calls:
                # Вызываем функцию и получаем результат
                function_response = await self.call_function(tool_calls[0], data['messages'])
                return function_response
            else:
                return response_message.get('content')

        except Exception as e:
            logger.error(f"Ошибка при вызове LLM: {e}")
            return None

    async def call_function(self, tool_call, messages):
        function_name = tool_call['function']['name']
        function_args = json.loads(tool_call['function']['arguments'])

        # Вызываем соответствующую функцию бота 
        if function_name == "search_information":
            query = function_args.get("query")
            # ... (код для вызова функции поиска и получения результата)
            results = "Здесь будет результат поиска" # Замените на реальный результат
            return {
                "tool_call_id": tool_call['id'],
                "role": "tool",
                "name": function_name,
                "content": query,
            }
        # ... (обработка других функций) ...

        # Если функция не найдена
        return {
            "tool_call_id": tool_call['id'],
            "role": "tool",
            "name": function_name,
            "content": f"Ошибка: функция '{function_name}' не найдена.", 
        }