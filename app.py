import os
import time
import uuid
import sqlite3
import random
import threading
import json
import requests
from flask import Flask, render_template_string, request, session
from flask_socketio import SocketIO, emit, join_room
import instagrapi
from instagrapi import Client

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret_key_pratik_secure_2026'

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

DB_FILE = 'raid_console_data.db'
DELAYS = [24, 45, 20, 15, 40]

# PROXY CONFIGURATION - ADD MULTIPLE PROXIES
PROXY_URLS = [
    # Free proxies (might be slow/unreliable)
    "http://eoktrcfi:kdc6a477zqf7@31.59.20.176:6754/",
    
    # Add more proxies here from free proxy sites
    # Format: "http://user:pass@ip:port/" or "http://ip:port/"
]

# Try without proxy first if no working proxy found
USE_PROXY = False  # Start with proxy disabled since the provided one is dead
CURRENT_PROXY_INDEX = 0

def test_proxy(proxy_url):
    """Test if proxy is working"""
    try:
        proxies = {
            'http': proxy_url,
            'https': proxy_url
        }
        # Try multiple test endpoints
        test_urls = [
            'https://api.ipify.org?format=json',
            'http://ip-api.com/json/',
            'https://httpbin.org/ip'
        ]
        
        for url in test_urls:
            try:
                response = requests.get(url, proxies=proxies, timeout=10)
                if response.status_code == 200:
                    print(f"✅ Proxy working! Response: {response.text[:100]}")
                    return True, response.text
            except:
                continue
        
        return False, None
    except Exception as e:
        print(f"❌ Proxy test failed: {e}")
        return False, None

def get_working_proxy():
    """Get a working proxy from the list"""
    global CURRENT_PROXY_INDEX
    
    if not PROXY_URLS:
        return None
    
    print("🔍 Testing proxies...")
    
    # Try all proxies
    for i, proxy in enumerate(PROXY_URLS):
        print(f"Testing proxy {i+1}/{len(PROXY_URLS)}: {proxy[:30]}...")
        working, _ = test_proxy(proxy)
        if working:
            CURRENT_PROXY_INDEX = i
            print(f"✅ Using working proxy: {proxy}")
            return proxy
    
    print("❌ No working proxies found! Will try without proxy.")
    return None

# Test proxy on startup
WORKING_PROXY = get_working_proxy()
if WORKING_PROXY:
    PROXY_URL = WORKING_PROXY
    USE_PROXY = True
