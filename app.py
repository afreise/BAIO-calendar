import os
import json
import re
from datetime import datetime, timezone
from flask import Flask, request, jsonify, render_template, session
from flask_session import Session
from scraper import scrape_event
from calendar_client import add_to_calendar

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

APP_PASSWORD = os.environ.get("APP_PASSWORD", "changeme")

@app.route("/")
def index():
    authenticated = session.get("authenticated", False)
    return render_template("index.html", authenticated=authenticated)

@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    if data.get("password") == APP_PASSWORD:
        session["authenticated"] = True
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Incorrect password"}), 401

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"success": True})

@app.route("/add-events", methods=["POST"])
def add_events():
    if not session.get("authenticated"):
        return jsonify({"error": "Not authenticated"}), 401

    data = request.get_json()
    urls = data.get("urls", [])
    if not urls:
        return jsonify({"error": "No URLs provided"}), 400

    results = []
    for url in urls:
        url = url.strip()
        if not url:
            continue
        try:
            event = scrape_event(url)
            if not event:
                results.append({"url": url, "success": False, "error": "Could not extract event details"})
                continue
            calendar_link = add_to_calendar(event)
            results.append({"url": url, "success": True, "event": event, "calendar_link": calendar_link})
        except Exception as e:
            results.append({"url": url, "success": False, "error": str(e)})

    return jsonify({"results": results})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
