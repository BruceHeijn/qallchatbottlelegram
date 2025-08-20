import telebot
import random
import time
import json
import os
import threading
import schedule
import requests
import datetime
import gspread
from google.oauth2.service_account import Credentials
from flask import Flask, request

# Инициализация Flask для вебхуков
app = Flask(__name__)

# Загружаем токены из переменных окружения
BOT_TOKEN = os.getenv("TOKEN")  # Исправлено с TOKEN
TENOR_API_KEY = os.getenv("TENOR_API_KEY")
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")  # Исправлено с хардкода

# Проверка переменных окружения
print(f"BOT_TOKEN: {'Set' if BOT_TOKEN else 'Not set'}")
print(f"TENOR_API_KEY: {'Set' if TENOR_API_KEY else 'Not set'}")
print(f"GOOGLE_CREDENTIALS: {GOOGLE_CREDENTIALS[:50] if GOOGLE_CREDENTIALS else 'Not set'}...")
print(f"SPREADSHEET_ID: {SPREADSHEET_ID if SPREADSHEET_ID else 'Not set'}")

# Проверка, что все переменные заданы
if not all([BOT_TOKEN, TENOR_API_KEY, GOOGLE_CREDENTIALS, SPREADSHEET_ID]):
    print("Ошибка: Одна или несколько переменных окружения не заданы")
    exit(1)

bot = telebot.TeleBot(BOT_TOKEN)

# Настройки Google Sheets
STATS_SHEET_NAME = "Sheet1"  # Для статистики
USERS_SHEET_NAME = "Users"  # Для пользователей
LAST_CHOICE_SHEET_NAME = "LastChoice"  # Для последнего выбора

# Инициализация Google Sheets
def init_sheets():
    try:
        creds_dict = json.loads(GOOGLE_CREDENTIALS)
        creds = Credentials.from_service_account_info(
            creds_dict,
            scopes=[
                "https://spreadsheets.google.com/feeds",
                "https://www.googleapis.com/auth/drive",
            ],
        )
        client = gspread.authorize(creds)
        workbook = client.open_by_key(SPREADSHEET_ID)

        stats_sheet = workbook.worksheet(STATS_SHEET_NAME)
        users_sheet = workbook.worksheet(USERS_SHEET_NAME)
        last_choice_sheet = workbook.worksheet(LAST_CHOICE_SHEET_NAME)

        # Проверяем/создаем заголовки
        if not stats_sheet.get("A1:D1"):
            stats_sheet.append_row(["Дата", "User ID", "Username", "Статус"])
        if not users_sheet.get("A1:C1"):
            users_sheet.append_row(["Chat ID", "User ID", "Username"])
        if not last_choice_sheet.get("A1:B1"):
            last_choice_sheet.append_row(["Chat ID", "Timestamp"])

        print("Google Sheets успешно инициализирован")
        return {
            "stats": stats_sheet,
            "users": users_sheet,
            "last_choice": last_choice_sheet
        }
    except Exception as e:
        print(f"Ошибка инициализации Google Sheets: {e}")
        return None

sheets = init_sheets()
if not sheets:
    print("Критическая ошибка: Не удалось подключиться к Google Sheets. Бот не запустится.")
    exit(1)

# Загрузка данных из Google Sheets
def load_users():
    users = {}
    try:
        data = sheets["users"].get_all_values()[1:]  # Пропускаем заголовок
        for row in data:
            chat_id = row[0]
            user_id = int(row[1])
            username = row[2]
            if chat_id not in users:
                users[chat_id] = []
            users[chat_id].append({"id": user_id, "name": username})
        print("Пользователи загружены из Google Sheets")
    except Exception as e:
        print(f"Ошибка загрузки пользователей: {e}")
    return users

def load_last_choice():
    last_choice = {}
    try:
        data = sheets["last_choice"].get_all_values()[1:]  # Пропускаем заголовок
        for row in data:
            chat_id = row[0]
            try:
                timestamp = float(row[1])
                last_choice[chat_id] = timestamp
            except ValueError:
                continue
        print("LastChoice загружен из Google Sheets")
    except Exception as e:
        print(f"Ошибка загрузки LastChoice: {e}")
    return last_choice

users = load_users()
last_choice = load_last_choice()

# Сохранение данных в Google Sheets
def save_users():
    try:
        sheets["users"].delete_rows(2, sheets["users"].row_count)
        rows = []
        for chat_id, user_list in users.items():
            for user in user_list:
                rows.append([chat_id, str(user["id"]), user["name"]])
        if rows:
            sheets["users"].append_rows(rows)
        print("Пользователи сохранены в Google Sheets")
    except Exception as e:
        print(f"Ошибка сохранения пользователей: {e}")

def save_last_choice():
    try:
        sheets["last_choice"].delete_rows(2, sheets["last_choice"].row_count)
        rows = [[chat_id, str(timestamp)] for chat_id, timestamp in last_choice.items()]
        if rows:
            sheets["last_choice"].append_rows(rows)
        print("LastChoice сохранён в Google Sheets")
    except Exception as e:
        print(f"Ошибка сохранения LastChoice: {e}")