else:
    PROXY_URL = None
    USE_PROXY = False
    print("⚠️ Running without proxy - may not work if IP is blocked")

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_raids (
            user_key TEXT PRIMARY KEY,
            session_id TEXT,
            thread_id TEXT,
            message TEXT,
            is_active INTEGER DEFAULT 0,
            sent_count INTEGER DEFAULT 0,
            failed_count INTEGER DEFAULT 0,
            username TEXT DEFAULT 'NOT LOGGED IN'
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS console_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_key TEXT,
            log_message TEXT,
            log_type TEXT,
            timestamp TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def save_log(user_key, message, log_type):
    timestamp = time.strftime('%H:%M:%S')
    conn = get_db_connection()
    conn.execute(
        'INSERT INTO console_logs (user_key, log_message, log_type, timestamp) VALUES (?, ?, ?, ?)',
        (user_key, message, log_type, timestamp)
    )
    conn.commit()
    conn.close()

active_clients = {}

def get_instagram_client(user_key, session_id):
    try:
        cl = Client()
        
        # Apply proxy if enabled
        if USE_PROXY and PROXY_URL:
            try:
                cl.set_proxy(PROXY_URL)
                print(f"✅ Using proxy: {PROXY_URL}")
            except Exception as e:
                print(f"⚠️ Proxy setup failed: {e}")
                print("🔄 Trying without proxy...")
        
        # Try login with session
        print(f"🔄 Logging in with session ID: {session_id[:15]}...")
        
        # Set timeout and retry
        cl.set_timeout(30)
        
        try:
            cl.login_by_sessionid(session_id)
        except Exception as login_err:
            print(f"Login attempt failed: {login_err}")
            # Try one more time without proxy if it failed with proxy
            if USE_PROXY and PROXY_URL:
                print("🔄 Retrying without proxy...")
                cl = Client()
                cl.set_timeout(30)
                cl.login_by_sessionid(session_id)
        
        # Verify login
        user_info = cl.account_info()
        if user_info and user_info.pk:
            print(f"✅ Login successful! User: {user_info.username} (ID: {user_info.pk})")
            session_file = f"session_{user_key}.json"
            cl.dump_settings(session_file)
            return cl, user_info
        
        print("❌ Login failed: No user info returned")
        return None, None
        
    except Exception as e:
        print(f"❌ Login error: {e}")
        return None, None

def verify_session(session_id):
    try:
        cl = Client()
        
        # Apply proxy if enabled
        if USE_PROXY and PROXY_URL:
            try:
                cl.set_proxy(PROXY_URL)
                print(f"✅ Verifying with proxy: {PROXY_URL}")
            except Exception as e:
                print(f"⚠️ Proxy setup failed: {e}")
        
        # Set timeout
        cl.set_timeout(30)
        
        print(f"🔄 Verifying session: {session_id[:15]}...")
        
        try:
            cl.login_by_sessionid(session_id)
        except Exception as login_err:
            print(f"Login attempt failed: {login_err}")
            # Try without proxy if it failed with proxy
            if USE_PROXY and PROXY_URL:
                print("🔄 Retrying verification without proxy...")
                cl = Client()
                cl.set_timeout(30)
                cl.login_by_sessionid(session_id)
        
        user_info = cl.account_info()
        
        if user_info and user_info.pk:
            print(f"✅ Session valid! User: {user_info.username}")
            return True, user_info.username
        
        print("❌ Session invalid: No user info")
        return False, None
        
    except instagrapi.exceptions.LoginRequired as e:
        print(f"❌ Login required error: {e}")
        return False, None
    except instagrapi.exceptions.PleaseWaitFewMinutes as e:
        print(f"⏳ Rate limited: {e}")
        return False, None
    except instagrapi.exceptions.ChallengeRequired as e:
        print(f"🔒 Challenge required: {e}")
        print("💡 You need to complete a challenge in the browser first")
        return False, None
    except instagrapi.exceptions.ClientLoginError as e:
        print(f"❌ Login error: {e}")
        return False, None
    except Exception as e:
        print(f"❌ Verification error: {e}")
        return False, None

# HTML_TEMPLATE - Same as before (keeping it short for the response)
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PRATIK - SPAM PANEL</title>
    <script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; font-family: 'Consolas', monospace; }
        body { background-color: #0a0a0a; color: #0f0; min-height: 100vh; padding: 20px; overflow-x: hidden; }
        
        .header {
            position: relative; text-align: center; margin-bottom: 15px; padding: 20px 70px;
            background: linear-gradient(90deg, #ff0000, #ff7300, #fffb00, #48ff00, #00ffd5, #002bff, #7a00ff, #ff00c8, #ff0000);
            background-size: 400% 400%; animation: gradient 15s ease infinite; border-radius: 10px;
            box-shadow: 0 0 30px rgba(255, 0, 0, 0.5);
        }
        @keyframes gradient { 0% { background-position: 0% 50%; } 50% { background-position: 100% 50%; } 100% { background-position: 0% 50%; } }
        
        .icon-btn {
            position: absolute; top: 50%; transform: translateY(-50%); background: rgba(0,0,0,0.6);
            color: #00ff00; border: 2px solid #00ff00; border-radius: 8px; width: 50px; height: 50px;
            font-size: 1.8rem; cursor: pointer; display: flex; align-items: center; justify-content: center;
            transition: all 0.3s ease; z-index: 10;
        }
        .icon-btn:hover { background: #00ff00; color: #000; box-shadow: 0 0 15px #00ff00; }
        .btn-menu { left: 15px; }
        .btn-add { right: 15px; }

        .tabs-bar { display: flex; gap: 10px; margin-bottom: 20px; overflow-x: auto; padding-bottom: 5px; }
        .tab-item {
            background: #111; color: #888; border: 1px solid #333; padding: 8px 16px; border-radius: 5px;
            cursor: pointer; white-space: nowrap; display: flex; align-items: center; gap: 10px;
        }
        .tab-item.active { color: #00ff00; border-color: #00ff00; background: #1e1e1e; box-shadow: 0 0 10px rgba(0, 255, 0, 0.2); }
        .tab-item .close-tab { color: #ff0000; font-weight: bold; }

        .glowing-text { font-size: 3.5rem; font-weight: 900; color: white; text-shadow: 0 0 10px #ff0000, 0 0 20px #ff0000; letter-spacing: 2px; }

        .drawer {
            position: fixed; top: 0; left: -320px; width: 300px; height: 100%; background-color: #111;
            border-right: 2px solid #00ff00; box-shadow: 5px 0 25px rgba(0, 255, 0, 0.3); transition: left 0.3s ease; z-index: 100; padding: 20px;
        }
        .drawer.open { left: 0; }
        .drawer-header { display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #00ff00; padding-bottom: 10px; margin-bottom: 20px; }
        .drawer-close { background: none; border: none; color: #ff0000; font-size: 1.5rem; cursor: pointer; }
        .pages-list { list-style: none; max-height: calc(100vh - 120px); overflow-y: auto; }
        .pages-list li { background: #222; margin-bottom: 10px; padding: 12px; border-radius: 5px; border: 1px solid #444; cursor: pointer; display: flex; justify-content: space-between; align-items: center; }
        .pages-list li:hover { border-color: #00ff00; }

        .container { display: flex; gap: 20px; max-width: 1800px; margin: 0 auto; }
        .left-panel { flex: 1; background-color: #111; border-radius: 10px; padding: 25px; border: 2px solid #ff0000; box-shadow: 0 0 20px rgba(255, 0, 0, 0.3); }
        .right-panel { flex: 2; background-color: #111; border-radius: 10px; padding: 25px; border: 2px solid #00ff00; box-shadow: 0 0 20px rgba(0, 255, 0, 0.3); min-height: 600px; }
        .panel-title { color: #ff0000; font-size: 1.8rem; margin-bottom: 20px; text-align: center; border-bottom: 2px solid #ff0000; text-shadow: 0 0 10px rgba(255, 0, 0, 0.5); }
        .panel-title.green { color: #00ff00; border-bottom-color: #00ff00; text-shadow: 0 0 10px rgba(0, 255, 0, 0.5); }
        
        .form-group { background-color: #222; padding: 20px; border-radius: 10px; margin-bottom: 20px; }
        .input-group { margin-bottom: 15px; }
        .input-group label { display: block; color: #00ff00; margin-bottom: 8px; font-weight: bold; }
        .input-group input, .input-group textarea { width: 100%; padding: 12px; background: #000; border: 1px solid #444; color: #0f0; border-radius: 5px; outline: none; }
        .input-group input:focus, .input-group textarea:focus { border-color: #00ff00; }
        textarea { resize: vertical; min-height: 100px; }
        
        .button-group { display: flex; gap: 15px; margin-top: 15px; }
        .btn { flex: 1; padding: 15px; border: none; border-radius: 5px; font-size: 1.1rem; font-weight: bold; cursor: pointer; text-transform: uppercase; letter-spacing: 1px; }
        .btn-login { background: linear-gradient(45deg, #ff0000, #ff4400); color: white; }
        .btn-start { background: linear-gradient(45deg, #00ff00, #00cc00); color: black; }
        .btn-stop { background: linear-gradient(45deg, #ff4444, #ff0000); color: white; }
        
        .stats { background-color: #222; padding: 20px; border-radius: 10px; margin-top: 20px; border: 1px solid #444; }
        .stat-item { display: flex; justify-content: space-between; margin-bottom: 10px; color: #0f0; font-size: 1.1rem; }
        
        .console-container { background-color: #000; border-radius: 10px; padding: 20px; height: 500px; overflow-y: auto; border: 2px solid #333; }
        .console-line { margin-bottom: 8px; padding-left: 10px; border-left: 3px solid transparent; animation: fadeIn 0.5s; }
        .console-line.success { color: #00ff00; border-left-color: #00ff00; }
        .console-line.error { color: #ff0000; border-left-color: #ff0000; }
        .console-line.info { color: #00ffff; border-left-color: #00ffff; }
        .console-line.warning { color: #ffff00; border-left-color: #ffff00; }
        @keyframes fadeIn { from { opacity: 0; transform: translateX(-10px); } to { opacity: 1; transform: translateX(0); } }
        
        .status-indicator { display: inline-block; width: 12px; height: 12px; border-radius: 50%; margin-right: 8px; }
        .status-online { background-color: #00ff00; box-shadow: 0 0 10px #00ff00; }
        .status-offline { background-color: #ff0000; box-shadow: 0 0 10px #ff0000; }
        
        .proxy-status { padding: 10px; margin-bottom: 10px; border-radius: 5px; font-size: 0.9rem; }
        .proxy-status.success { background: #003300; border: 1px solid #00ff00; color: #00ff00; }
        .proxy-status.error { background: #330000; border: 1px solid #ff0000; color: #ff0000; }
        
        @media (max-width: 1200px) { .container { flex-direction: column; } .glowing-text { font-size: 2.5rem; } }
    </style>
</head>
<body>
    <div class="header">
        <button class="icon-btn btn-menu" onclick="toggleDrawer()">☰</button>
        <h1 class="glowing-text">PRATIK SPAM PANEL</h1>
        <button class="icon-btn btn-add" onclick="createNewPage(true)">+</button>
    </div>

    <div class="tabs-bar" id="tabsBar"></div>

    <div class="drawer" id="pagesDrawer">
        <div class="drawer-header">
            <h3>PAGES CREATED (<span id="totalPagesCount">0</span>)</h3>
            <button class="drawer-close" onclick="toggleDrawer()">✖</button>
        </div>
        <ul class="pages-list" id="pagesList"></ul>
    </div>
    
    <div class="container">
        <div class="left-panel">
            <h2 class="panel-title">CONTROL PANEL</h2>
            <div id="proxyStatus" class="proxy-status error">
                ⚠️ PROXY STATUS: DISABLED/DOWN - Running without proxy
            </div>
            <div class="form-group">
                <div class="input-group">
                    <label for="sessionId">SESSION ID</label>
                    <input type="text" id="sessionId" placeholder="Enter Instagram Session ID">
                </div>
                <div class="button-group">
                    <button class="btn btn-login" onclick="login()">LOGIN</button>
                    <button class="btn btn-stop" onclick="logout()">LOGOUT</button>
                </div>
            </div>
            
            <div class="form-group">
                <div class="input-group">
                    <label for="threadId">THREAD ID</label>
                    <input type="text" id="threadId" placeholder="Enter Thread ID">
                </div>
                <div class="input-group">
                    <label for="message">MESSAGE</label>
                    <textarea id="message" placeholder="Enter message..."></textarea>
                </div>
                <div class="button-group">
                    <button class="btn btn-start" onclick="startSending()">START RAID</button>
                    <button class="btn btn-stop" onclick="stopSending()">STOP RAID</button>
                </div>
            </div>
            
            <div class="stats">
                <div id="statusDisplay"><span class="status-indicator status-offline"></span> STATUS: OFFLINE</div>
                <div id="usernameDisplay">USERNAME: NOT LOGGED IN</div>
                <hr style="border-color:#444; margin: 15px 0;">
                <div class="stat-item"><span>MESSAGES SENT:</span><span id="sentCount">0</span></div>
                <div class="stat-item"><span>FAILED:</span><span id="failedCount">0</span></div>
                <div class="stat-item"><span>RAID STATUS:</span><span id="raidStatus">IDLE</span></div>
            </div>
        </div>
        
        <div class="right-panel">
            <h2 class="panel-title green">LIVE CONSOLE</h2>
            <div class="console-container" id="console"></div>
        </div>
    </div>
    
    <script>
        let socket = io();
        let storedPages = JSON.parse(localStorage.getItem('pratik_pages') || '[]');
        let activePageId = localStorage.getItem('pratik_active_page');
        
        let userKey = localStorage.getItem('pratik_user_key');
        if (!userKey) {
            userKey = 'user_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
            localStorage.setItem('pratik_user_key', userKey);
        }
        
        let currentPageId = activePageId || ('Page_' + Date.now());
        
        if (storedPages.length === 0) {
            createNewPage(false);
        } else {
            if (!activePageId) {
                activePageId = storedPages[0].id;
                localStorage.setItem('pratik_active_page', activePageId);
            }
            currentPageId = activePageId;
            renderTabs();
            renderStoredPagesList();
        }

        socket.on('connect', function() {
            socket.emit('register_page', { 
                page_id: currentPageId,
                user_key: userKey 
            });
        });

        function createNewPage(userClicked = true) {
            const pageId = 'Page_' + Date.now();
            const newPage = {
                id: pageId,
                name: 'Console #' + (storedPages.length + 1),
                created: new Date().toLocaleTimeString()
            };
            storedPages.push(newPage);
            activePageId = pageId;
            currentPageId = pageId;
            savePages();
            renderTabs();
            renderStoredPagesList();
            socket.emit('register_page', { 
                page_id: pageId,
                user_key: userKey 
            });
        }

        function switchPage(pageId) {
            activePageId = pageId;
            currentPageId = pageId;
            localStorage.setItem('pratik_active_page', activePageId);
            renderTabs();
            renderStoredPagesList();
            socket.emit('register_page', { 
                page_id: pageId,
                user_key: userKey 
            });
            document.getElementById('console').innerHTML = '';
            socket.emit('request_page_data', { 
                page_id: pageId,
                user_key: userKey 
            });
        }

        function removePage(pageId, event) {
            if (event) event.stopPropagation();
            if (storedPages.length <= 1) return;
            storedPages = storedPages.filter(p => p.id !== pageId);
            if (activePageId === pageId) {
                activePageId = storedPages[0].id;
                currentPageId = activePageId;
                localStorage.setItem('pratik_active_page', activePageId);
            }
            savePages();
            renderTabs();
            renderStoredPagesList();
            socket.emit('unregister_page', { 
                page_id: pageId,
                user_key: userKey 
            });
        }

        function savePages() {
            localStorage.setItem('pratik_pages', JSON.stringify(storedPages));
            localStorage.setItem('pratik_active_page', activePageId);
        }

        function renderTabs() {
            const tabsBar = document.getElementById('tabsBar');
            tabsBar.innerHTML = storedPages.map(page => `
                <div class="tab-item ${page.id === activePageId ? 'active' : ''}" onclick="switchPage('${page.id}')">
                    <span>${page.name}</span>
                    <span class="close-tab" onclick="removePage('${page.id}', event)">✖</span>
                </div>
            `).join('');
        }

        function renderStoredPagesList() {
            const list = document.getElementById('pagesList');
            document.getElementById('totalPagesCount').textContent = storedPages.length;
            list.innerHTML = storedPages.map(page => `
                <li onclick="switchPage('${page.id}')">
                    <div>
                        <strong>${page.name}</strong><br>
                        <small style="color:#777">Created: ${page.created}</small>
                    </div>
                    ${storedPages.length > 1 ? `<span style="color:#ff0000;" onclick="removePage('${page.id}', event)">Delete</span>` : ''}
                </li>
            `).join('');
        }

        function toggleDrawer() {
            document.getElementById('pagesDrawer').classList.toggle('open');
        }

        socket.on('init_state', function(data) {
            if (data.page_id && data.page_id !== currentPageId) return;
            if (data.user_key && data.user_key !== userKey) return;
            
            document.getElementById('sessionId').value = data.session_id || '';
            document.getElementById('threadId').value = data.thread_id || '';
            if (data.message) document.getElementById('message').value = data.message;
            
            document.getElementById('sentCount').textContent = data.sent_count;
            document.getElementById('failedCount').textContent = data.failed_count;
            document.getElementById('raidStatus').textContent = data.is_active ? 'RUNNING' : 'STOPPED';
            
            if (data.username && data.username !== 'NOT LOGGED IN') {
                document.getElementById('statusDisplay').innerHTML = '<span class="status-indicator status-online"></span> STATUS: ONLINE';
                document.getElementById('usernameDisplay').textContent = 'USERNAME: ' + data.username;
            }
            
            const consoleDiv = document.getElementById('console');
            consoleDiv.innerHTML = '';
            data.logs.forEach(log => {
                addConsoleMessage(`[${log.timestamp}] ${log.log_message}`, log.log_type, false);
            });
            consoleDiv.scrollTop = consoleDiv.scrollHeight;
        });

        socket.on('console_message', function(data) {
            if (data.page_id && data.page_id !== currentPageId) return;
            if (data.user_key && data.user_key !== userKey) return;
            addConsoleMessage(`[${data.timestamp}] ${data.message}`, data.type, true);
        });

        socket.on('update_stats', function(data) {
            if (data.page_id && data.page_id !== currentPageId) return;
            if (data.user_key && data.user_key !== userKey) return;
            if (data.sent !== undefined) document.getElementById('sentCount').textContent = data.sent;
            if (data.failed !== undefined) document.getElementById('failedCount').textContent = data.failed;
            if (data.raid_status) document.getElementById('raidStatus').textContent = data.raid_status;
        });

        socket.on('login_status', function(data) {
            if (data.page_id && data.page_id !== currentPageId) return;
            if (data.user_key && data.user_key !== userKey) return;
            if (data.success) {
                document.getElementById('statusDisplay').innerHTML = '<span class="status-indicator status-online"></span> STATUS: ONLINE';
                document.getElementById('usernameDisplay').textContent = 'USERNAME: ' + data.username;
            }
        });

        socket.on('proxy_status', function(data) {
            const statusDiv = document.getElementById('proxyStatus');
            if (data.working) {
                statusDiv.className = 'proxy-status success';
                statusDiv.textContent = '✅ PROXY STATUS: WORKING - ' + data.proxy;
            } else {
                statusDiv.className = 'proxy-status error';
                statusDiv.textContent = '⚠️ PROXY STATUS: DISABLED/DOWN - Running without proxy';
            }
        });

        function addConsoleMessage(message, type = 'info', scroll = true) {
            const consoleDiv = document.getElementById('console');
            const messageDiv = document.createElement('div');
            messageDiv.className = `console-line ${type}`;
            messageDiv.textContent = message;
            consoleDiv.appendChild(messageDiv);
            if (scroll) consoleDiv.scrollTop = consoleDiv.scrollHeight;
        }

        function login() {
            const sid = document.getElementById('sessionId').value.trim();
            if (sid) {
                socket.emit('login', { 
                    session_id: sid, 
                    page_id: currentPageId,
                    user_key: userKey 
                });
            }
        }

        function logout() {
            socket.emit('logout', { 
                page_id: currentPageId,
                user_key: userKey 
            });
            document.getElementById('statusDisplay').innerHTML = '<span class="status-indicator status-offline"></span> STATUS: OFFLINE';
            document.getElementById('usernameDisplay').textContent = 'USERNAME: NOT LOGGED IN';
        }

        function startSending() {
            const threadId = document.getElementById('threadId').value.trim();
            const message = document.getElementById('message').value.trim();
            if (threadId && message) {
                socket.emit('start_raid', { 
                    thread_id: threadId, 
                    message: message,
                    page_id: currentPageId,
                    user_key: userKey 
                });
            }
        }

        function stopSending() {
            socket.emit('stop_raid', { 
                page_id: currentPageId,
                user_key: userKey 
            });
        }
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

page_data = {}

@socketio.on('connect')
def handle_connect():
    print("Client connected")
    # Send proxy status
    emit('proxy_status', {
        'working': USE_PROXY and PROXY_URL is not None,
        'proxy': PROXY_URL if PROXY_URL else 'None'
    })

@socketio.on('register_page')
def handle_register_page(data):
    user_key = data.get('user_key')
    page_id = data.get('page_id')
    if not user_key or not page_id:
        return
    page_key = f"{user_key}_{page_id}"
    
    if page_key not in page_data:
        page_data[page_key] = {
            'user_key': user_key,
            'page_id': page_id,
            'session_id': '',
            'thread_id': '',
            'message': '',
            'is_active': False,
            'sent_count': 0,
            'failed_count': 0,
            'username': 'NOT LOGGED IN'
        }
    
    join_room(page_key)
    
    conn = get_db_connection()
    user_data = conn.execute('SELECT * FROM user_raids WHERE user_key = ?', (page_key,)).fetchone()
    logs = conn.execute('SELECT log_message, log_type, timestamp FROM console_logs WHERE user_key = ? ORDER BY id ASC', (page_key,)).fetchall()
    conn.close()
    
    if user_data:
        emit('init_state', {
            'page_id': page_id,
            'user_key': user_key,
            'session_id': user_data['session_id'] or '',
            'thread_id': user_data['thread_id'] or '',
            'message': user_data['message'] or '',
            'is_active': bool(user_data['is_active']),
            'sent_count': user_data['sent_count'] or 0,
            'failed_count': user_data['failed_count'] or 0,
            'username': user_data['username'] or 'NOT LOGGED IN',
            'logs': [dict(log) for log in logs]
        }, room=page_key)
    else:
        emit('init_state', {
            'page_id': page_id,
            'user_key': user_key,
            'session_id': '',
            'thread_id': '',
            'message': '',
            'is_active': False,
            'sent_count': 0,
            'failed_count': 0,
            'username': 'NOT LOGGED IN',
            'logs': []
        }, room=page_key)

@socketio.on('request_page_data')
def handle_request_page_data(data):
    user_key = data.get('user_key')
    page_id = data.get('page_id')
    page_key = f"{user_key}_{page_id}"
    
    conn = get_db_connection()
    user_data = conn.execute('SELECT * FROM user_raids WHERE user_key = ?', (page_key,)).fetchone()
    logs = conn.execute('SELECT log_message, log_type, timestamp FROM console_logs WHERE user_key = ? ORDER BY id ASC', (page_key,)).fetchall()
    conn.close()
    
    if user_data:
        emit('init_state', {
            'page_id': page_id,
            'user_key': user_key,
            'session_id': user_data['session_id'] or '',
            'thread_id': user_data['thread_id'] or '',
            'message': user_data['message'] or '',
            'is_active': bool(user_data['is_active']),
            'sent_count': user_data['sent_count'] or 0,
            'failed_count': user_data['failed_count'] or 0,
            'username': user_data['username'] or 'NOT LOGGED IN',
            'logs': [dict(log) for log in logs]
        }, room=page_key)

@socketio.on('unregister_page')
def handle_unregister_page(data):
    user_key = data.get('user_key')
    page_id = data.get('page_id')
    page_key = f"{user_key}_{page_id}"
    if page_key in page_data:
        del page_data[page_key]
    if page_key in active_clients:
        del active_clients[page_key]

@socketio.on('login')
def handle_login(data):
    user_key = data.get('user_key')
    page_id = data.get('page_id')
    session_id = data.get('session_id')
    page_key = f"{user_key}_{page_id}"
    
    if not session_id:
        msg = "Please enter a session ID"
        save_log(page_key, msg, 'error')
        emit('console_message', {'message': msg, 'type': 'error', 'timestamp': time.strftime('%H:%M:%S'), 'page_id': page_id, 'user_key': user_key}, room=page_key)
        return
    
    try:
        # Try login with session
        is_valid, username = verify_session(session_id)
        
        if not is_valid:
            msg = "❌ Session ID is invalid or expired.\n\n💡 TIPS:\n1. Get a fresh session ID from your browser\n2. Make sure you have a working proxy\n3. Try logging in through browser first"
            save_log(page_key, msg, 'error')
            emit('login_status', {'success': False, 'page_id': page_id, 'user_key': user_key}, room=page_key)
            emit('console_message', {'message': msg, 'type': 'error', 'timestamp': time.strftime('%H:%M:%S'), 'page_id': page_id, 'user_key': user_key}, room=page_key)
            return
        
        cl, user_info = get_instagram_client(page_key, session_id)
        if not cl or not user_info:
            msg = "❌ Failed to create Instagram client.\n\n💡 TIPS:\n1. Try a different proxy\n2. Check if Instagram is blocking your IP\n3. Try using a VPN"
            save_log(page_key, msg, 'error')
            emit('login_status', {'success': False, 'page_id': page_id, 'user_key': user_key}, room=page_key)
            emit('console_message', {'message': msg, 'type': 'error', 'timestamp': time.strftime('%H:%M:%S'), 'page_id': page_id, 'user_key': user_key}, room=page_key)
            return
        
        active_clients[page_key] = cl
        
        if page_key in page_data:
            page_data[page_key]['session_id'] = session_id
            page_data[page_key]['username'] = user_info.username
        
        conn = get_db_connection()
        conn.execute('''
            INSERT INTO user_raids (user_key, session_id, username) VALUES (?, ?, ?)
            ON CONFLICT(user_key) DO UPDATE SET session_id=?, username=?
        ''', (page_key, session_id, user_info.username, session_id, user_info.username))
        conn.commit()
        conn.close()
        
        msg = f"✅ LOGIN SUCCESS: {user_info.username}"
        save_log(page_key, msg, 'success')
        emit('login_status', {'success': True, 'username': user_info.username, 'page_id': page_id, 'user_key': user_key}, room=page_key)
        emit('console_message', {'message': msg, 'type': 'success', 'timestamp': time.strftime('%H:%M:%S'), 'page_id': page_id, 'user_key': user_key}, room=page_key)
        
    except Exception as e:
        msg = f"❌ LOGIN FAILED: {str(e)}"
        save_log(page_key, msg, 'error')
        emit('login_status', {'success': False, 'page_id': page_id, 'user_key': user_key}, room=page_key)
        emit('console_message', {'message': msg, 'type': 'error', 'timestamp': time.strftime('%H:%M:%S'), 'page_id': page_id, 'user_key': user_key}, room=page_key)

@socketio.on('logout')
def handle_logout(data):
    user_key = data.get('user_key')
    page_id = data.get('page_id')
    page_key = f"{user_key}_{page_id}"
    
    if page_key in active_clients:
        del active_clients[page_key]
    
    session_file = f"session_{page_key}.json"
    if os.path.exists(session_file):
        try:
            os.remove(session_file)
        except:
            pass
    
    if page_key in page_data:
        page_data[page_key]['session_id'] = ''
        page_data[page_key]['username'] = 'NOT LOGGED IN'
    
    conn = get_db_connection()
    conn.execute('UPDATE user_raids SET username = "NOT LOGGED IN", session_id = "" WHERE user_key = ?', (page_key,))
    conn.commit()
    conn.close()
    
    msg = "Logged out"
    save_log(page_key, msg, 'info')
    emit('console_message', {'message': msg, 'type': 'info', 'timestamp': time.strftime('%H:%M:%S'), 'page_id': page_id, 'user_key': user_key}, room=page_key)

@socketio.on('start_raid')
def handle_start_raid(data):
    user_key = data.get('user_key')
    page_id = data.get('page_id')
    thread_id = data.get('thread_id')
    message_text = data.get('message')
    page_key = f"{user_key}_{page_id}"

    conn = get_db_connection()
    user_data = conn.execute('SELECT * FROM user_raids WHERE user_key = ?', (page_key,)).fetchone()
    
    if not user_data or not user_data['session_id']:
        conn.close()
        msg = "❌ Please login first."
        save_log(page_key, msg, 'error')
        emit('console_message', {'message': msg, 'type': 'error', 'timestamp': time.strftime('%H:%M:%S'), 'page_id': page_id, 'user_key': user_key}, room=page_key)
        return

    if user_data['is_active']:
        conn.close()
        msg = "⚠️ Raid is already running."
        save_log(page_key, msg, 'warning')
        emit('console_message', {'message': msg, 'type': 'warning', 'timestamp': time.strftime('%H:%M:%S'), 'page_id': page_id, 'user_key': user_key}, room=page_key)
        return

    conn.execute('''
        UPDATE user_raids SET thread_id=?, message=?, is_active=1 WHERE user_key=?
    ''', (thread_id, message_text, page_key))
    conn.commit()
    conn.close()

    if page_key in page_data:
        page_data[page_key]['thread_id'] = thread_id
        page_data[page_key]['message'] = message_text
        page_data[page_key]['is_active'] = True

    msg = f"🚀 Starting raid on thread: {thread_id}"
    save_log(page_key, msg, 'warning')
    emit('console_message', {'message': msg, 'type': 'warning', 'timestamp': time.strftime('%H:%M:%S'), 'page_id': page_id, 'user_key': user_key}, room=page_key)
    emit('update_stats', {'raid_status': 'RUNNING', 'page_id': page_id, 'user_key': user_key}, room=page_key)

    threading.Thread(target=run_raid, args=(page_key, thread_id, message_text, page_id, user_key)).start()

def run_raid(page_key, target_thread, target_msg, page_id, user_key):
    counter = 0
    while True:
        conn = get_db_connection()
        status_row = conn.execute('SELECT is_active, session_id, sent_count, failed_count FROM user_raids WHERE user_key = ?', (page_key,)).fetchone()
        
        if not status_row or not status_row['is_active']:
            conn.close()
            break

        cl = active_clients.get(page_key)
        if not cl:
            try:
                cl, user_info = get_instagram_client(page_key, status_row['session_id'])
                if cl and user_info:
                    active_clients[page_key] = cl
                else:
                    raise Exception("Restore failed")
            except Exception as ex:
                conn.execute('UPDATE user_raids SET failed_count = failed_count + 1 WHERE user_key = ?', (page_key,))
                conn.commit()
                conn.close()
                err_msg = f"❌ Session restore failed: {str(ex)}"
                save_log(page_key, err_msg, 'error')
                socketio.emit('console_message', {'message': err_msg, 'type': 'error', 'timestamp': time.strftime('%H:%M:%S'), 'page_id': page_id, 'user_key': user_key}, room=page_key)
                time.sleep(10)
                continue

        try:
            counter += 1
            cl.direct_send(target_msg, thread_ids=[target_thread])
            conn.execute('UPDATE user_raids SET sent_count = sent_count + 1 WHERE user_key = ?', (page_key,))
            conn.commit()
            
            updated_sent = status_row['sent_count'] + 1
            out_msg = f"✅ Sent #{counter} -> {target_msg[:30]}..."
            save_log(page_key, out_msg, 'success')
            
            socketio.emit('console_message', {'message': out_msg, 'type': 'success', 'timestamp': time.strftime('%H:%M:%S'), 'page_id': page_id, 'user_key': user_key}, room=page_key)
            socketio.emit('update_stats', {'sent': updated_sent, 'page_id': page_id, 'user_key': user_key}, room=page_key)
        except Exception as e:
            conn.execute('UPDATE user_raids SET failed_count = failed_count + 1 WHERE user_key = ?', (page_key,))
            conn.commit()
            
            updated_failed = status_row['failed_count'] + 1
            err_msg = f"❌ Failed to send: {str(e)}"
            save_log(page_key, err_msg, 'error')
            
            socketio.emit('console_message', {'message': err_msg, 'type': 'error', 'timestamp': time.strftime('%H:%M:%S'), 'page_id': page_id, 'user_key': user_key}, room=page_key)
            socketio.emit('update_stats', {'failed': updated_failed, 'page_id': page_id, 'user_key': user_key}, room=page_key)

        conn.close()

        current_delay = random.choice(DELAYS)
        for _ in range(int(current_delay)):
            check_conn = get_db_connection()
            check_active = check_conn.execute('SELECT is_active FROM user_raids WHERE user_key = ?', (page_key,)).fetchone()
            check_conn.close()
            if not check_active or not check_active['is_active']:
                socketio.emit('update_stats', {'raid_status': 'STOPPED', 'page_id': page_id, 'user_key': user_key}, room=page_key)
                return
            time.sleep(1)

    socketio.emit('update_stats', {'raid_status': 'STOPPED', 'page_id': page_id, 'user_key': user_key}, room=page_key)

@socketio.on('stop_raid')
def handle_stop_raid(data):
    user_key = data.get('user_key')
    page_id = data.get('page_id')
    page_key = f"{user_key}_{page_id}"
    
    conn = get_db_connection()
    conn.execute('UPDATE user_raids SET is_active = 0 WHERE user_key = ?', (page_key,))
    conn.commit()
    conn.close()
    
    if page_key in page_data:
        page_data[page_key]['is_active'] = False
    
    msg = "🛑 Stopping raid..."
    save_log(page_key, msg, 'warning')
    emit('console_message', {'message': msg, 'type': 'warning', 'timestamp': time.strftime('%H:%M:%S'), 'page_id': page_id, 'user_key': user_key}, room=page_key)
    emit('update_stats', {'raid_status': 'STOPPED', 'page_id': page_id, 'user_key': user_key}, room=page_key)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    socketio.run(app, host='0.0.0.0', port=port, debug=True)
