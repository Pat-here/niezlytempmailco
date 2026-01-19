import threading, os, time
from web_app import app
from thunder_mail import run_bot_process

# Blokada przed wieloma instancjami bota
if os.environ.get('BOT_ALREADY_STARTED') is None:
    os.environ['BOT_ALREADY_STARTED'] = 'true'
    print("🚀 Uruchamiam bota w tle...")
    threading.Thread(target=run_bot_process, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