# Фразы для roast (agr)
roast_phrases = [
    "{name}, ты словно баг в продакшене — все тебя видят, но никто не хочет чинить.",
    "{name}, твои победы такие же редкие, как Wi-Fi в деревне.",
    "{name}, если бы тупость светилась, ты был бы городом-миллионником.",
    "{name}, ты как update Windows — всегда не вовремя и никому не нужен.",
    "{name}, когда мозги раздавали, ты в очереди за мемами стоял.",
    "{name}, с тобой скучно даже котам.",
    "{name}, ты словно финал Игры Престолов — все ждали большего, а получили тебя.",
]

# Эпичные фразы для choose
epic_phrases = [
    "В великой битве судеб {handsome} восстал, а {not_handsome} пал...",
    "Как сказал бы Гендальф: красавчик сегодня — {handsome}, а в тени остался {not_handsome}.",
    "Судьба бросила кости: {handsome} идёт в легенды, {not_handsome} — в анекдоты.",
    "Даже драконы бы склонили головы перед {handsome}, но над {not_handsome} смеялись бы гномы.",
    "В этот день мир узнал героя — {handsome}. И узнал, кого винить — {not_handsome}.",
    "ЖТ всегда хотел бабу, но увы. Герой дня - {handsome}. А пидор, как зачаствую бывает - {not_handsome}.",
]

# Монетка
coin_sides = [
    "Орёл",
    "Решка",
    "Монета встала на ребро, оба получите в ебло!",
    "Монета улетела и не вернулась, твоя попа распархнулась 🪙",
]

# Функция для отправки случайного мема
def send_daily_meme():
    for chat_id in users.keys():
        try:
            url = f"https://tenor.googleapis.com/v2/search?q=funny&key={TENOR_API_KEY}&limit=20"
            r = requests.get(url)
            if r.status_code == 200:
                data = r.json()
                if "results" in data and len(data["results"]) > 0:
                    gif_url = random.choice(data["results"])["media_formats"]["gif"]["url"]
                    bot.send_animation(chat_id, gif_url, caption="Ваш ежедневный мемчик 🤣")
            else:
                print(f"Ошибка Tenor API: {r.status_code}")
        except Exception as e:
            print(f"Ошибка отправки мема: {e}")

# Функция для отправки roast
def send_daily_roast():
    for chat_id in users.keys():
        if chat_id not in users or not users[chat_id]:
            continue
        try:
            target = random.choice(users[chat_id])
            target_name = target["name"]
            phrase = random.choice(roast_phrases).replace("{name}", f"@{target_name}")
            for participant in users[chat_id]:
                bot.send_message(
                    chat_id, f"🔥 @{participant['name']} запускает агр на @{target_name}!\n{phrase}"
                )
        except Exception as e:
            print(f"Ошибка отправки roast в чат {chat_id}: {e}")

# Случайное время для запуска заданий
def schedule_random_times():
    schedule.clear("daily_tasks")
    meme_hour = random.randint(6, 23)
    meme_minute = random.randint(0, 59)
    roast_hour = random.randint(6, 23)
    roast_minute = random.randint(0, 59)
    schedule.every().day.at(f"{meme_hour:02d}:{meme_minute:02d}").do(send_daily_meme).tag("daily_tasks")
    schedule.every().day.at(f"{roast_hour:02d}:{roast_minute:02d}").do(send_daily_roast).tag("daily_tasks")
    print(f"Запланировано: мемы в {meme_hour:02d}:{meme_minute:02d}, roast в {roast_hour:02d}:{roast_minute:02d}")

# Обновляем расписание раз в сутки
schedule_random_times()
schedule.every().day.at("05:55").do(schedule_random_times)

def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(30)

threading.Thread(target=run_scheduler, daemon=True).start()

