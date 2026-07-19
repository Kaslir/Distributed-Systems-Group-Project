import os

from flask import Flask, jsonify


app = Flask(__name__)


@app.get("/home")
def home():
    server_id = os.getenv("SERVER_ID", os.getenv("HOSTNAME", "unknown"))
    return jsonify({"message": f"Hello from Server: {server_id}", "status": "successful"}), 200


@app.get("/heartbeat")
def heartbeat():
    return "", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
