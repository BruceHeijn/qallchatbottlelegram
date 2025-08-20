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
last_choice = {}  # Хранит время последнего /choose для каждого чата
last_agr = {}     # Хранит время последнего /agr для каждого чата
stats_cache = []
register_attempts = {}  # Хранит количество попыток регистрации: {chat_id: {user_id: count}}

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

# Проверка статуса Google Sheets API
def check_sheets_api(creds):
    try:
        service = build("sheets", "v4", credentials=creds)
        service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
        return "Google Sheets API активен, таблица доступна."
    except HttpError as e:
        error_details = json.loads(e.content.decode()) if e.content else {}
        return f"Ошибка Google Sheets API: {str(e)}, детали: {error_details}"
    except Exception as e:
        return f"Неожиданная ошибка проверки API: {str(e)}"

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
        if not last_choice_sheet.get("A1:C1"):
            last_choice_sheet.append_row(["Chat ID", "Choose Timestamp", "Agr Timestamp"])
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
    global last_choice, last_agr
    if not sheets["last_choice"]:
        print("Google Sheets недоступен, использую локальный кэш LastChoice")
        return last_choice, last_agr
    try:
        data = sheets["last_choice"].get_all_values()[1:]
        last_choice = {}
        last_agr = {}
        for row in data:
            try:
                chat_id = row[0]
                choose_timestamp = float(row[1]) if row[1] else 0
                agr_timestamp = float(row[2]) if len(row) > 2 and row[2] else 0
                if choose_timestamp:
                    last_choice[chat_id] = choose_timestamp
                if agr_timestamp:
                    last_agr[chat_id] = agr_timestamp
            except (IndexError, ValueError):
                continue
        print("LastChoice и LastAgr загружены из Google Sheets")
    except Exception as e:
        print(f"Ошибка загрузки LastChoice/LastAgr: {e}")
    return last_choice, last_agr

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
        print("Google Sheets недоступен, LastChoice/LastAgr сохранены в локальном кэше")
        return
    try:
        sheets["last_choice"].delete_rows(2, sheets["last_choice"].row_count)
        rows = []
        for chat_id in set(list(last_choice.keys()) + list(last_agr.keys())):
            choose_time = str(last_choice.get(chat_id, ""))
            agr_time = str(last_agr.get(chat_id, ""))
            rows.append([chat_id, choose_time, agr_time])
        if rows:
            sheets["last_choice"].append_rows(rows)
        print("LastChoice и LastAgr сохранены в Google Sheets")
    except Exception as e:
        print(f"Ошибка сохранения LastChoice/LastAgr: {e}")

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
last_choice, last_agr = load_last_choice()

# Фоновое переподключение к Google Sheets
schedule.every(5).minutes.do(reconnect_sheets)

