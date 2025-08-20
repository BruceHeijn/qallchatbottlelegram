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
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from flask import Flask, request

# Инициализация Flask для вебхуков
app = Flask(__name__)

# Загружаем токены из переменных окружения
BOT_TOKEN = os.getenv("TOKEN")
TENOR_API_KEY = os.getenv("TENOR_API_KEY")
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
RAILWAY_PUBLIC_DOMAIN = os.getenv("RAILWAY_PUBLIC_DOMAIN")

# Проверка переменных окружения
print(f"BOT_TOKEN: {'Set' if BOT_TOKEN else 'Not set'}")
print(f"TENOR_API_KEY: {'Set' if TENOR_API_KEY else 'Not set'}")
print(f"GOOGLE_CREDENTIALS: {GOOGLE_CREDENTIALS[:50] if GOOGLE_CREDENTIALS else 'Not set'}...")
print(f"SPREADSHEET_ID: {SPREADSHEET_ID if SPREADSHEET_ID else 'Not set'}")
print(f"RAILWAY_PUBLIC_DOMAIN: {RAILWAY_PUBLIC_DOMAIN if RAILWAY_PUBLIC_DOMAIN else 'Not set'}")

# Проверка, что все переменные заданы
if not all([BOT_TOKEN, TENOR_API_KEY, GOOGLE_CREDENTIALS, SPREADSHEET_ID]):
    print("Ошибка: Одна или несколько переменных окружения не заданы")
    exit(1)

bot = telebot.TeleBot(BOT_TOKEN)

# Настройки Google Sheets
STATS_SHEET_NAME = "Sheet1"
USERS_SHEET_NAME = "Users"
LAST_CHOICE_SHEET_NAME = "LastChoice"

# Глобальные переменные
sheets = {"stats": None, "users": None, "last_choice": None}
users = {}
last_choice = {}
stats_cache = []

# Проверка существования таблицы
def check_spreadsheet_exists(creds):
    try:
        print(f"Проверка существования таблицы: {SPREADSHEET_ID}")
        service = build("sheets", "v4", credentials=creds)
        response = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
        print(f"Таблица {SPREADSHEET_ID} существует: {response['properties']['title']}")
        return True
    except HttpError as e:
        error_details = json.loads(e.content.decode()) if e.content else {}
        print(f"Ошибка проверки таблицы {SPREADSHEET_ID}: {str(e)}, детали: {error_details}")
        return False
    except Exception as e:
        print(f"Неожиданная ошибка при проверке таблицы {SPREADSHEET_ID}: {str(e)}")
        return False

# Создание новой таблицы
def create_new_spreadsheet(creds):
    try:
        print("Попытка создания новой таблицы")
        service = build("sheets", "v4", credentials=creds)
        spreadsheet = {
            "properties": {"title": f"BotStats_{int(time.time())}"}
        }
        response = service.spreadsheets().create(body=spreadsheet).execute()
        new_spreadsheet_id = response["spreadsheetId"]
        print(f"Создана новая таблица: {new_spreadsheet_id}")
        return new_spreadsheet_id
    except Exception as e:
        print(f"Ошибка создания новой таблицы: {str(e)}")
        return None

