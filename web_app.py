from flask import Flask, session, redirect, url_for, request
import os, database as db

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "super-secret")

@app.route('/')
def home():
    if not session.get('logged_in'): return redirect(url_for('login'))
    s = db.get_all_stats()
    return f"""
    <html><body style="font-family:sans-serif; text-align:center; padding-top:50px;">
        <h1>⚡ ThunderMail Dashboard</h1>
        <p>Użytkownicy: <b>{s[0]}</b> | Skrzynki: <b>{s[1]}</b></p>
        <p>Bany: <b>{s[2]}</b> | Odebrane: <b>{s[3]}</b></p>
        <br><a href="/logout" style="color:red;">Wyloguj</a>
    </body></html>
    """

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == os.getenv("ADMIN_PASSWORD"):
            session['logged_in'] = True
            return redirect(url_for('home'))
    return '<body style="text-align:center;padding-top:100px;"><form method="post"><h1>Admin Login</h1><input type="password" name="password"><br><br><input type="submit" value="Wejdź"></form></body>'

@app.route('/logout')
def logout():
    session.pop('logged_in', None); return redirect(url_for('login'))

@app.route('/keep_alive')
def keep_alive(): return "OK", 200