# Фразы для roast (agr)
roast_phrases = [
    "{name}, ты как Казак без лошади — громкий, но бесполезный.",
    "{name}, твои шутки такие же редкие, как Илюха КЗ на тусовке.",
    "{name}, если бы тупость была валютой, ты был бы богаче Ванечки.",
    "{name}, ты как ЖТ на диете — всё пытаешься, но результат нулевой.",
    "{name}, когда мозги раздавали, ты был в баре с Максиком.",
    "{name}, с тобой скучно даже Венычу на его дне рождения.",
    "{name}, ты как Юрчик на экзамене — всё знаешь, но всё равно провал.",
    "{name}, твой интеллект — как аптечка Медика: вроде есть, а толку нет.",
    "{name}, ты как Васич на вписке — всех раздражаешь, но не уходишь.",
    "{name}, твоя харизма — как Wi-Fi в деревне: никто не ловит сигнал.",
    "{name}, ты как баг в коде Казак: никто не знает, как ты появился.",
    "{name}, твои идеи такие же свежие, как шашлык от Илюхи КЗ через неделю.",
    "{name}, ты как Ванечка в качалке — стараешься, но мышцы не растут.",
    "{name}, ЖТ мечтает о славе, а ты — о том, чтобы просто не облажаться.",
    "{name}, ты как Максик на танцполе — все смотрят, но лучше бы не видели.",
    "{name}, твоя продуктивность — как график Веныча: всегда на нуле.",
    "{name}, ты как Юрчик в споре — говоришь много, а смысла ноль.",
    "{name}, Медик бы прописал тебе таблетку от скуки, но ты и её бы потерял.",
    "{name}, ты как Васич в пабе — орёшь громко, а платят другие.",
    "{name}, твой код жизни — как у Казак: вечный рефакторинг без результата.",
    "{name}, Илюха КЗ бы сказал, что ты — мем, который никто не лайкнул.",
    "{name}, ты как Ванечка в чате — пишешь, но все игнорят.",
    "{name}, ЖТ бы позавидовал твоей способности всё провалить.",
    "{name}, ты как Максик на утро после вечеринки — никто не знает, где ты.",
    "{name}, Веныч бы назвал тебя королём лени, но он сам занят ничем.",
    "{name}, твои планы — как лекции Юрчика: никто их не понимает.",
    "{name}, Медик бы поставил тебе диагноз: хроническая скукота.",
    "{name}, ты как Васич на рыбалке — весь день сидишь, а клёва нет.",
    "{name}, Казак бы сказал, что ты — как степь: пусто и ветрено.",
    "{name}, Илюха КЗ бы снял про тебя мем, но ты даже для этого скучный.",
    "{name}, ты как Ванечка в Доте — всегда в миде, но всегда фейлишь.",
    "{name}, ЖТ бы написал про тебя песню, но она бы называлась 'Эпик Фейл'.",
    "{name}, твоя жизнь — как сторис Максика: никто не досмотрел до конца."
]

