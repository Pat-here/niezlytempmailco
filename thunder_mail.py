import os
import logging
import requests
import random
import string
import asyncio
import database as db
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
MAIL_TM_API = "https://api.mail.tm"

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


# --- UI HELPERS ---
async def send_fresh_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str,
                          keyboard: InlineKeyboardMarkup):
    user_id = update.effective_user.id
    last_msg_id = db.get_last_menu_id(user_id)
    if last_msg_id:
        try:
            await context.bot.delete_message(chat_id=user_id, message_id=last_msg_id)
        except Exception:
            pass
    try:
        if update.callback_query:
            await update.callback_query.answer()
        msg = await context.bot.send_message(chat_id=user_id, text=text, parse_mode=ParseMode.HTML,
                                             reply_markup=keyboard, disable_web_page_preview=True)
        db.update_last_menu_id(user_id, msg.id)
    except Exception as e:
        logger.error(f"Błąd wysyłania menu: {e}")


def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ Generuj Email", callback_data='gen_new'),
         InlineKeyboardButton("📂 Moje Skrzynki", callback_data='list_emails')],
        [InlineKeyboardButton("👤 Mój Profil", callback_data='profile'),
         InlineKeyboardButton("ℹ️ Pomoc", callback_data='about')]
    ])


def back_btn(target='main_menu'):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Wróć do Menu", callback_data=target)]])


# --- CLEANER ---
def pretty_clean_html(html_content, text_content):
    if not html_content and text_content: return text_content, []
    if not html_content: return "Brak treści.", []
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        for el in soup(["script", "style", "head", "meta", "iframe", "input", "img"]):
            el.decompose()
        found_links = [f"🔗 {a.get_text(strip=True)[:30]}: {a['href']}" for a in soup.find_all('a', href=True) if
                       "http" in a['href'] and "unsubscribe" not in a['href'].lower()]
        for br in soup.find_all("br"): br.replace_with("\n")
        clean_text = "\n".join([line.strip() for line in soup.get_text(separator="\n").splitlines() if line.strip()])
        return clean_text, found_links[:10]
    except Exception:
        return text_content or "Błąd przetwarzania HTML.", []


# --- MAIL ENGINE ---
class MailTM:
    @staticmethod
    def get_domain():
        try:
            return requests.get(f"{MAIL_TM_API}/domains").json()['hydra:member'][0]['domain']
        except:
            return None

    @staticmethod
    def create_account(addr, pwd):
        r = requests.post(f"{MAIL_TM_API}/accounts", json={"address": addr, "password": pwd})
        return r.json() if r.status_code == 201 else None

    @staticmethod
    def get_token(addr, pwd):
        r = requests.post(f"{MAIL_TM_API}/token", json={"address": addr, "password": pwd})
        return r.json().get('token') if r.ok else None

    @staticmethod
    def get_messages(token):
        try:
            r = requests.get(f"{MAIL_TM_API}/messages", headers={'Authorization': f'Bearer {token}'})
            return r.json().get('hydra:member', [])
        except:
            return []

    @staticmethod
    def get_message_content(token, mid):
        try:
            return requests.get(f"{MAIL_TM_API}/messages/{mid}", headers={'Authorization': f'Bearer {token}'}).json()
        except:
            return {}