# Инициализация Google Sheets
def init_sheets():
    try:
        print("Попытка парсинга GOOGLE_CREDENTIALS")
        creds_dict = json.loads(GOOGLE_CREDENTIALS)
        print("GOOGLE_CREDENTIALS успешно распарсен")
        creds = Credentials.from_service_account_info(
            creds_dict,
            scopes=[
                "https://spreadsheets.google.com/feeds",
                "https://www.googleapis.com/auth/drive",
                "https://www.googleapis.com/auth/spreadsheets",
            ],
        )
        print("Попытка авторизации Google Sheets")
        client = gspread.authorize(creds)
        print("Google Sheets авторизация успешна")

        # Проверка существования таблицы
        if not check_spreadsheet_exists(creds):
            print(f"Таблица {SPREADSHEET_ID} недоступна или не существует")
            return None

        print(f"Попытка открытия таблицы: {SPREADSHEET_ID}")
        workbook = client.open_by_key(SPREADSHEET_ID)
        print(f"Таблица открыта: {SPREADSHEET_ID}")

        # Проверяем/создаём листы
        try:
            stats_sheet = workbook.worksheet(STATS_SHEET_NAME)
            print(f"Лист {STATS_SHEET_NAME} найден")
        except gspread.exceptions.WorksheetNotFound:
            stats_sheet = workbook.add_worksheet(title=STATS_SHEET_NAME, rows=100, cols=10)
            print(f"Создан лист: {STATS_SHEET_NAME}")
        try:
            users_sheet = workbook.worksheet(USERS_SHEET_NAME)
            print(f"Лист {USERS_SHEET_NAME} найден")
        except gspread.exceptions.WorksheetNotFound:
            users_sheet = workbook.add_worksheet(title=USERS_SHEET_NAME, rows=100, cols=10)
            print(f"Создан лист: {USERS_SHEET_NAME}")
        try:
            last_choice_sheet = workbook.worksheet(LAST_CHOICE_SHEET_NAME)
            print(f"Лист {LAST_CHOICE_SHEET_NAME} найден")
        except gspread.exceptions.WorksheetNotFound:
            last_choice_sheet = workbook.add_worksheet(title=LAST_CHOICE_SHEET_NAME, rows=100, cols=10)
            print(f"Создан лист: {LAST_CHOICE_SHEET_NAME}")

        # Проверяем/создаем заголовки
        if not stats_sheet.get("A1:D1"):
            stats_sheet.append_row(["Дата", "User ID", "Username", "Статус"])
            print("Заголовки добавлены в Sheet1")
        if not users_sheet.get("A1:C1"):
            users_sheet.append_row(["Chat ID", "User ID", "Username"])
            print("Заголовки добавлены в Users")
        if not last_choice_sheet.get("A1:B1"):
            last_choice_sheet.append_row(["Chat ID", "Timestamp"])
            print("Заголовки добавлены в LastChoice")

        print("Google Sheets успешно инициализирован")
        return {
            "stats": stats_sheet,
            "users": users_sheet,
            "last_choice": last_choice_sheet
        }
    except Exception as e:
        print(f"Ошибка инициализации Google Sheets: {str(e)}")
        return None

# Периодическое переподключение к Google Sheets
def reconnect_sheets():
    global sheets
    if not all(sheets.values()):
        print("Попытка переподключения к Google Sheets")
        new_sheets = init_sheets()
        if new_sheets:
            sheets = new_sheets
            sync_stats_to_sheets()
            load_users()
            load_last_choice()
            print("Переподключение успешно, данные синхронизированы")

# Загрузка данных из Google Sheets
def load_users():
    global users
    if not sheets["users"]:
        print("Google Sheets недоступен, использую локальный кэш пользователей")
        return users
    try:
        data = sheets["users"].get_all_values()[1:]
        users = {}
        for row in data:
            try:
                chat_id = row[0]
                user_id = int(row[1])
                username = row[2]
                if chat_id not in users:
                    users[chat_id] = []
                users[chat_id].append({"id": user_id, "name": username})
            except (IndexError, ValueError) as e:
                print(f"Ошибка обработки строки пользователей: {row}, ошибка: {e}")
        print("Пользователи загружены из Google Sheets")
    except Exception as e:
        print(f"Ошибка загрузки пользователей: {e}")
    return users

def load_last_choice():
    global last_choice
    if not sheets["last_choice"]:
        print("Google Sheets недоступен, использую локальный кэш LastChoice")
        return last_choice
    try:
        data = sheets["last_choice"].get_all_values()[1:]
        last_choice = {}
        for row in data:
            try:
                chat_id = row[0]
                timestamp = float(row[1])
                last_choice[chat_id] = timestamp
            except (IndexError, ValueError):
                continue
        print("LastChoice загружен из Google Sheets")
    except Exception as e:
        print(f"Ошибка загрузки LastChoice: {e}")
    return last_choice

# Сохранение данных в Google Sheets
def save_users():
    if not sheets["users"]:
        print("Google Sheets недоступен, пользователи сохранены в локальном кэше")
        return
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
    if not sheets["last_choice"]:
        print("Google Sheets недоступен, LastChoice сохранён в локальном кэше")
        return
    try:
        sheets["last_choice"].delete_rows(2, sheets["last_choice"].row_count)
        rows = [[chat_id, str(timestamp)] for chat_id, timestamp in last_choice.items()]
        if rows:
            sheets["last_choice"].append_rows(rows)
        print("LastChoice сохранён в Google Sheets")
    except Exception as e:
        print(f"Ошибка сохранения LastChoice: {e}")

# Синхронизация локального кэша статистики с Google Sheets
def sync_stats_to_sheets():
    global stats_cache
    if not sheets["stats"] or not stats_cache:
        return
    try:
        for entry in stats_cache:
            sheets["stats"].append_row(entry)
        print(f"Синхронизировано {len(stats_cache)} записей статистики в Google Sheets")
        stats_cache = []
    except Exception as e:
        print(f"Ошибка синхронизации статистики: {e}")

# Инициализация Google Sheets
sheets = init_sheets()
if not sheets:
    print("Предупреждение: Google Sheets недоступен, бот будет работать с локальным кэшем")
    sheets = {"stats": None, "users": None, "last_choice": None}

