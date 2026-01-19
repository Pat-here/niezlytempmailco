from flask import Flask, render_template, request, redirect, url_for, session
import os
import database as db
from thunder_mail import MailTM

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "domyslny-sekretny-klucz-zmien-to-w-env")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "wypierdalaj!")

def is_logged_in():
    return session.get('logged_in')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('dashboard'))
        else:
            return render_template('index.html', error="Błędne hasło")
    return render_template('index.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/')
def dashboard():
    if not is_logged_in(): return redirect(url_for('login'))
    stats_data = db.get_all_stats()
    return render_template('dashboard.html', stats={'users': stats_data[0], 'emails': stats_data[1], 'banned': stats_data[2]})

@app.route('/users')
def users():
    if not is_logged_in(): return redirect(url_for('login'))
    all_users = db.get_all_users_web()
    return render_template('users.html', users=all_users)

@app.route('/ban/<int:user_id>')
def toggle_ban(user_id):
    if not is_logged_in(): return redirect(url_for('login'))
    db.admin_toggle_ban(user_id)
    return redirect(url_for('users'))

@app.route('/spy')
def spy():
    if not is_logged_in(): return redirect(url_for('login'))
    emails_data = db.admin_get_all_emails_tokens()
    messages = []
    for row in emails_data:
        eid, uid, addr, token = row
        try:
            msgs = MailTM.get_messages(token)
            if msgs:
                latest = msgs[0]
                messages.append({
                    'addr': addr,
                    'subject': latest.get('subject', 'Brak tematu'),
                    'from': latest.get('from', {}).get('address', 'Nieznany'),
                    'intro': latest.get('intro', 'Brak podglądu')[:80]
                })
        except Exception:
            continue
    return render_template('spy.html', messages=messages)

@app.route('/keep_alive')
def keep_alive():
    """Endpoint dla UptimeRobot, żeby aplikacja na Renderze nie zasypiała."""
    return "OK", 200