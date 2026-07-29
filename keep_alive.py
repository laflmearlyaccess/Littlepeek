from flask import Flask
from threading import Thread

app = Flask(__name__)


@app.route("/")
def home():
    return "Le bot est en ligne !"


def run():
    # Render (et la plupart des hébergeurs) fournissent le port à utiliser
    # via la variable d'environnement PORT. On retombe sur 8080 en local.
    import os
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)


def keep_alive():
    """Lance le serveur Flask dans un thread séparé, sans bloquer le bot."""
    t = Thread(target=run)
    t.start()