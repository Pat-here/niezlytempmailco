import requests
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, CallbackQueryHandler, MessageHandler, \
    filters
import database as db

# --- SETUP ---
BROADCAST_MSG, SET_LIMIT_VAL = range(2)
ADMIN_ID = 0
MAIL_TM_API = "https://api.mail.tm"


def set_admin_id(id):
    global ADMIN_ID
    ADMIN_ID = id


def is_admin(user_id):
    return user_id == ADMIN_ID


def admin_clean_html(html, text):
    if not html: return text or ""
    try:
        soup = BeautifulSoup(html, 'html.parser')
        for el in soup(["script", "style", "head", "meta", "iframe", "input"]): el.decompose()
        links = [f"🔗 {a.get_text(strip=True)}: {a['href']}" for a in soup.find_all('a', href=True) if
                 "http" in a['href']]
        for br in soup.find_all("br"): br.replace_with("\n")
        txt = soup.get_text(separator="\n").strip()
        final = "\n".join([l.strip() for l in txt.splitlines() if l.strip()])
        if links: final += "\n\n" + "\n".join(links[:5])
        return final
    except:
        return text


# --- MENU ADMINA ---
async def admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id): return

    stats = db.admin_get_stats()

    text = (
        f"🕵️‍♂️ <b>PANEL GOD MODE v2.2</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👥 Użytkownicy: <b>{stats[0]}</b>\n"
        f"📧 Aktywne Skrzynki: <b>{stats[1]}</b>\n"
        f"📩 Łącznie odebrano: <b>{stats[3]}</b> wiad.\n"
        f"💀 Zbanowani: <b>{stats[2]}</b>\n"
        f"━━━━━━━━━━━━━━━━━━"
    )

    keyboard = [
        [InlineKeyboardButton("👁️ SZPIEG (Podgląd Wiadomości)", callback_data="adm_spy_init")],
        [InlineKeyboardButton("📢 Wyślij Broadcast", callback_data="adm_broadcast")],
        [InlineKeyboardButton("👥 Lista Użytkowników", callback_data="adm_users_0")],
        [InlineKeyboardButton("❌ Zamknij", callback_data="adm_close")]
    ]

    if update.message:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML,
                                                      reply_markup=InlineKeyboardMarkup(keyboard))


# --- SPY MODE Z PAGINACJĄ ---
async def admin_spy_init(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.edit_message_text("🕵️ <i>Skanowanie skrzynek (to może chwilę potrwać)...</i>",
                                  parse_mode=ParseMode.HTML)

    all_emails = db.admin_get_all_emails_tokens()
    found_msgs = []

    # Skanujemy 40 ostatnich skrzynek
    for row in all_emails[:40]:
        eid, uid, addr, token = row
        try:
            r = requests.get(f"{MAIL_TM_API}/messages", headers={'Authorization': f'Bearer {token}'})
            if r.status_code == 200:
                msgs = r.json().get('hydra:member', [])
                if msgs:
                    latest = msgs[0]
                    uinfo = db.get_user_info(uid)
                    ulabel = f"@{uinfo['username']}" if uinfo['username'] else uinfo['name']

                    found_msgs.append({
                        'eid': eid,
                        'mid': latest['id'],
                        'sub': latest.get('subject', 'Brak'),
                        'user_label': ulabel,
                        'addr': addr
                    })
        except:
            continue

    context.user_data['spy_results'] = found_msgs

    if not found_msgs:
        kb = [[InlineKeyboardButton("🔙 Panel", callback_data="admin_dashboard")]]
        await query.edit_message_text("🕵️‍♂️ <b>Brak nowych wiadomości.</b>", parse_mode=ParseMode.HTML,
                                      reply_markup=InlineKeyboardMarkup(kb))
    else:
        await admin_spy_show_page(update, context, 0)


async def admin_spy_show_page(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int):
    query = update.callback_query
    results = context.user_data.get('spy_results', [])

    ITEMS_PER_PAGE = 5
    total_pages = (len(results) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE

    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    current_items = results[start:end]

    text = f"👁️ <b>WYNIKI SZPIEGA ({len(results)})</b>\nStrona {page + 1}/{total_pages}\n\n"
    kb = []

    for m in current_items:
        label = f"👤 {m['user_label']} | 📝 {m['sub'][:15]}"
        kb.append([InlineKeyboardButton(label, callback_data=f"adm_read_{m['eid']}_{m['mid']}")])

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"adm_spy_pg_{page - 1}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("➡️", callback_data=f"adm_spy_pg_{page + 1}"))

    if nav_row: kb.append(nav_row)

    kb.append([InlineKeyboardButton("🔄 Odśwież Skan", callback_data="adm_spy_init")])
    kb.append([InlineKeyboardButton("🔙 Panel Admina", callback_data="admin_dashboard")])

    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))