# --- HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.add_or_update_user(user.id, user.username, user.first_name)
    text = f"👋 <b>Cześć, {user.first_name}!</b>\nWitaj w <b>ThunderTempMail</b>.\nTwórz tymczasowe adresy email i używaj ich swobodnie.\n\n👇 <b>Panel Sterowania:</b>"
    await send_fresh_menu(update, context, text, main_menu_keyboard())


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user = query.from_user
    info = db.get_user_info(user.id)
    if info.get('is_banned'):
        await query.answer("Twoje konto jest zablokowane.", show_alert=True)
        return

    if data == 'main_menu':
        await start(update, context)
    elif data == 'profile':
        text = f"👤 <b>Twój Profil</b>\n\n🆔 ID: <code>{user.id}</code>\n🔢 Limit skrzynek: <b>{info['limit']}</b> (aktywne)\n📅 Dzienny limit generowania: <b>{info['daily_usage']}/{info['limit']}</b>\n📧 Aktywne teraz: <b>{db.count_user_emails(user.id)}</b>"
        await send_fresh_menu(update, context, text, back_btn())
    elif data == 'about':
        text = "ℹ️ <b>ThunderTempMail</b>\n\nSystem tymczasowych skrzynek e-mail. W razie problemów, skontaktuj się z administratorem."
        await send_fresh_menu(update, context, text, back_btn())
    elif data == 'gen_new':
        if db.count_user_emails(user.id) >= info['limit']:
            await query.answer(f"Osiągnięto limit {info['limit']} aktywnych skrzynek. Usuń jedną, by stworzyć nową.",
                               show_alert=True)
            return
        can_create, msg = db.check_daily_limit(user.id, info['limit'])
        if not can_create:
            await query.answer(msg, show_alert=True)
            return
        await query.edit_message_text("⚙️ <i>Generowanie nowej skrzynki...</i>", parse_mode=ParseMode.HTML)
        dom = MailTM.get_domain()
        if not dom:
            await send_fresh_menu(update, context, "⚠️ Błąd API, nie można pobrać domeny. Spróbuj za chwilę.",
                                  back_btn())
            return
        rnd = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
        addr = f"{rnd}@{dom}"
        pwd = "P" + ''.join(random.choices(string.ascii_letters + string.digits, k=12))
        acc = MailTM.create_account(addr, pwd)
        if acc and acc.get('id'):
            token = MailTM.get_token(addr, pwd)
            db.add_email_to_db(user.id, addr, pwd, token, acc['id'])
            text = f"✅ <b>Gotowe!</b>\n\nNowy adres email:\n📧 <code>{addr}</code>\n\n(Kliknij, aby skopiować)"
            await send_fresh_menu(update, context, text, main_menu_keyboard())
        else:
            await send_fresh_menu(update, context, "⚠️ Błąd tworzenia konta email. Spróbuj ponownie.", back_btn())
    elif data == 'list_emails':
        emails = db.get_user_emails(user.id)
        if not emails:
            await query.answer("Nie masz jeszcze żadnych skrzynek.", show_alert=True)
            return
        kb = [[InlineKeyboardButton(f"📬 {addr}", callback_data=f"view_{eid}")] for addr, eid in emails]
        kb.append([InlineKeyboardButton("🏠 Menu Główne", callback_data='main_menu')])
        await send_fresh_menu(update, context, "📂 <b>Wybierz skrzynkę:</b>", InlineKeyboardMarkup(kb))
    elif data.startswith('view_'):
        eid = data.split('_')[1]
        det = db.get_email_details(eid)
        if not det:
            await query.answer("Ta skrzynka została usunięta.", show_alert=True)
            await start(update, context)
            return
        msgs = MailTM.get_messages(det[1])
        text = f"📬 <b>Panel Skrzynki</b>\n\n📧 <code>{det[0]}</code>\n📨 Wiadomości: <b>{len(msgs)}</b>"
        kb = [[InlineKeyboardButton("📨 Skrzynka Odbiorcza", callback_data=f"inbox_{eid}")],
              [InlineKeyboardButton("🗑️ Usuń Adres", callback_data=f"del_{eid}")],
              [InlineKeyboardButton("🔙 Wróć", callback_data='list_emails')]]
        await send_fresh_menu(update, context, text, InlineKeyboardMarkup(kb))
    elif data.startswith('del_'):
        eid = data.split('_')[1]
        db.delete_email_from_db(eid)
        await query.answer("Usunięto skrzynkę!", show_alert=True)
        await menu_callback(await query.edit_message_text("..."), context)  # Refresh list
    elif data.startswith('inbox_'):
        eid = data.split('_')[1]
        det = db.get_email_details(eid)
        if not det: return
        msgs = MailTM.get_messages(det[1])
        if not msgs:
            await query.answer("Skrzynka jest pusta!", show_alert=True)
            return
        text = f"📨 <b>Wiadomości ({len(msgs)}):</b>"
        kb = [[InlineKeyboardButton(f"📄 {(m.get('subject') or 'Brak tematu')[:25]}",
                                    callback_data=f"read_{eid}_{m['id']}")] for m in msgs[:10]]
        kb.append([InlineKeyboardButton("🔙 Panel Skrzynki", callback_data=f"view_{eid}")])
        await send_fresh_menu(update, context, text, InlineKeyboardMarkup(kb))
    elif data.startswith('read_'):
        try:
            _, eid, mid = data.split('_')
            det = db.get_email_details(eid)
            full = MailTM.get_message_content(det[1], mid)
            html = "".join(full.get('html', []))
            clean_text, links = pretty_clean_html(html, full.get('text', ''))
            view_text = f"👤 <b>Od:</b> {full.get('from', {}).get('address')}\n📝 <b>Temat:</b> {full.get('subject')}\n➖➖➖➖➖➖➖➖\n{clean_text[:1500]}"
            if links: view_text += "\n\n👇 <b>Linki w wiadomości:</b>\n" + "\n".join(links)
            kb = [[InlineKeyboardButton("🗑️ Usuń Skrzynkę", callback_data=f"del_{eid}")],
                  [InlineKeyboardButton("🔙 Wróć do Listy", callback_data=f"inbox_{eid}")]]
            await send_fresh_menu(update, context, view_text, InlineKeyboardMarkup(kb))
        except Exception as e:
            await query.answer(f"Błąd odczytu wiadomości: {e}", show_alert=True)


