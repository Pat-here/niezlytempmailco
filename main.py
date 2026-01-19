import threading
from web_app import app
from thunder_mail import run_bot_process
import os

# WAŻNE: To musi być POZA sekcją if __name__ == "__main__"
# Dzięki temu Gunicorn uruchomi bota podczas startu serwera
print("🚀 Inicjalizacja systemu ThunderMail...")
try:
    bot_thread = threading.Thread(target=run_bot_process)
    bot_thread.daemon = True
    bot_thread.start()
    print("🤖 Wątek bota został zainicjowany pomyślnie.")
except Exception as e:
    print(f"❌ Błąd podczas startu wątku bota: {e}")

if __name__ == "__main__":
    # Ta sekcja wykona się tylko przy lokalnym uruchomieniu: python main.py
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