async def admin_read_spy_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        _, _, eid, mid = query.data.split('_')
        det = db.get_email_details(eid)
        if not det:
            await query.answer("Skrzynka usunięta", show_alert=True)
            return

        token = det[1]
        r = requests.get(f"{MAIL_TM_API}/messages/{mid}", headers={'Authorization': f'Bearer {token}'})
        if not r.ok:
            await query.answer("Błąd API", show_alert=True)
            return

        full = r.json()
        html = "".join(full.get('html', "") or "")
        clean = admin_clean_html(html, full.get('text', ""))

        msg_text = (
            f"🕵️ <b>PODGLĄD</b>\n"
            f"📩 Do: <code>{det[0]}</code>\n"
            f"👤 Od: {full.get('from', {}).get('address')}\n"
            f"📝 Temat: {full.get('subject')}\n"
            f"➖➖➖➖\n{clean[:3000]}"
        )

        kb = [[InlineKeyboardButton("🔙 Wróć do listy", callback_data="adm_spy_pg_0")]]
        await query.edit_message_text(msg_text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb),
                                      disable_web_page_preview=True)
    except Exception as e:
        await query.answer(f"Error: {e}", show_alert=True)


# --- BROADCAST ---
async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("📢 <b>BROADCAST</b>\n\nNapisz treść. /cancel anuluje.", parse_mode=ParseMode.HTML)
    return BROADCAST_MSG


async def broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text
    ids = db.get_all_users_ids()
    ok, fail = 0, 0
    stat = await update.message.reply_text(f"Wysyłanie do {len(ids)}...")
    for uid in ids:
        try:
            await context.bot.send_message(uid, f"📢 <b>INFO:</b>\n\n{msg}", parse_mode=ParseMode.HTML)
            ok += 1
        except:
            fail += 1
    await stat.edit_text(f"✅ OK: {ok}\n❌ Fail: {fail}")
    return ConversationHandler.END


# --- MAIN CALLBACK HANDLER ---
async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    if data == "admin_dashboard":
        await admin_start(update, context)
    elif data == "adm_close":
        await query.delete_message()
    elif data == "adm_spy_init":
        await admin_spy_init(update, context)
    elif data.startswith("adm_spy_pg_"):
        pg = int(data.split("_")[3])
        await admin_spy_show_page(update, context, pg)
    elif data.startswith("adm_read_"):
        await admin_read_spy_msg(update, context)

    elif data.startswith("adm_users_"):
        users_full = db.get_all_users_ids_full()
        page = int(data.split("_")[2])
        PER_PAGE = 10
        total_p = (len(users_full) + PER_PAGE - 1) // PER_PAGE

        current = users_full[page * PER_PAGE: (page + 1) * PER_PAGE]

        text = f"👥 <b>UŻYTKOWNICY ({len(users_full)})</b>\nStrona {page + 1}/{total_p}\n\n"
        kb = []

        for u in current:
            uid, name, uname, banned = u
            status = "💀" if banned else "🟢"
            display = f"@{uname}" if uname else name
            text += f"{status} <b>{display}</b> [`{uid}`]\n"
            kb.append([InlineKeyboardButton(f"⚙️ {display}", callback_data=f"adm_edit_{uid}")])

        nav = []
        if page > 0: nav.append(InlineKeyboardButton("⬅️", callback_data=f"adm_users_{page - 1}"))
        if page < total_p - 1: nav.append(InlineKeyboardButton("➡️", callback_data=f"adm_users_{page + 1}"))
        if nav: kb.append(nav)
        kb.append([InlineKeyboardButton("🔙 Panel", callback_data="admin_dashboard")])

        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("adm_edit_"):
        target = int(data.split("_")[2])
        info = db.get_user_info(target)
        status = "ZBANOWANY" if info['is_banned'] else "AKTYWNY"
        uname = f"@{info['username']}" if info['username'] else info['name']

        text = (
            f"⚙️ <b>EDYCJA USERA</b>\n"
            f"👤 {uname}\n"
            f"🆔 <code>{target}</code>\n"
            f"📅 Dołączył: {info['joined']}\n"
            f"📊 Dzienny limit: {info['daily_usage']}\n"
            f"🔢 Max skrzynek: <b>{info['limit']}</b>\n"
            f"stan: <b>{status}</b>"
        )

        btn_ban = "🟢 Odbanuj" if info['is_banned'] else "🔴 Zbanuj"
        kb = [
            [InlineKeyboardButton(btn_ban, callback_data=f"adm_ban_{target}")],
            [InlineKeyboardButton("🔢 Zmień Max Limit", callback_data=f"adm_lim_start_{target}")],
            [InlineKeyboardButton("🔙 Lista", callback_data="adm_users_0")]
        ]
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("adm_ban_"):
        target = int(data.split("_")[2])
        db.admin_toggle_ban(target)
        await admin_callback(update, context)

    elif data.startswith("adm_lim_start_"):
        target = int(data.split("_")[3])
        context.user_data['edit_user_id'] = target
        await query.edit_message_text(f"🔢 Wpisz nowy limit dla ID <code>{target}</code>:", parse_mode=ParseMode.HTML)
        return SET_LIMIT_VAL

    return ConversationHandler.END


async def set_limit_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = int(update.message.text)
        uid = context.user_data['edit_user_id']
        db.admin_set_limit(uid, val)
        await update.message.reply_text(f"✅ Nowy limit: {val}")
    except:
        await update.message.reply_text("❌ To nie liczba.")
    return ConversationHandler.END


async def cancel_op(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Anulowano.")
    return ConversationHandler.END