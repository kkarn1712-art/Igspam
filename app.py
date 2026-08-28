import asyncio
import random
import uuid
import os
import json
import threading
import logging
from flask import Flask, jsonify, Response
from instagrapi import Client
from instagrapi.exceptions import LoginRequired, RateLimitError

logging.getLogger('werkzeug').setLevel(logging.ERROR)

USERNAME = "xyz.enters30"
PASSWORD = "ankushgodhu"

SESSION_FILE = f"session_{USERNAME}.json"

MSG_DELAY = 30
GROUP_DELAY = 4
ERROR_COOLDOWN = 3

MESSAGE_FILE = "text.txt"
TITLE_FILE = "nc.txt"

DOC_ID = "29088580780787855"
IG_APP_ID = "936619743392459"

USERS = [USERNAME]
logs_ui = {USERNAME: []}

def log_line(text):
    logs_ui[USERNAME].append(text)
    if len(logs_ui[USERNAME]) > 200:
        logs_ui[USERNAME].pop(0)
    print(text)

def load_lines(path):
    if not os.path.exists(path):
        print(f"❌ File missing: {path}")
        exit()
    with open(path, "r", encoding="utf-8") as f:
        return [x.strip() for x in f if x.strip()]

MESSAGES = load_lines(MESSAGE_FILE)
TITLES = load_lines(TITLE_FILE)

GREEN = "\033[92m"
RESET = "\033[0m"

cl = Client()
login_lock = asyncio.Lock()

app = Flask(__name__)

@app.route('/')
def home():
    return "alive"

@app.route('/status')
def status():
    return jsonify({user: logs_ui[user] for user in USERS})

@app.route('/logs')
def logs_route():
    output = []
    header_text = "✦  SINISTERS | SX⁷  ✦"
    output.append(header_text)
    output.append("=" * len(header_text))
    output.append("")
    for user in USERS:
        output.append(f"[ {user} ]")
        output.append("-" * (len(user) + 4))
        for line in logs_ui[user]:
            output.append(line)
        output.append("")
    return Response("\n".join(output), mimetype="text/plain")

@app.route("/dashboard")
def dashboard():
    html = """
    <html>
    <head>
        <title>SINISTERS | SX⁷</title>
        <meta http-equiv="refresh" content="2">
        <style>
            body { background-color: #0d1117; font-family: monospace; margin: 0; padding: 20px; color: #00ff88; }
            .header { text-align: center; font-size: 28px; font-weight: bold; margin-bottom: 30px; border: 2px solid #00ff88; padding: 10px; }
            .container { display: flex; flex-direction: row; gap: 20px; align-items: flex-start; }
            .panel { flex: 1; min-width: 300px; border: 2px solid #00ff88; background-color: #111827; padding: 15px; height: 80vh; overflow-y: auto; }
            .panel-title { font-weight: bold; margin-bottom: 10px; border-bottom: 1px solid #00ff88; padding-bottom: 5px; }
            .log-line { margin-bottom: 6px; white-space: pre-wrap; }
        </style>
    </head>
    <body>
        <div class="header">✦ SINISTERS | SX⁷ ✦</div>
        <div class="container">
    """
    for user in USERS:
        html += f'<div class="panel"><div class="panel-title">{user}</div>'
        for line in logs_ui[user]:
            html += f'<div class="log-line">{line}</div>'
        html += "</div>"
    html += """
        </div>
        <script>
        function scrollPanels() {
            document.querySelectorAll('.panel').forEach(function(panel) {
                panel.scrollTop = panel.scrollHeight;
            });
        }
        window.onload = scrollPanels;
        setInterval(scrollPanels, 1500);
        </script>
    </body>
    </html>
    """
    return html

def run_flask():
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)

def setup_mobile_fingerprint():
    cl.set_user_agent(
        "Instagram 312.0.0.22.114 Android "
        "(33/13; 420dpi; 1080x2400; OnePlus; "
        "GM1913; OnePlus7Pro; qcom; en_US)"
    )
    cl.set_locale("en_US")
    cl.set_country_code(1)
    cl.set_timezone_offset(-18000)

    uuids = {
        "phone_id": str(uuid.uuid4()),
        "uuid": str(uuid.uuid4()),
        "client_session_id": str(uuid.uuid4()),
        "advertising_id": str(uuid.uuid4()),
        "device_id": "android-" + uuid.uuid4().hex[:16]
    }

    cl.set_uuids(uuids)

    cl.private.headers.update({
        "X-IG-App-ID": IG_APP_ID,
        "X-IG-Device-ID": uuids["uuid"],
        "X-IG-Android-ID": uuids["device_id"],
        "X-IG-Timezone-Offset": "-18000",
        "Accept-Language": "en-US",
        "Connection": "keep-alive"
    })

async def login():
    async with login_lock:
        if os.path.exists(SESSION_FILE):
            try:
                cl.load_settings(SESSION_FILE)
                cl.login(USERNAME, PASSWORD)
                cl.get_timeline_feed()
                log_line(f"⏳SESSION LOGIN - {GREEN}{USERNAME}{RESET}")
                return
            except Exception:
                pass
        cl.login(USERNAME, PASSWORD)
        cl.dump_settings(SESSION_FILE)
        log_line(f"⏳FRESH LOGIN - {GREEN}{USERNAME}{RESET}")

def fetch_group_threads():
    try:
        threads = cl.direct_threads(amount=100)
    except Exception:
        return []
    group_ids = []
    for t in threads:
        try:
            if getattr(t, "is_group", False) and len(t.users) >= 2:
                group_ids.append(t.id)
        except Exception:
            continue
    log_line(f"🕸️ GCS - {GREEN}{len(group_ids)}{RESET}")
    return group_ids

async def api_call(func, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)

def graphql_rename(thread_id, title):
    csrf = cl.private.cookies.get("csrftoken", "")
    cl.private.headers.update({
        "X-CSRFToken": csrf,
        "Referer": f"https://www.instagram.com/direct/t/{thread_id}/"
    })
    payload = {
        "doc_id": DOC_ID,
        "variables": json.dumps({
            "thread_fbid": str(thread_id),
            "new_title": title
        })
    }
    r = cl.private.post(
        "https://www.instagram.com/api/graphql/",
        data=payload,
        timeout=10
    )
    return r.status_code == 200

def rename_thread(thread_id, title):
    try:
        cl.private_request(
            f"direct_v2/threads/{thread_id}/update_title/",
            data={"title": title}
        )
        return True
    except RateLimitError:
        return graphql_rename(thread_id, title)
    except Exception as e:
        if "rate" in str(e).lower():
            return graphql_rename(thread_id, title)
        return False

async def process_groups(group_ids):
    total = len(group_ids)
    for i, gid in enumerate(group_ids, start=1):
        try:
            msg = random.choice(MESSAGES)
            await api_call(cl.direct_send, msg, thread_ids=[gid])
            log_line(f"📨 - {i}/{total}")
            await asyncio.sleep(MSG_DELAY)
            title = random.choice(TITLES)
            success = await api_call(rename_thread, gid, title)
            if success:
                log_line(f"💠 - {title}")
            await asyncio.sleep(GROUP_DELAY)
        except LoginRequired:
            await login()
        except Exception:
            await asyncio.sleep(ERROR_COOLDOWN)

async def main():
    setup_mobile_fingerprint()
    await login()
    round_num = 1
    while True:
        groups = fetch_group_threads()
        if groups:
            await process_groups(groups)
        round_num += 1
        log_line(f"\n🥤- ROUND {round_num} (120s wait)\n")
        await asyncio.sleep(120)

if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    asyncio.run(main())
