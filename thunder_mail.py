import os, logging, asyncio, random, string, requests
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, ConversationHandler, MessageHandler, filters
import database as db

TOKEN = os.getenv("TELEGRAM_TOKEN")
try: ADMIN_ID = int(os.getenv("ADMIN_ID"))
except: ADMIN_ID = 0

MAIL_TM_API = "https://api.mail.tm"
BROADCAST_MSG, SET_LIMIT_VAL = range(2)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- UTILS ---
def clean_html(html, text):
    if not html: return text or "Brak treści."
    soup = BeautifulSoup(html, 'html.parser')
    for el in soup(["script", "style"]): el.decompose()
    return soup.get_text(separator="\n").strip()[:3500]

class MailTM:
    @staticmethod
    def get_domain():
        return requests.get(f"{MAIL_TM_API}/domains").json()['hydra:member'][0]['domain']
    @staticmethod
    def create_account(addr, pwd):
        r = requests.post(f"{MAIL_TM_API}/accounts", json={"address": addr, "password": pwd})
        return r.json() if r.status_code == 201 else None
    @staticmethod
    def get_token(addr, pwd):
        r = requests.post(f"{MAIL_TM_API}/token", json={"address": addr, "password": pwd})
        return r.json().get('token')
    @staticmethod
    def get_messages(token):
        return requests.get(f"{MAIL_TM_API}/messages", headers={'Authorization': f'Bearer {token}'}).json().get('hydra:member', [])
    @staticmethod
    def get_message_content(token, mid):
        return requests.get(f"{MAIL_TM_API}/messages/{mid}", headers={'Authorization': f'Bearer {token}'}).json()

