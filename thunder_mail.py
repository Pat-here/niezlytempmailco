import os, logging, asyncio, random, string, requests
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, ConversationHandler, MessageHandler, filters
import database as db

# SETUP
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
MAIL_TM_API = "https://api.mail.tm"

# States dla Admina
BROADCAST_MSG, SET_LIMIT_VAL = range(2)

# --- ENGINE ---
class MailTM:
    @staticmethod
    def get_domain():
        try: return requests.get(f"{MAIL_TM_API}/domains").json()['hydra:member'][0]['domain']
        except: return None
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
        try: return requests.get(f"{MAIL_TM_API}/messages", headers={'Authorization': f'Bearer {token}'}).json().get('hydra:member', [])
        except: return []
    @staticmethod
    def get_message_content(token, mid):
        try: return requests.get(f"{MAIL_TM_API}/messages/{mid}", headers={'Authorization': f'Bearer {token}'}).json()
        except: return {}

def clean_html(html, text):
    if not html: return text or "Brak treści."
    soup = BeautifulSoup(html, 'html.parser')
    for el in soup(["script", "style", "head", "meta"]): el.decompose()
    links = [f"🔗 {a.get_text(strip=True)[:20]}: {a['href']}" for a in soup.find_all('a', href=True) if "http" in a['href']]
    txt = soup.get_text(separator="\n").strip()
    res = "\n".join([l.strip() for l in txt.splitlines() if l.strip()])
    if links: res += "\n\n" + "\n".join(links[:5])
    return res[:3500]