# Обработчик команд
@bot.message_handler(commands=["start", "test", "list", "choose", "stats", "register", "agr", "monetka"])
def handle_commands(message):
    chat_id = str(message.chat.id)
    command = message.text.split()[0].split("@")[0].lower()

    if command in ["/start", "/test"]:
        bot.reply_to(message, "Бот работает, хвала Аннубису! 😊")

    elif command == "/list":
        if chat_id not in users or not users[chat_id]:
            bot.reply_to(message, "Нет зарегистрированных участников. Используйте /register, ебантяи!")
        else:
            names = [u["name"] for u in users[chat_id]]
            bot.reply_to(message, f"Участники: {', '.join(names)}")

    elif command == "/choose":
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

        participants = users[chat_id]
        handsome = random.choice(participants)
        not_handsome = random.choice(participants)
        while not_handsome["id"] == handsome["id"]:
            not_handsome = random.choice(participants)

        # Записываем в Google Таблицы
        if sheets["stats"]:
            try:
                current_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                sheets["stats"].append_row(
                    [current_date, str(handsome["id"]), "@" + handsome["name"], "Красавчик"]
                )
                sheets["stats"].append_row(
                    [current_date, str(not_handsome["id"]), "@" + not_handsome["name"], "Пидор"]
                )
                print(f"Записано в Google Sheets: Красавчик @{handsome['name']}, Пидор @{not_handsome['name']}")
            except Exception as e:
                bot.reply_to(message, f"Ошибка при сохранении в таблицу: {str(e)}")
                print(f"Ошибка записи в Google Sheets: {e}")

        # Фраза для выбора
        phrase = random.choice(epic_phrases).format(
            handsome="@" + handsome["name"], not_handsome="@" + not_handsome["name"]
        )

        # Сообщение с фразой отдельно и потом сообщения для красавчика и пидора
        bot.reply_to(message, phrase)
        bot.reply_to(message, f"🎉 Красавчик дня: @{handsome['name']}")
        bot.reply_to(message, f"👎 Пидор дня: @{not_handsome['name']}")

        last_choice[chat_id] = current_time
        save_last_choice()

    elif command == "/stats":
        if not sheets["stats"]:
            bot.reply_to(message, "Ошибка: не удалось подключиться к Google Таблицам.")
            return

        try:
            # Читаем данные из таблицы (кроме заголовка)
            data = sheets["stats"].get_all_values()[1:]  # Пропускаем заголовок
            if not data:
                bot.reply_to(message, "Статистика пуста. Используйте /choose!")
                return

            # Подсчитываем статистику
            stats = {}
            for row in data:
                user_id, username, status = row[1], row[2], row[3]
                if user_id not in stats:
                    stats[user_id] = {"name": username, "wins": 0, "losses": 0}
                if status == "Красавчик":
                    stats[user_id]["wins"] += 1
                elif status == "Пидор":
                    stats[user_id]["losses"] += 1

            # Формируем ответ
            sorted_stats = sorted(stats.items(), key=lambda x: x[1]["wins"], reverse=True)
            response = "📊 Статистика:\n"
            for _, data in sorted_stats:
                total = data["wins"] + data["losses"]
                win_rate = (data["wins"] / total * 100) if total > 0 else 0
                loss_rate = (data["losses"] / total * 100) if total > 0 else 0
                response += f"{data['name']}: Красавчик - {data['wins']}, Пидор - {data['losses']}\n"
                response += f"➡ Красавчик {win_rate:.1f}% | Пидор {loss_rate:.1f}%\n\n"
            bot.reply_to(message, response)
        except Exception as e:
            bot.reply_to(message, f"Ошибка при чтении статистики: {str(e)}")
            print(f"Ошибка чтения Google Sheets: {e}")

    elif command == "/register":
        user_id = message.from_user.id
        username = message.from_user.username or message.from_user.first_name or f"User_{user_id}"
        if chat_id not in users:
            users[chat_id] = []
        if user_id not in [u["id"] for u in users[chat_id]]:
            users[chat_id].append({"id": user_id, "name": username})
            save_users()
            bot.reply_to(message, f"Вы зарегистрированы! @{username}")
        else:
            bot.reply_to(message, f"Вы уже зарегистрированы, долбаёб! @{username}")

    elif command == "/agr":
        if chat_id not in users or not users[chat_id]:
            bot.reply_to(message, "Нет зарегистрированных участников, сук! Используйте /register.")
            return
        author_id = message.from_user.id
        author = (
            message.from_user.username
            or message.from_user.first_name
            or f"User_{author_id}"
        )
        possible_targets = [u for u in users[chat_id] if u["id"] != author_id]
        if not possible_targets:
            bot.reply_to(message, "Нужно минимум 2 участника, чтобы запускать агр!")
            return
        target = random.choice(possible_targets)
        target_name = target["name"]
        phrase = random.choice(roast_phrases).replace("{name}", f"@{target_name}")
        response = f"🔥 @{author} запускает агр!\n{phrase}"
        bot.reply_to(message, response)

    elif command == "/monetka":
        result = random.choice(coin_sides)
        bot.reply_to(message, f"Монетка показала: {result}")

# Маршрут для вебхуков
@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def get_updates():
    try:
        json_string = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return "OK", 200
    except Exception as e:
        print(f"Ошибка обработки вебхука: {e}")
        return "Error", 500

# Установка вебхука
def set_webhook():
    try:
        bot.remove_webhook()
        time.sleep(0.1)
        webhook_url = f"https://{os.getenv('RAILWAY_PUBLIC_DOMAIN')}/{BOT_TOKEN}"
        bot.set_webhook(url=webhook_url)
        print(f"Вебхук установлен: {webhook_url}")
    except Exception as e:
        print(f"Ошибка установки вебхука: {e}")

if __name__ == "__main__":
    print("Бот запускается...")
    set_webhook()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))

