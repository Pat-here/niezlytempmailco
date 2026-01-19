import threading, os
from web_app import app
from thunder_mail import run_bot_process

# Start Bota
print("🚀 Start bota...")
threading.Thread(target=run_bot_process, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
