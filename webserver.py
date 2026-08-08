#!/usr/bin/env python3
"""
webserver.py - Standalone Web Log Dashboard
Chạy độc lập, không phụ thuộc pipeline.
Luôn online dù pipeline có crash.
"""
import os
import csv
import json
import threading
from pathlib import Path
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

BASE_DIR = Path(__file__).parent
PORT     = int(os.environ.get("WEB_PORT", 5000))

LOG_FILES = {
    "acc1":       BASE_DIR / "pipeline_acc1.log",
    "acc2":       BASE_DIR / "pipeline_acc2.log",
    "acc3":       BASE_DIR / "pipeline_acc3.log",
    "dispatcher": BASE_DIR / "pipeline_dispatcher.log",
}
CSV_PATH = BASE_DIR / "telegram_media_downloader" / "full_hoahoc.csv"

def read_tail(path: Path, max_lines: int = 600) -> str:
    if not path.exists():
        return f"(Chua co log: {path.name})"
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return "".join(lines[-max_lines:])
    except Exception as e:
        return f"(Loi doc log: {e})"

HTML = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<title>Pipeline Monitor - LIVE</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0d1117;color:#c9d1d9;font-family:ui-sans-serif,system-ui,sans-serif;display:flex;flex-direction:column;height:100vh;padding:12px;gap:8px}
h1{color:#58a6ff;font-size:17px;flex-shrink:0}
.bar{display:flex;gap:6px;align-items:center;flex-shrink:0;flex-wrap:wrap}
.tab{padding:7px 16px;border-radius:8px 8px 0 0;cursor:pointer;font-size:13px;font-weight:700;border:1px solid #30363d;border-bottom:none;background:#161b22;color:#8b949e;transition:.15s}
.tab.active{background:#1f2937;color:#f0f6fc;border-color:#58a6ff}
.tab.t1{border-top:2px solid #3fb950}
.tab.t2{border-top:2px solid #58a6ff}
.tab.t3{border-top:2px solid #f78166}
.tab.t4{border-top:2px solid #d2a8ff}
.tab.csv{border-top:2px solid #e3b341}
.panel{display:none;background:#161b22;border:1px solid #30363d;border-radius:0 8px 8px 8px;padding:12px;flex:1;overflow-y:auto;white-space:pre-wrap;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12.5px;line-height:1.6;min-height:0}
.panel.active{display:block}
.tabs{display:flex;gap:4px}
button{background:#238636;color:#fff;border:0;padding:6px 14px;border-radius:6px;cursor:pointer;font-weight:700;font-size:12px}
button:hover{background:#2ea043}
.sec{background:#21262d!important;border:1px solid #30363d;color:#c9d1d9}
.sec:hover{background:#30363d!important}
label{font-size:12px;color:#8b949e;cursor:pointer;display:flex;align-items:center;gap:4px;margin-left:auto}
.badge{padding:2px 8px;border-radius:12px;font-size:11px;font-weight:700;background:#1a4731;color:#3fb950}
.S{color:#3fb950;font-weight:700}.E{color:#f85149;font-weight:700}.W{color:#d29922}.I{color:#58a6ff}
#csvWrap table{border-collapse:collapse;width:100%;font-size:12px}
#csvWrap th,#csvWrap td{border:1px solid #30363d;padding:4px 8px;text-align:left}
#csvWrap th{background:#21262d;color:#8b949e;position:sticky;top:0}
#csvWrap tr:hover td{background:#1f2937}
.st-COMPLETED{color:#3fb950;font-weight:700}
.st-FORWARDED_ACC2,.st-FORWARDED_ACC3{color:#58a6ff}
.st-FAILED_DOWNLOAD,.st-FAILED_RCLONE,.st-FAILED_EXTRACT{color:#f85149}
.st-PENDING{color:#8b949e}
</style>
</head>
<body>
<h1>&#x1F680; Pipeline Monitor &nbsp;<span class="badge">LIVE</span></h1>
<div class="bar">
  <button onclick="fetchAll()">&#x1F504; Lam moi</button>
  <button class="sec" onclick="dl('/dl/csv')">&#x1F4CA; CSV</button>
  <button class="sec" onclick="dl('/dl/acc1')">&#x1F4E5; Log Acc1</button>
  <label><input type="checkbox" id="as" checked> Tu cuon xuong</label>
</div>
<div class="tabs">
  <div class="tab t1 active" onclick="sw(0)">&#x1F7E2; Acc 1 (Master)</div>
  <div class="tab t2"        onclick="sw(1)">&#x1F535; Acc 2 (Relay)</div>
  <div class="tab t3"        onclick="sw(2)">&#x1F7E0; Acc 3 (Relay)</div>
  <div class="tab t4"        onclick="sw(3)">&#x1F6F0;&#xFE0F; Dispatcher</div>
  <div class="tab csv"       onclick="sw(4)">&#x1F4CA; CSV Status</div>
</div>
<div class="panel active" id="p0">Dang tai...</div>
<div class="panel"        id="p1">Dang tai...</div>
<div class="panel"        id="p2">Dang tai...</div>
<div class="panel"        id="p3">Dang tai...</div>
<div class="panel"        id="p4"><div id="csvWrap">Dang tai CSV...</div></div>

<script>
var cur=0;
function colorize(t){return t.replace(/\\[SUCCESS\\]/g,'<span class="S">[SUCCESS]</span>').replace(/\\[ERROR\\]/g,'<span class="E">[ERROR]</span>').replace(/\\[WARN\\]/g,'<span class="W">[WARN]</span>').replace(/\\[INFO\\]/g,'<span class="I">[INFO]</span>');}
function sw(i){document.querySelectorAll('.tab').forEach(function(t,j){t.classList.toggle('active',i===j)});document.querySelectorAll('.panel').forEach(function(p,j){p.classList.toggle('active',i===j)});cur=i;}
async function fp(url,pid){try{var r=await fetch(url);var t=await r.text();var p=document.getElementById(pid);p.innerHTML=colorize(t.replace(/</g,'&lt;').replace(/>/g,'&gt;'));if(document.getElementById('as').checked&&pid==='p'+cur)p.scrollTop=p.scrollHeight;}catch(e){}}
async function fetchCSV(){try{var r=await fetch('/api/csv');var rows=await r.json();if(!rows.length){document.getElementById('csvWrap').textContent='(Chua co du lieu)';return;}var cols=Object.keys(rows[0]);var html='<table><tr>'+cols.map(function(c){return '<th>'+c+'</th>';}).join('')+'</tr>';rows.forEach(function(row){var st=(row.status||'').replace(/\\s/g,'_');html+='<tr>'+cols.map(function(c){return '<td class="'+(c==='status'?'st-'+st:'')+'">'+(row[c]||'')+'</td>';}).join('')+'</tr>';});html+='</table>';document.getElementById('csvWrap').innerHTML=html;}catch(e){}}
function dl(url){var a=document.createElement('a');a.href=url;a.click();}
function fetchAll(){fp('/api/logs/acc1','p0');fp('/api/logs/acc2','p1');fp('/api/logs/acc3','p2');fp('/api/logs/dispatcher','p3');fetchCSV();}
fetchAll();
setInterval(fetchAll,2500);
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def send_text(self, content, ctype="text/plain; charset=utf-8"):
        if isinstance(content, str):
            data = content.encode("utf-8")
        else:
            data = content
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        p = self.path.split("?")[0]
        if p in ("/", "/index.html"):
            self.send_text(HTML, "text/html; charset=utf-8")
        elif p == "/api/logs/acc1":
            self.send_text(read_tail(LOG_FILES["acc1"]))
        elif p == "/api/logs/acc2":
            self.send_text(read_tail(LOG_FILES["acc2"]))
        elif p == "/api/logs/acc3":
            self.send_text(read_tail(LOG_FILES["acc3"]))
        elif p == "/api/logs/dispatcher":
            self.send_text(read_tail(LOG_FILES["dispatcher"]))
        elif p == "/api/csv":
            rows = []
            if CSV_PATH.exists():
                try:
                    with open(CSV_PATH, "r", encoding="utf-8") as f:
                        for row in csv.DictReader(f, fieldnames=["title","status","updated"]):
                            rows.append(dict(row))
                except Exception:
                    pass
            self.send_text(json.dumps(rows, ensure_ascii=False), "application/json; charset=utf-8")
        elif p == "/dl/csv":
            if CSV_PATH.exists():
                data = CSV_PATH.read_bytes()
                ts = datetime.now().strftime("%Y%m%d-%H%M%S")
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="status_{ts}.csv"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_error(404)
        elif p == "/dl/acc1":
            lf = LOG_FILES["acc1"]
            data = lf.read_bytes() if lf.exists() else b""
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="acc1_{ts}.log"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif p == "/health":
            self.send_text("OK")
        else:
            self.send_error(404)


class ReuseServer(HTTPServer):
    allow_reuse_address = True


def background_cleanup_loop():
    import time
    try:
        from telegram_media_downloader.utils.auto_cleaner import clean_garbage
    except Exception as e:
        clean_garbage = None
        print(f"[AUTO-CLEANER INIT ERR] {e}", flush=True)

    while True:
        time.sleep(300)  # Tự động quét 5 phút 1 lần
        if clean_garbage:
            try:
                clean_garbage(max_idle_minutes=10)
            except Exception as e:
                print(f"[AUTO-CLEANER ERR] {e}", flush=True)


def main():
    import time
    # Kích hoạt luồng ngầm tự động dọn rác đĩa 5 phút 1 lần
    t_clean = threading.Thread(target=background_cleanup_loop, daemon=True)
    t_clean.start()

    for attempt in range(10):
        try:
            server = ReuseServer(("0.0.0.0", PORT), Handler)
            print(f"[OK] Web Dashboard tai http://0.0.0.0:{PORT}", flush=True)
            server.serve_forever()
            return
        except OSError as e:
            print(f"[!] Port {PORT} ban ({e}), thu lai sau 2s... ({attempt+1}/10)", flush=True)
            time.sleep(2)
    print(f"[X] Khong the bind port {PORT}.", flush=True)


if __name__ == "__main__":
    main()