# --- JOBS ---
async def check_mail_job(context: ContextTypes.DEFAULT_TYPE):
    conn = None
    try:
        conn = db.get_connection()
        c = conn.cursor()
        c.execute("SELECT id, user_id, address, token, last_msg_count FROM emails")
        rows = c.fetchall()
        c.close()

        for eid, uid, addr, token, last_count in rows:
            try:
                msgs = MailTM.get_messages(token)
                current_count = len(msgs)
                if current_count > last_count:
                    new_msgs = current_count - last_count
                    latest = msgs[0]
                    notif_text = f"🔔 <b>NOWA WIADOMOŚĆ!</b>\nNa skrzynce: <code>{addr}</code>\nOd: {latest.get('from', {}).get('address')}\nTemat: <b>{latest.get('subject', 'Brak')}</b>"
                    kb = [[InlineKeyboardButton("📖 Czytaj Teraz", callback_data=f"read_{eid}_{latest['id']}")]]
                    await context.bot.send_message(uid, notif_text, parse_mode=ParseMode.HTML,
                                                   reply_markup=InlineKeyboardMarkup(kb))

                    c_update = conn.cursor()
                    c_update.execute("UPDATE emails SET last_msg_count = %s WHERE id = %s", (current_count, eid))
                    conn.commit()
                    c_update.close()
                elif current_count != last_count:
                    c_update = conn.cursor()
                    c_update.execute("UPDATE emails SET last_msg_count = %s WHERE id = %s", (current_count, eid))
                    conn.commit()
                    c_update.close()
            except Exception as e:
                logger.warning(f"Błąd sprawdzania skrzynki {addr}: {e}")
                continue
    except Exception as e:
        logger.error(f"Główny błąd w check_mail_job: {e}")
    finally:
        if conn:
            db.release_connection(conn)


async def maintenance_job(context: ContextTypes.DEFAULT_TYPE):
    db.cleanup_old_emails(days=7)


# --- RUNNER ---
def run_bot_process():
    """Funkcja uruchamiana w osobnym wątku"""
    # Fix dla loopa w wątku
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    db.init_db()
    
    # TOKEN pobierany z env
    app = Application.builder().token(os.getenv("TELEGRAM_TOKEN")).build()

    # Handlery
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(menu_callback))

    # Jobs
    app.job_queue.run_repeating(check_mail_job, interval=20, first=10)
    app.job_queue.run_repeating(maintenance_job, interval=86400, first=60)

    print("🤖 Bot ThunderMail wystartował pomyślnie!")
    
    # WAŻNE: stop_signals=None jest kluczowe, gdy bot działa w wątku!
    app.run_polling(stop_signals=None)
