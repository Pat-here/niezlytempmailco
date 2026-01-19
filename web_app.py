from flask import Flask, render_template, session, redirect, url_for, request
import os, database as db

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "flash-secret")

@app.route('/')
def home():
    if not session.get('logged_in'): return redirect(url_for('login'))
    s = db.get_all_stats()
    return f"<h1>ThunderMail Status</h1><p>Users: {s[0]}</p><p>Emails: {s[1]}</p><a href='/logout'>Logout</a>"

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == os.getenv("ADMIN_PASSWORD"):
            session['logged_in'] = True
            return redirect(url_for('home'))
    return '<form method="post"><input type="password" name="password"><input type="submit"></form>'

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/keep_alive')
def keep_alive(): return "OK", 200
