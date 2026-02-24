import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Отримуємо шлях до папки, де лежить цей файл (config.py)
BASE_DIR = Path(__file__).resolve().parent

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = int(os.getenv("GROUP_ID"))

# Отримуємо URL з .env
raw_db_url = os.getenv("DATABASE_URL")

# Якщо це SQLite, перетворюємо відносний шлях на абсолютний
if raw_db_url.startswith("sqlite"):
    # sqlite+aiosqlite:///./university.db -> беремо назву файлу
    db_file = raw_db_url.split("/")[-1]
    # Створюємо абсолютний шлях до файлу в корені проекту
    DATABASE_URL = f"sqlite+aiosqlite:///{BASE_DIR / db_file}"
else:
    DATABASE_URL = raw_db_url


# import os
# from dotenv import load_dotenv
#
# load_dotenv()
#
# BOT_TOKEN = os.getenv("BOT_TOKEN")
# DATABASE_URL = os.getenv("DATABASE_URL")
# GROUP_ID = int(os.getenv("GROUP_ID"))