# Эпичные фразы для choose
epic_phrases = [
    "{handsome} сияет, как Медик на вызове, а {not_handsome} тонет, как ЖТ в своих фантазиях.",
    "{handsome} — как Казак на коне, а {not_handsome} — как его конь без седла.",
    "Судьба выбрала {handsome}, как Илюха КЗ выбирает пиво, а {not_handsome} — как его пустой кошелёк.",
    "Даже Ванечка бы склонил голову перед {handsome}, но над {not_handsome} он бы просто ржал.",
    "В этот день {handsome} стал легендой, а {not_handsome} — мемом от Юрчика.",
    "Васич бы поставил на {handsome}, а {not_handsome} он бы просто пнул.",
    "{handsome} — как Максик на вечеринке, а {not_handsome} — как его похмелье.",
    "{handsome} взлетел, как Веныч на тусовке, а {not_handsome} упал, как его настроение к утру.",
    "Боги выбрали {handsome}, как Медик выбирает бинты, а {not_handsome} — как его пациенты без страховки.",
    "{handsome} — король чата, как Казак в степи, а {not_handsome} — просто пыль на ветре.",
    "{handsome} сияет, как Илюха КЗ на шашлыках, а {not_handsome} — как угли после дождя.",
    "{handsome} — как Ванечка в мечтах, а {not_handsome} — как его реальность.",
    "ЖТ бы написал балладу о {handsome}, а {not_handsome} попал бы только в припев про лузеров.",
    "{handsome} — как Максик на сцене, а {not_handsome} — как его микрофон, который не работает.",
    "{handsome} — это Веныч на максималках, а {not_handsome} — Веныч на минималках.",
    "Юрчик бы назвал {handsome} гением, а {not_handsome} — его неудавшимся экспериментом.",
    "{handsome} — как Медик в операционной, а {not_handsome} — как его пациент без анестезии.",
    "{handsome} — это Васич с деньгами, а {not_handsome} — Васич с долгами.",
    "{handsome} — как Казак на пиру, а {not_handsome} — как его пустая тарелка.",
    "Илюха КЗ бы снял сторис про {handsome}, а {not_handsome} попал бы только в спам.",
    "{handsome} — как Ванечка в своих снах, а {not_handsome} — как его будильник утром.",
    "{handsome} — это ЖТ на вершине, а {not_handsome} — ЖТ на дне своего плейлиста.",
    "{handsome} — как Максик в топе, а {not_handsome} — как его лаги в игре.",
    "Веныч бы поднял тост за {handsome}, а {not_handsome} он бы просто пролил пиво.",
    "{handsome} — как Юрчик на лекции, а {not_handsome} — как его конспекты, которые никто не читает.",
    "{handsome} — это Медик с диагнозом 'легенда', а {not_handsome} — с диагнозом 'фейл'.",
    "{handsome} — как Васич на тусовке, а {not_handsome} — как его похмельный понедельник.",
    "{handsome} — это Казак в бою, а {not_handsome} — его конь, который сбежал.",
    "Илюха КЗ бы сказал: {handsome} — это пати, а {not_handsome} — это утро после.",
    "{handsome} — как Ванечка на фотке, а {not_handsome} — как его отражение в кривом зеркале.",
    "{handsome} — это ЖТ с хитом, а {not_handsome} — его демо, которое никто не скачал.",
    "{handsome} — как Максик в ударе, а {not_handsome} — как его шутка, которую никто не понял.",
    "{handsome} — это Веныч на чилле, а {not_handsome} — Веныч на стрессе.",
    "{handsome} — как Юрчик с идеей, а {not_handsome} — как его реализация."
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

# Случайное время для запуска мемов
def schedule_random_times():
    schedule.clear("daily_tasks")
    meme_hour = random.randint(6, 23)
    meme_minute = random.randint(0, 59)
    schedule.every().day.at(f"{meme_hour:02d}:{meme_minute:02d}").do(send_daily_meme).tag("daily_tasks")
    print(f"Запланировано: мемы в {meme_hour:02d}:{meme_minute:02d}")

# Обновляем расписание раз в сутки
schedule_random_times()
schedule.every().day.at("05:55").do(schedule_random_times)

def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(30)

threading.Thread(target=run_scheduler, daemon=True).start()

# Обработчик команд
@bot.message_handler(commands=["start", "test", "list", "choose", "stats", "register", "agr", "monetka", "createsheet", "checksheets"])
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
        bot.reply_to(message, f"👑 Красавчик дня: @{handsome['name']}")
        bot.reply_to(message, f"💥 Пидор дня: @{not_handsome['name']}")

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

            # Полная статистика
            response = "📊 Статистика:\n"
            sorted_stats = sorted(stats.items(), key=lambda x: x[1]["wins"], reverse=True)
            for _, data in sorted_stats:
                total = data["wins"] + data["losses"]
                win_rate = (data["wins"] / total * 100) if total > 0 else 0
                loss_rate = (data["losses"] / total * 100) if total > 0 else 0
                response += f"{data['name']}: Красавчик - {data['wins']}, Пидор - {data['losses']}\n"
                response += f"➡ Красавчик {win_rate:.1f}% | Пидор {loss_rate:.1f}%\n\n"

            # Кастомные фразы для топ-3
            top_comments = {
                "Казак": ["степной король рулит!", "конь в деле, Казак на высоте!", "степь дрожит от его славы!"],
                "Илюха КЗ": ["шашлычный бог на троне!", "КЗ гордится своим героем!", "пиво и слава — его путь!"],
                "Ванечка": ["милота спасает чат!", "мид не провалился, Ванечка жжёт!", "самый милый чемпион!"],
                "ЖТ": ["мечтатель покорил вершины!", "ЖТ взлетел, как ракета!", "даже без баб он легенда!"],
                "Максик": ["танцпол в огне!", "вечеринка начинается с Максика!", "король тусовок!"],
                "Веныч": ["чилл на миллион!", "Веныч — король расслабона!", "маэстро спокойствия!"],
                "Юрчик": ["почти гений, но уже звезда!", "кодит, как бог!", "мозги Юрчика — это мощь!"],
                "Медик": ["спасает чат, как всегда!", "бинты и слава!", "доктор всех вылечил!"],
                "Васич": ["пабный герой!", "Васич с пивом непобедим!", "король барной стойки!"]
            }
            loser_comments = {
                "Казак": ["степь плачет по твоим фейлам!", "конь сбежал, Казак в пролёте!", "степной лузер дня!"],
                "Илюха КЗ": ["шашлык сгорел, как твоя репутация!", "КЗ в шоке от твоих фейлов!", "пиво закончилось, Илюха грустит!"],
                "Ванечка": ["мид провалился снова!", "милота не помогла!", "Ванечка, даже ангелы плачут!"],
                "ЖТ": ["мечтатель без баб на максималках!", "ЖТ, твои мечты тонут!", "даже фантазии тебя подвели!"],
                "Максик": ["танцпол пуст, Максик фейлит!", "вечеринка без Максика — провал!", "лузер тусовки!"],
                "Веныч": ["чилл не спас, Веныч внизу!", "даже расслабон не помог!", "лузер спокойствия!"],
                "Юрчик": ["код с ошибкой 404!", "Юрчик, гениальность где-то потерялась!", "эксперимент Юрчика провалился!"],
                "Медик": ["бинты не спасли!", "Медик, диагноз: фейл!", "пациент не выжил!"],
                "Васич": ["пабный чемпион по фейлам!", "пиво пролилось, Васич в пролёте!", "лузер барной стойки!"]
            }

            # Топ-3 Красавчиков
            top_winners = sorted(stats.items(), key=lambda x: x[1]["wins"], reverse=True)[:3]
            response += "\n🏆 Топ-3 Красавчиков:\n"
            for i, (user_id, data) in enumerate(top_winners, 1):
                comment = random.choice(top_comments.get(data["name"].lstrip("@"), ["просто легенда!"]))
                response += f"{i}. {data['name']} - {data['wins']} раз, {comment}\n"

            # Топ-3 Пидоров
            top_losers = sorted(stats.items(), key=lambda x: x[1]["losses"], reverse=True)[:3]
            response += "\n💥 Топ-3 Пидоров:\n"
            for i, (user_id, data) in enumerate(top_losers, 1):
                comment = random.choice(loser_comments.get(data["name"].lstrip("@"), ["эпичный провал!"]))
                response += f"{i}. {data['name']} - {data['losses']} раз, {comment}\n"

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
            print(f"Пользователь @{username} зарегистрирован в чате {chat_id}")
        else:
            if chat_id not in register_attempts:
                register_attempts[chat_id] = {}
            if user_id not in register_attempts[chat_id]:
                register_attempts[chat_id][user_id] = 0
            register_attempts[chat_id][user_id] += 1
            if register_attempts[chat_id][user_id] == 1:
                bot.reply_to(message, f"Вы уже зарегистрированы, долбаёб! @{username}")
            else:
                bot.reply_to(message, "да иди ты уже нахуй")
            print(f"Повторная попытка регистрации: @{username}, попытка #{register_attempts[chat_id][user_id]}")

    elif command == "/agr":
        if chat_id not in users or not users[chat_id]:
            bot.reply_to(message, "Нет зарегистрированных участников, сук! Используйте /register.")
            return

        current_time = time.time()
        if chat_id in last_agr and current_time - last_agr[chat_id] < 86400:
            remaining = int(86400 - (current_time - last_agr[chat_id]))
            hours = remaining // 3600
            minutes = (remaining % 3600) // 60
            bot.reply_to(message, f"Ещё рано для агра! Подождите {hours} ч {minutes} мин.")
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

        last_agr[chat_id] = current_time
        save_last_choice()

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

    elif command == "/checksheets":
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
            status = check_sheets_api(creds)
            bot.reply_to(message, f"Статус Google Sheets: {status}")
        except Exception as e:
            bot.reply_to(message, f"Ошибка проверки Google Sheets: {str(e)}")
            print(f"Ошибка проверки Google Sheets: {str(e)}")

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