users = load_users()
last_choice = load_last_choice()

# Фоновое переподключение к Google Sheets
schedule.every(5).minutes.do(reconnect_sheets)

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
@bot.message_handler(commands=["start", "test", "list", "choose", "stats", "register", "agr", "monetka", "createsheet"])
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

        # Записываем в Google Таблицы или кэш
        current_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if sheets["stats"]:
            try:
                sheets["stats"].append_row(
                    [current_date, str(handsome["id"]), "@" + handsome["name"], "Красавчик"]
                )
                sheets["stats"].append_row(
                    [current_date, str(not_handsome["id"]), "@" + not_handsome["name"], "Пидор"]
                )
                print(f"Записано в Google Sheets: Красавчик @{handsome['name']}, Пидор @{not_handsome['name']}")
            except Exception as e:
                print(f"Ошибка записи в Google Sheets: {str(e)}")
                stats_cache.append([current_date, str(handsome["id"]), "@" + handsome["name"], "Красавчик"])
                stats_cache.append([current_date, str(not_handsome["id"]), "@" + not_handsome["name"], "Пидор"])
                bot.reply_to(message, "Ошибка записи в Google Sheets, данные сохранены в локальном кэше")
        else:
            stats_cache.append([current_date, str(handsome["id"]), "@" + handsome["name"], "Красавчик"])
            stats_cache.append([current_date, str(not_handsome["id"]), "@" + not_handsome["name"], "Пидор"])
            print(f"Google Sheets недоступен, данные сохранены в локальном кэше: Красавчик @{handsome['name']}, Пидор @{not_handsome['name']}")

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
            if not stats_cache:
                bot.reply_to(message, "Статистика пуста. Используйте /choose!")
                return
            data = stats_cache
            print("Google Sheets недоступен, использую локальный кэш для статистики")
        else:
            try:
                data = sheets["stats"].get_all_values()[1:]
                if not data and not stats_cache:
                    bot.reply_to(message, "Статистика пуста. Используйте /choose!")
                    return
                data = data + stats_cache
            except Exception as e:
                print(f"Ошибка чтения Google Sheets: {str(e)}")
                if not stats_cache:
                    bot.reply_to(message, "Ошибка: не удалось подключиться к Google Таблицам и нет локального кэша.")
                    return
                data = stats_cache
                print("Google Sheets недоступен, использую локальный кэш для статистики")

        try:
            stats = {}
            for row in data:
                try:
                    user_id, username, status = row[1], row[2], row[3]
                    if user_id not in stats:
                        stats[user_id] = {"name": username, "wins": 0, "losses": 0}
                    if status == "Красавчик":
                        stats[user_id]["wins"] += 1
                    elif status == "Пидор":
                        stats[user_id]["losses"] += 1
                except IndexError:
                    print(f"Ошибка обработки строки статистики: {row}")
                    continue

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
            print(f"Ошибка формирования статистики: {e}")

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

    elif command == "/createsheet":
        try:
            creds_dict = json.loads(GOOGLE_CREDENTIALS)
            creds = Credentials.from_service_account_info(
                creds_dict,
                scopes=[
                    "https://spreadsheets.google.com/feeds",
                    "https://www.googleapis.com/auth/drive",
                    "https://www.googleapis.com/auth/spreadsheets",
                ],
            )
            new_spreadsheet_id = create_new_spreadsheet(creds)
            if new_spreadsheet_id:
                bot.reply_to(message, f"Создана новая таблица: {new_spreadsheet_id}. Обновите SPREADSHEET_ID в настройках!")
                print(f"Создана новая таблица: {new_spreadsheet_id}")
            else:
                bot.reply_to(message, "Ошибка создания таблицы. Проверьте настройки Google API.")
        except Exception as e:
            bot.reply_to(message, f"Ошибка создания таблицы: {str(e)}")
            print(f"Ошибка создания таблицы: {str(e)}")

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
    if not RAILWAY_PUBLIC_DOMAIN:
        print("RAILWAY_PUBLIC_DOMAIN не задан, переключаюсь на polling")
        return False
    try:
        bot.remove_webhook()
        time.sleep(0.1)
        webhook_url = f"https://{RAILWAY_PUBLIC_DOMAIN}/{BOT_TOKEN}"
        print(f"Попытка установки вебхука: {webhook_url}")
        bot.set_webhook(url=webhook_url)
        print(f"Вебхук установлен: {webhook_url}")
        return True
    except Exception as e:
        print(f"Ошибка установки вебхука: {e}")
        return False

# Запуск бота
if __name__ == "__main__":
    print("Бот запускается...")
    webhook_success = set_webhook()
    if webhook_success:
        app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
    else:
        print("Вебхук не установлен, использую polling")
        bot.infinity_polling()

