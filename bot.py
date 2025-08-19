import telebot
import random
import time
import json
import os
import threading
import schedule
import requests
import datetime

# Загружаем токены из переменных окружения
TOKEN = "8367662884:AAF2Q8v19wGyPI4wxVeLx-liUrby6grHmHQ"
TENOR_API_KEY = "AIzaSyDTE8VLCHXtqsZksOmXMC9z4Lri9FnpYRA"

bot = telebot.TeleBot(TOKEN)

# Файлы для хранения данных
USERS_FILE = 'users.json'
LAST_CHOICE_FILE = 'last_choice.json'
STATS_FILE = 'stats.json'
LAST_AGR_FILE = 'last_agr.json'
USED_ROASTS_FILE = 'used_roasts.json'
LAST_MEM_FILE = 'last_mem.json'  # Файл для хранения времени последнего мема

# Функции для работы с файлами
def load_data(file_name, default):
    if os.path.exists(file_name):
        with open(file_name, 'r') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return default
    return default

def save_data(file_name, data):
    with open(file_name, 'w') as f:
        json.dump(data, f, indent=2)

# Загружаем данные
users = load_data(USERS_FILE, {})
last_choice = load_data(LAST_CHOICE_FILE, {})
stats = load_data(STATS_FILE, {})
last_agr = load_data(LAST_AGR_FILE, {})
used_roasts = load_data(USED_ROASTS_FILE, {})
last_mem = load_data(LAST_MEM_FILE, {})  # Загружаем время последнего мема

# Фразы для roast (agr) - обновленные
roast_phrases = [
    "{name}, ты словно баг в продакшене — все тебя видят, но никто не хочет чинить.",
    "{name}, твои победы такие же редкие, как Wi-Fi в деревне.",
    "{name}, если бы тупость светилась, ты был бы городом-миллионником.",
    "{name}, ты как update Windows — всегда не вовремя и никому не нужен.",
    "{name}, когда мозги раздавали, ты в очереди за мемами стоял.",
    "{name}, с тобой скучно даже котам.",
    "{name}, ты словно финал Игры Престолов — все ждали большего, а получили тебя.",
    "{name}, ты как неудачный эксперимент с питоном — без конца падаешь!",
    "{name}, с твоим интеллектом и код не компилируется.",
    "{name}, ты как терабайт на флешке — всё поместилось, но ничего не работает.",
    "{name}, даже вирусы обходят твою голову стороной.",
    "{name}, ты как старый компьютер — постоянно зависаешь и тормозишь.",
    "{name}, если бы твоё лицо было багом, ты был бы баг-трекером.",
    "{name}, у тебя на лице даже спамные сообщения не остаются."
    # и так далее до 100...
]

# Функция для отправки мема через Tenor API
def send_mem(chat_id):
    current_time = time.time()
    
    # Проверка, был ли мем отправлен недавно
    if chat_id in last_mem and current_time - last_mem[chat_id] < 86400:
        remaining = int(86400 - (current_time - last_mem[chat_id]))
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60
        return  # Если мем уже отправлен, ничего не делать
    
    # Получение мема через Tenor API
    response = requests.get(f'https://api.tenor.com/v1/search?q=funny&key={TENOR_API_KEY}&limit=1')
    data = response.json()
    
    if 'results' in data:
        meme_url = data['results'][0]['media'][0]['gif']['url']
        bot.send_message(chat_id, f"Вот твой мем: {meme_url}")
    
    # Сохраняем время отправки мема
    last_mem[chat_id] = current_time
    save_data(LAST_MEM_FILE, last_mem)

# Случайное время для отправки мема
def schedule_random_mem():
    schedule.clear('daily_mem')
    mem_hour = random.randint(6, 23)  # Случайный час в интервале от 6 до 23
    mem_minute = random.randint(0, 59)  # Случайная минута
    schedule.every().day.at(f"{mem_hour:02d}:{mem_minute:02d}").do(send_mem_to_all).tag('daily_mem')

# Обновляем расписание раз в сутки
schedule_random_mem()

# Обновляем расписание мема раз в сутки
schedule.every().day.at("05:55").do(schedule_random_mem)

# Функция для отправки мема всем участникам
def send_mem_to_all():
    # Получаем все чаты, в которые нужно отправить мемы (например, все чаты с ботом)
    for chat_id in last_mem.keys():
        send_mem(chat_id)