# --- USER HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.add_or_update_user(user.id, user.username, user.first_name)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ Generuj Email", callback_data='gen_new'), InlineKeyboardButton("📂 Moje Skrzynki", callback_data='list_emails')],
        [InlineKeyboardButton("👤 Mój Profil", callback_data='profile'), InlineKeyboardButton("ℹ️ Pomoc", callback_data='about')]
    ])
    text = f"👋 Witaj <b>{user.first_name}</b> w ThunderMail!"
    if update.callback_query: await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    else: 
        msg = await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        db.update_last_menu_id(user.id, msg.id)

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    uid = query.from_user.id
    info = db.get_user_info(uid)
    if info['is_banned']: return await query.answer("Zbanowany!", show_alert=True)

    if data == 'main_menu': await start(update, context)
    elif data == 'gen_new':
        if db.count_user_emails(uid) >= info['limit']: return await query.answer("Limit skrzynek!", show_alert=True)
        can, m = db.check_daily_limit(uid, info['limit'])
        if not can: return await query.answer(m, show_alert=True)
        dom = MailTM.get_domain()
        addr = f"{''.join(random.choices(string.ascii_lowercase + string.digits, k=10))}@{dom}"
        pwd = "P" + ''.join(random.choices(string.ascii_letters + string.digits, k=10))
        if MailTM.create_account(addr, pwd):
            tk = MailTM.get_token(addr, pwd)
            db.add_email_to_db(uid, addr, pwd, tk, "api")
            await query.edit_message_text(f"✅ Adres: <code>{addr}</code>", parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="main_menu")]]))
    elif data == 'list_emails':
        em = db.get_user_emails(uid)
        kb = [[InlineKeyboardButton(f"📬 {a}", callback_data=f"view_{i}")] for a, i in em]
        kb.append([InlineKeyboardButton("🏠 Menu", callback_data="main_menu")])
        await query.edit_message_text("📂 Twoje skrzynki:", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith('view_'):
        eid = data.split('_')[1]
        det = db.get_email_details(eid)
        msgs = MailTM.get_messages(det[1])
        kb = [[InlineKeyboardButton(f"📨 Inbox ({len(msgs)})", callback_data=f"inbox_{eid}")],[InlineKeyboardButton("🗑️ Usuń", callback_data=f"del_{eid}")],[InlineKeyboardButton("🔙 Wróć", callback_data="list_emails")]]
        await query.edit_message_text(f"📧 <code>{det[0] }</code>", reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.HTML)
    elif data.startswith('inbox_'):
        eid = data.split('_')[1]
        det = db.get_email_details(eid)
        msgs = MailTM.get_messages(det[1])
        if not msgs: return await query.answer("Pusto!", show_alert=True)
        kb = [[InlineKeyboardButton(f"📄 {m.get('subject')[:20]}", callback_data=f"read_{eid}_{m['id']}")] for m in msgs[:10]]
        kb.append([InlineKeyboardButton("🔙 Wróć", callback_data=f"view_{eid}")])
        await query.edit_message_text("📨 Wiadomości:", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith('read_'):
        _, eid, mid = data.split('_')
        det = db.get_email_details(eid)
        m = MailTM.get_message_content(det[1], mid)
        txt = f"👤 Od: {m.get('from',{}).get('address')}\n📝 Temat: {m.get('subject')}\n\n{clean_html(m.get('html'), m.get('text'))}"
        await query.edit_message_text(txt[:4000], parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Inbox", callback_data=f"inbox_{eid}")]]))
    elif data.startswith('del_'):
        db.delete_email_from_db(data.split('_')[1])
        await query.answer("Usunięto!")
        await start(update, context)

# --- ADMIN HANDLERS ---
async def admin_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    s = db.get_all_stats()
    text = f"🕵️‍♂️ <b>ADMIN MODE</b>\n━━━━━━━━━━━━\n👥 Userzy: {s[0]}\n📧 Skrzynki: {s[1]}\n📩 Odebrano: {s[3]}\n💀 Bany: {s[2]}"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👁️ SZPIEG", callback_data="adm_spy")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="adm_bc")],
        [InlineKeyboardButton("👥 Lista Userów", callback_data="adm_users_0")],
        [InlineKeyboardButton("❌ Zamknij", callback_data="adm_close")]
    ])
    await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return
    data = query.data

    if data == "adm_spy":
        mails = db.admin_get_all_emails_tokens()
        kb = []
        for eid, uid, addr, token in mails[:15]:
            try:
                m = MailTM.get_messages(token)
                if m: kb.append([InlineKeyboardButton(f"📧 {addr[:12]}.. | {m[0]['subject'][:12]}", callback_data=f"adm_read_{eid}_{m[0]['id']}")])
            except: continue
        kb.append([InlineKeyboardButton("🔙 Panel", callback_data="adm_back")])
        await query.edit_message_text("👁️ Ostatnie maile:", reply_markup=InlineKeyboardMarkup(kb))
    elif data == "adm_bc":
        await query.edit_message_text("📢 Wpisz treść ogłoszenia (lub /cancel):")
        return BROADCAST_MSG
    elif data.startswith("adm_users_"):
        pg = int(data.split('_')[2])
        users = db.get_all_users_full()
        chunk = users[pg*10:(pg+1)*10]
        kb = [[InlineKeyboardButton(f"{'💀' if u[3] else '🟢'} {u[1]} (@{u[2]})", callback_data=f"adm_edit_{u[0]}")] for u in chunk]
        nav = []
        if pg > 0: nav.append(InlineKeyboardButton("⬅️", callback_data=f"adm_users_{pg-1}"))
        if len(users) > (pg+1)*10: nav.append(InlineKeyboardButton("➡️", callback_data=f"adm_users_{pg+1}"))
        if nav: kb.append(nav)
        kb.append([InlineKeyboardButton("🔙 Panel", callback_data="adm_back")])
        await query.edit_message_text("👥 Użytkownicy:", reply_markup=InlineKeyboardMarkup(kb))
    elif data == "adm_back":
        s = db.get_all_stats()
        text = f"🕵️‍♂️ <b>ADMIN MODE</b>\n━━━━━━━━━━━━\n👥 Userzy: {s[0]}\n📧 Skrzynki: {s[1]}\n📩 Odebrano: {s[3]}\n💀 Bany: {s[2]}"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("👁️ SZPIEG", callback_data="adm_spy")],[InlineKeyboardButton("📢 Broadcast", callback_data="adm_bc")],[InlineKeyboardButton("👥 Lista Userów", callback_data="adm_users_0")],[InlineKeyboardButton("❌ Zamknij", callback_data="adm_close")]])
        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    elif data == "adm_close": await query.delete_message()

async def admin_bc_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uids = db.get_all_users_ids()
    for u in uids:
        try: await context.bot.send_message(u, f"📢 <b>OGŁOSZENIE:</b>\n\n{update.message.text}", parse_mode=ParseMode.HTML)
        except: continue
    await update.message.reply_text("✅ Wysłano!")
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
                    txt = f"🔔 <b>NOWA WIADOMOŚĆ!</b>\n📧 <code>{addr}</code>\n📝 {m.get('subject')}"
                    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📖 Czytaj", callback_data=f"read_{eid}_{m['id']}")]])
                    await context.bot.send_message(uid, txt, parse_mode=ParseMode.HTML, reply_markup=kb)
                    c2 = conn.cursor()
                    c2.execute("UPDATE emails SET last_msg_count = %s WHERE id = %s", (len(msgs), eid))
                    conn.commit()
            except: continue
    finally:
        if conn: db.release_connection(conn)

# --- BOOT ---
def run_bot_process():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    db.init_db()
    app = Application.builder().token(TOKEN).build()
    
    # Broadcast Conversation
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_callback, pattern="^adm_bc$")],
        states={BROADCAST_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_bc_send)]},
        fallbacks=[CommandHandler("cancel", start)]
    ))

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_main))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^adm_"))
    app.add_handler(CallbackQueryHandler(menu_callback))
    
    app.job_queue.run_repeating(check_mail_job, interval=15, first=10)
    app.run_polling(stop_signals=None)
