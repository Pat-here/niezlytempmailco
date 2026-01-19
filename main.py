import threading
from web_app import app
from thunder_mail import run_bot_process
import os

if __name__ == "__main__":
    print("🚀 Uruchamianie aplikacji ThunderMail...")

    # Uruchom bota w osobnym wątku
    bot_thread = threading.Thread(target=run_bot_process)
    bot_thread.daemon = True  # Pozwól na zamknięcie wątku gdy główny program się zakończy
    bot_thread.start()

    # Uruchom serwer Flask
    port = int(os.environ.get("PORT", 5000))
    # Na Renderze Gunicorn sam obsłuży serwowanie, to jest głównie do testów lokalnych
    app.run(host="0.0.0.0", port=port, debug=False)