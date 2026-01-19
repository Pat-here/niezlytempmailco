import os, logging, psycopg2
from psycopg2 import pool
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# Pula połączeń
try:
    pg_pool = psycopg2.pool.ThreadedConnectionPool(
        minconn=1, maxconn=10,
        user=os.getenv("DB_USER"), password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"), dbname=os.getenv("DB_NAME")
    )
except Exception as e:
    print(f"Błąd inicjalizacji puli DB: {e}")

def get_connection(): return pg_pool.getconn()
def release_connection(conn): pg_pool.putconn(conn)

def init_db():
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("CREATE TABLE IF NOT EXISTS emails (id SERIAL PRIMARY KEY, user_id BIGINT, address TEXT, password TEXT, token TEXT, account_id TEXT, last_msg_count INTEGER DEFAULT 0, created_at TEXT DEFAULT '')")
        c.execute("CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, username TEXT, first_name TEXT, joined_at TEXT, is_banned INTEGER DEFAULT 0, custom_limit INTEGER DEFAULT 5, last_menu_msg_id BIGINT DEFAULT 0, daily_creations_count INTEGER DEFAULT 0, last_creation_date TEXT DEFAULT '')")
        conn.commit()
    finally: release_connection(conn)

def add_or_update_user(uid, uname, fname):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("INSERT INTO users (user_id, username, first_name, joined_at) VALUES (%s, %s, %s, %s) ON CONFLICT (user_id) DO UPDATE SET username=EXCLUDED.username, first_name=EXCLUDED.first_name", (uid, uname, fname, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
    finally: release_connection(conn)

def get_user_info(uid):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT is_banned, custom_limit, username, first_name, joined_at, daily_creations_count FROM users WHERE user_id = %s", (uid,))
        r = c.fetchone()
        if r: return {'is_banned':r[0], 'limit':r[1], 'username':r[2], 'name':r[3], 'joined':r[4], 'daily_usage':r[5]}
    finally: release_connection(conn)
    return {'is_banned':0, 'limit':5, 'username':'?', 'name':'?', 'joined':'-', 'daily_usage':0}

def check_daily_limit(uid, max_lim):
    conn = get_connection()
    try:
        c = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        c.execute("SELECT daily_creations_count, last_creation_date FROM users WHERE user_id = %s", (uid,))
        res = c.fetchone()
        if not res: return True, "OK"
        count, last_date = res
        if last_date != today:
            c.execute("UPDATE users SET daily_creations_count = 1, last_creation_date = %s WHERE user_id = %s", (today, uid))
            conn.commit()
            return True, "Reset"
        if count >= max_lim: return False, f"⚠️ Limit dzienny ({count}/{max_lim}) osiągnięty."
        c.execute("UPDATE users SET daily_creations_count = daily_creations_count + 1 WHERE user_id = %s", (uid,))
        conn.commit()
        return True, "OK"
    finally: release_connection(conn)

def add_email_to_db(uid, addr, pwd, token, acc_id):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("INSERT INTO emails (user_id, address, password, token, account_id, created_at) VALUES (%s, %s, %s, %s, %s, %s)", (uid, addr, pwd, token, acc_id, datetime.now().strftime("%Y-%m-%d")))
        conn.commit()
    finally: release_connection(conn)

def get_user_emails(uid):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT address, id FROM emails WHERE user_id = %s", (uid,))
        return c.fetchall()
    finally: release_connection(conn)

def get_email_details(eid):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT address, token, password, user_id FROM emails WHERE id = %s", (eid,))
        return c.fetchone()
    finally: release_connection(conn)

def delete_email_from_db(eid):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM emails WHERE id = %s", (eid,))
        conn.commit()
    finally: release_connection(conn)

def update_last_menu_id(uid, mid):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("UPDATE users SET last_menu_msg_id = %s WHERE user_id = %s", (mid, uid))
        conn.commit()
    finally: release_connection(conn)

def get_last_menu_id(uid):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT last_menu_msg_id FROM users WHERE user_id = %s", (uid,))
        r = c.fetchone()
        return r[0] if r else None
    finally: release_connection(conn)

def get_all_stats():
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT (SELECT count(*) FROM users), (SELECT count(*) FROM emails), (SELECT count(*) FROM users WHERE is_banned=1), (SELECT COALESCE(SUM(last_msg_count),0) FROM emails)")
        return c.fetchone()
    finally: release_connection(conn)

def admin_get_all_emails_tokens():
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT id, user_id, address, token FROM emails ORDER BY id DESC LIMIT 40")
        return c.fetchall()
    finally: release_connection(conn)

def get_all_users_full():
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT user_id, first_name, username, is_banned FROM users ORDER BY joined_at DESC")
        return c.fetchall()
    finally: release_connection(conn)

def get_all_users_ids():
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT user_id FROM users")
        return [r[0] for r in c.fetchall()]
    finally: release_connection(conn)

def admin_toggle_ban(uid):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("UPDATE users SET is_banned = CASE WHEN is_banned = 1 THEN 0 ELSE 1 END WHERE user_id = %s", (uid,))
        conn.commit()
    finally: release_connection(conn)

def admin_set_limit(uid, lim):
    conn = get_connection()
    try:
        c = conn.cursor()
        c.execute("UPDATE users SET custom_limit = %s WHERE user_id = %s", (lim, uid))
        conn.commit()
    finally: release_connection(conn)

def cleanup_old_emails(days=7):
    conn = get_connection()
    try:
        c = conn.cursor()
        cut = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        c.execute("DELETE FROM emails WHERE created_at < %s AND created_at != ''", (cut,))
        conn.commit()
    finally: release_connection(conn)