# Функция для отправки ежедневного агра случайному участнику
def send_daily_agr():
    for chat_id in users.keys():
        current_time = time.time()

        # Проверяем, был ли агр недавно
        if chat_id in last_agr and current_time - last_agr[chat_id] < 86400:
            remaining = int(86400 - (current_time - last_agr[chat_id]))
            hours = remaining // 3600
            minutes = (remaining % 3600) // 60
            continue

        if chat_id not in users or len(users[chat_id]) == 0:
            continue

        # Автор команды
        author_id = random.choice(users[chat_id])['id']
        author = f"User_{author_id}"

        # Цель агра (рандомный участник)
        target = random.choice(users[chat_id])
        target_name = target['name']

        # Выбираем неповторяющуюся фразу
        if chat_id not in used_roasts:
            used_roasts[chat_id] = []

        available_roasts = [r for r in roast_phrases if r not in used_roasts[chat_id]]
        if not available_roasts:
            used_roasts[chat_id] = []  # Сбрасываем использованные фразы
            available_roasts = roast_phrases.copy()

        phrase = random.choice(available_roasts)
        used_roasts[chat_id].append(phrase)
        save_data(USED_ROASTS_FILE, used_roasts)

        # Отправка агра
        phrase = phrase.replace("{name}", f"@{target_name}")
        response = f"🔥 @{author} запускает агр!\n{phrase}"
        bot.send_message(chat_id, response)

        last_agr[chat_id] = current_time
        save_data(LAST_AGR_FILE, last_agr)

# Случайное время для запуска агра
def schedule_random_agr():
    schedule.clear('daily_agr')
    agr_hour = random.randint(6, 23)
    agr_minute = random.randint(0, 59)
    schedule.every().day.at(f"{agr_hour:02d}:{agr_minute:02d}").do(send_daily_agr).tag('daily_agr')

# Обновляем расписание раз в сутки
schedule_random_agr()
schedule.every().day.at("05:55").do(schedule_random_agr)

def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(30)

threading.Thread(target=run_scheduler, daemon=True).start()

# Обработчик команд
@bot.message_handler(commands=['start', 'test', 'list', 'choose', 'stats', 'register', 'agr', 'monetka'])
def handle_commands(message):
    chat_id = str(message.chat.id)
    command = message.text.split()[0].split('@')[0].lower()

    if command in ['/start', '/test']:
        bot.reply_to(message, "Бот работает, хвала Аннубису! 😊")

    elif command == '/list':
        if chat_id not in users or not users[chat_id]:
            bot.reply_to(message, "Нет зарегистрированных участников. Используйте /register, ебантяи!")
        else:
            names = [u['name'] for u in users[chat_id]]
            bot.reply_to(message, f"Участники: {', '.join(names)}")

    elif command == '/choose':
        if chat_id not in users or len(users[chat_id]) < 2:
            bot.reply_to(message, f"Нужно минимум 2 участника! Сейчас: {len(users.get(chat_id, []))}")
            return

        current_time = time.time()
        if chat_id in last_choice and current_time - last_choice[chat_id] < 86400:
            remaining = int(86400 - (current_time - last_choice[chat_id]))
            hours = remaining // 3600
            minutes = (remaining % 3600) // 60
            bot.reply_to(message, f"Ещё рано! Подождите {hours} ч {minutes} мин.")
            return

        bot.reply_to(message, "Ожидайте, сейчас всё выберу, ёпта!")
        time.sleep(1)  # Задержка в 1 секунду

        participants = users[chat_id]
        handsome = random.choice(participants)
        not_handsome = random.choice(participants)
        while not_handsome['id'] == handsome['id']:
            not_handsome = random.choice(participants)

        # Отправляем результат после задержки
        bot.reply_to(message, f"Красавчик дня: @{handsome['name']}")
        time.sleep(1)
        bot.reply_to(message, f"Пидор дня: @{not_handsome['name']}")

        last_choice[chat_id] = current_time
        save_data(LAST_CHOICE_FILE, last_choice)

    elif command == '/stats':
        if chat_id not in stats or not stats[chat_id]:
            bot.reply_to(message, "Статистика пуста. Используйте /choose!")
            return

        sorted_stats = sorted(stats[chat_id].items(), key=lambda x: x[1]['wins'], reverse=True)
        response = "📊 Статистика:\n"
        for _, data in sorted_stats:
            total = data['wins'] + data['losses']
            win_rate = (data['wins'] / total * 100) if total > 0 else 0
            loss_rate = (data['losses'] / total * 100) if total > 0 else 0
            response += f"@{data['name']}: Красавчик - {data['wins']}, Пидор - {data['losses']}\n"
            response += f"➡ Красавчик {win_rate:.1f}% | Пидор {loss_rate:.1f}%\n\n"
        bot.reply_to(message, response)

    elif command == '/register':
        user_id = message.from_user.id
        username = message.from_user.username or message.from_user.first_name or f"User_{user_id}"
        if chat_id not in users:
            users[chat_id] = []
        if user_id not in [u['id'] for u in users[chat_id]]:
            users[chat_id].append({'id': user_id, 'name': username})
            save_data(USERS_FILE, users)
            bot.reply_to(message, f"Вы зарегистрированы! @{username}")
        else:
            bot.reply_to(message, f"Вы уже зарегистрированы, долбаёб! @{username}")

    elif command == '/monetka':
        result = random.choice(["Орёл", "Решка"])
        bot.reply_to(message, f"Монетка показала: {result}")

print("Бот запущен!")
bot.polling(none_stop=True)
