import os
import logging
import psycopg2
from psycopg2 import pool
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# --- PULA POŁĄCZEŃ ---
try:
    pg_pool = psycopg2.pool.ThreadedConnectionPool(
        minconn=1,
        maxconn=20,
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME")
    )
    print("✅ Pula połączeń DB aktywna.")
except Exception as e:
    logger.critical(f"❌ KRYTYCZNY BŁĄD puli DB: {e}")
    pg_pool = None

def get_connection():
    if pg_pool:
        return pg_pool.getconn()
    raise ConnectionError("Brak puli połączeń z bazą danych.")

def release_connection(conn):
    if pg_pool:
        pg_pool.putconn(conn)

# --- FUNKCJE BAZODANOWE ---

def init_db():
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS emails (id SERIAL PRIMARY KEY, user_id BIGINT, address TEXT, password TEXT, token TEXT, account_id TEXT, last_msg_count INTEGER DEFAULT 0, created_at TEXT DEFAULT '')''')
        c.execute('''CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, username TEXT, first_name TEXT, joined_at TEXT, is_banned INTEGER DEFAULT 0, custom_limit INTEGER DEFAULT 5, last_menu_msg_id BIGINT DEFAULT 0, daily_creations_count INTEGER DEFAULT 0, last_creation_date TEXT DEFAULT '')''')
        conn.commit()
        logger.info("✅ Inicjalizacja bazy danych zakończona.")
    except Exception as e:
        logger.error(f"Błąd inicjalizacji DB: {e}")
    finally:
        release_connection(conn)

def add_or_update_user(user_id, username, first_name):
    conn = get_connection()
    try:
        c = conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute("INSERT INTO users (user_id, username, first_name, joined_at) VALUES (%s, %s, %s, %s) ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username, first_name = EXCLUDED.first_name", (user_id, username, first_name, now))
        conn.commit()
    finally:
        release_connection(conn)

def get_user_info(user_id):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT is_banned, custom_limit, username, first_name, joined_at, daily_creations_count FROM users WHERE user_id = %s", (user_id,))
        res = c.fetchone()
        if res:
            return {'is_banned': res[0], 'limit': res[1], 'username': res[2], 'name': res[3], 'joined': res[4], 'daily_usage': res[5]}
    finally:
        release_connection(conn)
    return {'is_banned': 0, 'limit': 5, 'username': '?', 'name': '?', 'joined': '-', 'daily_usage': 0}

def check_daily_limit(user_id, max_limit):
    conn = get_connection()
    try:
        c = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        c.execute("SELECT daily_creations_count, last_creation_date FROM users WHERE user_id = %s", (user_id,))
        res = c.fetchone()
        if not res:
            c.execute("UPDATE users SET daily_creations_count = 1, last_creation_date = %s WHERE user_id = %s", (today, user_id))
            conn.commit()
            return True, "OK"
        count, last_date = res
        if last_date != today:
            c.execute("UPDATE users SET daily_creations_count = 1, last_creation_date = %s WHERE user_id = %s", (today, user_id))
            conn.commit()
            return True, "Reset"
        if count >= max_limit:
            return False, f"⚠️ Limit dzienny ({count}/{max_limit}) osiągnięty."
        c.execute("UPDATE users SET daily_creations_count = daily_creations_count + 1 WHERE user_id = %s", (user_id,))
        conn.commit()
        return True, "OK"
    finally:
        release_connection(conn)

def update_last_menu_id(user_id, msg_id):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("UPDATE users SET last_menu_msg_id = %s WHERE user_id = %s", (msg_id, user_id))
        conn.commit()
    finally:
        release_connection(conn)

def get_last_menu_id(user_id):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT last_menu_msg_id FROM users WHERE user_id = %s", (user_id,))
        res = c.fetchone()
        return res[0] if res else None
    finally:
        release_connection(conn)

def get_user_emails(user_id):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT address, id FROM emails WHERE user_id = %s", (user_id,))
        return c.fetchall()
    finally:
        release_connection(conn)

def count_user_emails(user_id):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT count(*) FROM emails WHERE user_id = %s", (user_id,))
        return c.fetchone()[0]
    finally:
        release_connection(conn)

def add_email_to_db(user_id, address, password, token, account_id):
    conn = get_connection()
    try:
        c = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        c.execute("INSERT INTO emails (user_id, address, password, token, account_id, created_at) VALUES (%s, %s, %s, %s, %s, %s)", (user_id, address, password, token, account_id, today))
        conn.commit()
    finally:
        release_connection(conn)

def get_email_details(email_id):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT address, token, password, user_id FROM emails WHERE id = %s", (email_id,))
        return c.fetchone()
    finally:
        release_connection(conn)

def delete_email_from_db(email_id):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM emails WHERE id = %s", (email_id,))
        conn.commit()
    finally:
        release_connection(conn)

def cleanup_old_emails(days=7):
    conn = get_connection()
    try:
        c = conn.cursor()
        cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        c.execute("DELETE FROM emails WHERE created_at < %s AND created_at != ''", (cutoff_date,))
        deleted_count = c.rowcount
        conn.commit()
        if deleted_count > 0:
            logger.info(f"🧹 MAINTENANCE: Usunięto {deleted_count} starych skrzynek.")
        return deleted_count
    except Exception as e:
        logger.error(f"Błąd czyszczenia starych maili: {e}")
        return 0
    finally:
        release_connection(conn)

# --- FUNKCJE DLA PANELU WEB ---
def get_all_stats():
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT (SELECT count(*) FROM users), (SELECT count(*) FROM emails), (SELECT count(*) FROM users WHERE is_banned = 1)")
        return c.fetchone()
    finally:
        release_connection(conn)

def get_all_users_web():
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT user_id, username, first_name, joined_at, is_banned, custom_limit, daily_creations_count FROM users ORDER BY joined_at DESC")
        return c.fetchall()
    finally:
        release_connection(conn)

def admin_toggle_ban(user_id):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("UPDATE users SET is_banned = CASE WHEN is_banned = 1 THEN 0 ELSE 1 END WHERE user_id = %s", (user_id,))
        conn.commit()
    finally:
        release_connection(conn)

def admin_get_all_emails_tokens():
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT id, user_id, address, token FROM emails ORDER BY id DESC LIMIT 50")
        return c.fetchall()
    finally:
        release_connection(conn)