import os
import uuid

from dotenv import load_dotenv
from flask import Flask, jsonify, send_from_directory
from livekit import api

load_dotenv(".env.local")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=None)


@app.get("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.get("/token")
def token():
    # A fresh room per session => LiveKit dispatches your running agent to it.
    room = f"voice-{uuid.uuid4().hex[:8]}"
    identity = f"user-{uuid.uuid4().hex[:6]}"

    jwt = (
        api.AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])
        .with_identity(identity)
        .with_name("You")
        .with_grants(api.VideoGrants(room_join=True, room=room))
        .to_jwt()
    )
    return jsonify(token=jwt, url=os.environ["LIVEKIT_URL"], room=room)


if __name__ == "__main__":
    print("Open http://localhost:8000 in your browser")
    app.run(host="127.0.0.1", port=8000, debug=False)