# --- USER HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.add_or_update_user(user.id, user.username, user.first_name)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ Generuj Email", callback_data='gen_new'), InlineKeyboardButton("📂 Moje Skrzynki", callback_data='list_emails')],
        [InlineKeyboardButton("👤 Mój Profil", callback_data='profile'), InlineKeyboardButton("ℹ️ Pomoc", callback_data='about')]
    ])
    text = f"👋 <b>Cześć, {user.first_name}!</b>\nWitaj w <b>ThunderTempMail</b>.\n\n👇 <b>Wybierz opcję:</b>"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    else:
        msg = await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        db.update_last_menu_id(user.id, msg.id)

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    info = db.get_user_info(user_id)

    if info['is_banned']: return await query.answer("Ban!", show_alert=True)

    if data == 'gen_new':
        if db.count_user_emails(user_id) >= info['limit']:
            return await query.answer(f"Limit {info['limit']} skrzynek!", show_alert=True)
        can, msg = db.check_daily_limit(user_id, info['limit'])
        if not can: return await query.answer(msg, show_alert=True)
        
        dom = MailTM.get_domain()
        addr = f"{''.join(random.choices(string.ascii_lowercase + string.digits, k=10))}@{dom}"
        pwd = "P" + ''.join(random.choices(string.ascii_letters + string.digits, k=10))
        acc = MailTM.create_account(addr, pwd)
        if acc:
            token = MailTM.get_token(addr, pwd)
            db.add_email_to_db(user_id, addr, pwd, token, acc['id'])
            await query.edit_message_text(f"✅ <b>Gotowe!</b>\n\n📧 <code>{addr}</code>", parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data='main_menu')]]))
    
    elif data == 'list_emails':
        emails = db.get_user_emails(user_id)
        if not emails: return await query.answer("Brak skrzynek.", show_alert=True)
        kb = [[InlineKeyboardButton(f"📬 {a}", callback_data=f"view_{i}")] for a, i in emails]
        kb.append([InlineKeyboardButton("🏠 Wróć", callback_data='main_menu')])
        await query.edit_message_text("📂 <b>Twoje skrzynki:</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

    elif data.startswith('view_'):
        eid = data.split('_')[1]
        det = db.get_email_details(eid)
        msgs = MailTM.get_messages(det[1])
        kb = [[InlineKeyboardButton(f"📨 Inbox ({len(msgs)})", callback_data=f"inbox_{eid}")], [InlineKeyboardButton("🗑️ Usuń", callback_data=f"del_{eid}")], [InlineKeyboardButton("🔙 Wróć", callback_data='list_emails')]]
        await query.edit_message_text(f"📧 <code>{det[0]}</code>", reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

    elif data.startswith('inbox_'):
        eid = data.split('_')[1]
        det = db.get_email_details(eid)
        msgs = MailTM.get_messages(det[1])
        if not msgs: return await query.answer("Pusto!", show_alert=True)
        kb = [[InlineKeyboardButton(f"📄 {m.get('subject')[:20]}", callback_data=f"read_{eid}_{m['id']}")] for m in msgs[:10]]
        kb.append([InlineKeyboardButton("🔙 Wróć", callback_data=f"view_{eid}")])
        await query.edit_message_text("📨 <b>Wiadomości:</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

    elif data.startswith('read_'):
        _, eid, mid = data.split('_')
        det = db.get_email_details(eid)
        msg = MailTM.get_message_content(det[1], mid)
        text = f"👤 <b>Od:</b> {msg.get('from',{}).get('address')}\n📝 <b>Temat:</b> {msg.get('subject')}\n\n{clean_html(msg.get('html'), msg.get('text'))}"
        await query.edit_message_text(text[:4000], parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Inbox", callback_data=f"inbox_{eid}")]]))

    elif data.startswith('del_'):
        db.delete_email_from_db(data.split('_')[1])
        await query.answer("Usunięto.")
        await start(update, context)

    elif data == 'main_menu': await start(update, context)
    elif data == 'profile':
        await query.edit_message_text(f"👤 <b>Profil</b>\nID: <code>{user_id}</code>\nLimity: {info['daily_usage']}/{info['limit']}", parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Wróć", callback_data='main_menu')]]))

# --- KOZACKI PANEL ADMINA ---
async def admin_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    s = db.get_all_stats()
    text = (f"🕵️‍♂️ <b>ADMIN MODE</b>\n━━━━━━━━━━━━\n"
            f"👥 Userzy: <b>{s[0]}</b>\n📧 Skrzynki: <b>{s[1]}</b>\n"
            f"📩 Odebrano: <b>{s[3]}</b>\n💀 Bany: <b>{s[2]}</b>")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👁️ SZPIEG (Wiadomości)", callback_data="adm_spy")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="adm_bc")],
        [InlineKeyboardButton("👥 Lista Użytkowników", callback_data="adm_users_0")],
        [InlineKeyboardButton("❌ Zamknij", callback_data="adm_close")]
    ])
    if update.callback_query: await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    else: await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return
    data = query.data

    if data == "adm_spy":
        await query.edit_message_text("🕵️ <i>Skanowanie...</i>", parse_mode=ParseMode.HTML)
        mails = db.admin_get_all_emails_tokens()
        results = []
        for eid, uid, addr, token in mails[:30]:
            msgs = MailTM.get_messages(token)
            if msgs:
                m = msgs[0]
                results.append([f"📧 {addr[:15]}.. | {m.get('subject')[:15]}", f"adm_read_{eid}_{m['id']}"])
        if not results: return await query.edit_message_text("Pusto.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="adm_back")]]))
        kb = [[InlineKeyboardButton(r[0], callback_data=r[1])] for r in results]
        kb.append([InlineKeyboardButton("🔙 Panel", callback_data="adm_back")])
        await query.edit_message_text("👁️ <b>Ostatnie u innych:</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

    elif data.startswith("adm_read_"):
        _, _, eid, mid = data.split('_')
        det = db.get_email_details(eid)
        msg = MailTM.get_message_content(det[1], mid)
        txt = f"🕵️ <b>SPY:</b> {det[0]}\nOd: {msg.get('from',{}).get('address')}\n\n{clean_html(msg.get('html'), msg.get('text'))}"
        await query.edit_message_text(txt[:4000], parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Spy", callback_data="adm_spy")]]))

    elif data.startswith("adm_users_"):
        pg = int(data.split('_')[2])
        users = db.get_all_users_full()
        chunk = users[pg*10:(pg+1)*10]
        text = f"👥 <b>Użytkownicy (Strona {pg+1}):</b>\n"
        kb = []
        for u in chunk:
            status = "💀" if u[3] else "🟢"
            kb.append([InlineKeyboardButton(f"{status} {u[1]} (@{u[2]})", callback_data=f"adm_edit_{u[0]}")])
        nav = []
        if pg > 0: nav.append(InlineKeyboardButton("⬅️", callback_data=f"adm_users_{pg-1}"))
        if len(users) > (pg+1)*10: nav.append(InlineKeyboardButton("➡️", callback_data=f"adm_users_{pg+1}"))
        if nav: kb.append(nav)
        kb.append([InlineKeyboardButton("🔙 Panel", callback_data="adm_back")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

    elif data.startswith("adm_edit_"):
        uid = int(data.split('_')[2])
        info = db.get_user_info(uid)
        text = f"⚙️ <b>Edycja:</b> {info['name']}\nID: <code>{uid}</code>\nLimit: {info['limit']}\nStatus: {'ZBANOWANY' if info['is_banned'] else 'OK'}"
        kb = [[InlineKeyboardButton("🚫 Ban/Odbanuj", callback_data=f"adm_tban_{uid}")], [InlineKeyboardButton("🔢 Zmień Limit", callback_data=f"adm_slim_{uid}")], [InlineKeyboardButton("🔙 Lista", callback_data="adm_users_0")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)

    elif data.startswith("adm_tban_"):
        db.admin_toggle_ban(int(data.split('_')[2]))
        await admin_callback(update, context)

    elif data.startswith("adm_slim_"):
        context.user_data['target_uid'] = data.split('_')[2]
        await query.edit_message_text("🔢 Wpisz nowy limit skrzynek:")
        return SET_LIMIT_VAL

    elif data == "adm_bc":
        await query.edit_message_text("📢 Wpisz treść Broadcastu:")
        return BROADCAST_MSG

    elif data == "adm_back": await admin_main(update, context)
    elif data == "adm_close": await query.delete_message()

async def admin_broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text
    uids = db.get_all_users_ids()
    for uid in uids:
        try: await context.bot.send_message(uid, f"📢 <b>OGŁOSZENIE:</b>\n\n{msg}", parse_mode=ParseMode.HTML)
        except: continue
    await update.message.reply_text("✅ Wysłano!")
    return ConversationHandler.END

async def admin_limit_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        lim = int(update.message.text)
        db.admin_set_limit(context.user_data['target_uid'], lim)
        await update.message.reply_text(f"✅ Nowy limit: {lim}")
    except: await update.message.reply_text("❌ Błąd.")
    return ConversationHandler.END

# --- JOBS ---
async def check_mail_job(context: ContextTypes.DEFAULT_TYPE):
    conn = None
    try:
        conn = db.get_connection()
        c = conn.cursor()
        c.execute("SELECT id, user_id, address, token, last_msg_count FROM emails")
        rows = c.fetchall()
        for eid, uid, addr, token, last in rows:
            try:
                msgs = MailTM.get_messages(token)
                if len(msgs) > last:
                    m = msgs[0]
                    txt = f"🔔 <b>NOWA WIADOMOŚĆ!</b>\n📧 <code>{addr}</code>\n👤 Od: {m.get('from',{}).get('address')}\n📝 {m.get('subject')}"
                    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📖 Czytaj", callback_data=f"read_{eid}_{m['id']}")]])
                    await context.bot.send_message(uid, txt, parse_mode=ParseMode.HTML, reply_markup=kb)
                    c2 = conn.cursor()
                    c2.execute("UPDATE emails SET last_msg_count = %s WHERE id = %s", (len(msgs), eid))
                    conn.commit()
            except: continue
    finally:
        if conn: db.release_connection(conn)

def run_bot_process():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    db.init_db()
    app = Application.builder().token(TOKEN).build()
    
    # Handlery Admina (Conversations)
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_callback, pattern="^adm_bc$"), CallbackQueryHandler(admin_callback, pattern="^adm_slim_")],
        states={BROADCAST_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_broadcast_send)], SET_LIMIT_VAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_limit_save)]},
        fallbacks=[CommandHandler("cancel", start)]
    ))

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_main))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^adm_"))
    app.add_handler(CallbackQueryHandler(menu_callback))
    
    app.job_queue.run_repeating(check_mail_job, interval=15, first=10)
    
    print("🤖 Bot Ready!")
    app.run_polling(stop_signals=None)
