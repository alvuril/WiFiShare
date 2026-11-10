#!/usr/bin/env python3
"""WiFi Share - send any file between devices on the same Wi-Fi.

Run it on one device, open the printed URL on the other (any browser, phone
included) and drag files in either direction. Python 3.8+, no dependencies.

    python wifishare.py                       # open the app window
    python wifishare.py serve                 # headless / terminal mode
    python wifishare.py send photo.jpg URL    # send from the command line
"""
import argparse
import http.server
import json
import os
import secrets
import socket
import socketserver
import sys
import urllib.parse
import urllib.request

CHUNK = 1024 * 1024

if sys.stdout is None:  # windowed .exe has no console
    sys.stdout = sys.stderr = open(os.devnull, "w")

PAGE = b"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0e1116">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="WiFi Share">
<title>WiFi Share</title>
<style>
:root{--bg:#f6f7f9;--fg:#1c1e21;--card:#fff;--line:#d5d9de;--acc:#3b7bf6}
@media(prefers-color-scheme:dark){:root{--bg:#15171a;--fg:#e8eaed;--card:#1f2226;--line:#383c42;--acc:#6ea0ff}}
body{margin:0;font:16px system-ui,sans-serif;background:var(--bg);color:var(--fg)}
main{max-width:640px;margin:0 auto;padding:20px;padding-top:max(20px,env(safe-area-inset-top))}
h1{font-size:1.4rem}h2{font-size:1rem;margin-top:28px}
#drop{border:2px dashed var(--line);border-radius:12px;padding:56px 16px;text-align:center;background:var(--card);cursor:pointer}
#drop.over{border-color:var(--acc)}
.row{display:flex;gap:10px;align-items:center;justify-content:space-between;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px;margin:8px 0}
.row span{overflow-wrap:anywhere}small{opacity:.65}
progress{width:90px}a{color:var(--acc)}
</style></head><body><main>
<h1>WiFi Share</h1>
<div id="drop">Tap or drop files here to send them to this device
<input id="pick" type="file" multiple hidden></div>
<div id="up"></div>
<h2>Files on this device</h2>
<div id="list"></div>
<script>
const KEY=new URLSearchParams(location.search).get('key')||'';
const q=KEY?'?key='+encodeURIComponent(KEY):'';
const $=id=>document.getElementById(id);
const size=n=>n<1024?n+' B':n<1048576?(n/1024).toFixed(1)+' KB':n<1073741824?(n/1048576).toFixed(1)+' MB':(n/1073741824).toFixed(2)+' GB';
function el(tag,text){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e}
function send(file){
  return new Promise(done=>{
    const row=el('div');row.className='row';
    const name=el('span',file.name),bar=el('progress'),st=el('small');
    bar.max=1;bar.value=0;row.append(name,bar,st);$('up').prepend(row);
    const x=new XMLHttpRequest();
    x.open('POST','/upload?name='+encodeURIComponent(file.name)+(KEY?'&key='+encodeURIComponent(KEY):''));
    x.upload.onprogress=e=>{if(e.lengthComputable)bar.value=e.loaded/e.total};
    x.onloadend=()=>{const ok=x.status===200;bar.remove();st.textContent=ok?'sent':'failed';done()};
    x.send(file);
  });
}
async function sendAll(files){for(const f of files)await send(f);load()}
async function load(){
  try{
    const r=await fetch('/api/files'+q);if(!r.ok)return;
    const files=await r.json(),box=$('list');box.replaceChildren();
    if(!files.length){box.append(el('small','Nothing received yet.'))}
    for(const f of files){
      const row=el('div');row.className='row';
      const a=el('a',f.name);a.href='/download/'+encodeURIComponent(f.name)+q;
      row.append(a,el('small',size(f.size)));box.append(row);
    }
  }catch(e){}
}
const drop=$('drop'),pick=$('pick');
drop.onclick=()=>pick.click();
pick.onchange=()=>{sendAll([...pick.files]);pick.value=''};
drop.ondragover=e=>{e.preventDefault();drop.classList.add('over')};
drop.ondragleave=()=>drop.classList.remove('over');
drop.ondrop=e=>{e.preventDefault();drop.classList.remove('over');sendAll([...e.dataTransfer.files])};
load();setInterval(load,3000);
</script></main></body></html>"""


def local_ip():
    """Best-guess LAN address (no packets are actually sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def unique_path(folder, name):
    name = os.path.basename(name.replace("\\", "/")).strip() or "file"
    base, ext = os.path.splitext(name)
    path, n = os.path.join(folder, name), 1
    while os.path.exists(path):
        path = os.path.join(folder, f"{base} ({n}){ext}")
        n += 1
    return path


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _reply(self, code, body=b"", ctype="text/plain; charset=utf-8", close=False):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if close:
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _authorized(self, query):
        key = self.server.key
        if not key:
            return True
        given = query.get("key", [self.headers.get("X-Key", "")])[0]
        return secrets.compare_digest(given.encode(), key.encode())

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(url.query)
        if not self._authorized(query):
            return self._reply(403, b"Missing or wrong key. Use the full URL shown in the terminal.")
        folder = self.server.folder
        if url.path == "/":
            return self._reply(200, PAGE, "text/html; charset=utf-8")
        if url.path == "/api/files":
            items = []
            for n in os.listdir(folder):
                p = os.path.join(folder, n)
                if os.path.isfile(p) and not n.endswith(".part"):
                    st = os.stat(p)
                    items.append({"name": n, "size": st.st_size, "mtime": st.st_mtime})
            items.sort(key=lambda i: -i["mtime"])
            return self._reply(200, json.dumps(items).encode(), "application/json")
        if url.path.startswith("/download/"):
            name = os.path.basename(urllib.parse.unquote(url.path[len("/download/"):]))
            path = os.path.join(folder, name)
            if not name or not os.path.isfile(path):
                return self._reply(404, b"Not found")
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(os.path.getsize(path)))
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + urllib.parse.quote(name))
            self.end_headers()
            with open(path, "rb") as f:
                while chunk := f.read(CHUNK):
                    self.wfile.write(chunk)
            return
        self._reply(404, b"Not found")

    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(url.query)
        if not self._authorized(query):
            return self._reply(403, b"Bad key", close=True)
        if url.path != "/upload":
            return self._reply(404, b"Not found", close=True)
        try:
            length = int(self.headers["Content-Length"])
        except (TypeError, ValueError):
            return self._reply(411, b"Content-Length required", close=True)
        path = unique_path(self.server.folder, query.get("name", ["file"])[0])
        part, left = path + ".part", length
        try:
            with open(part, "wb") as f:
                while left > 0:
                    chunk = self.rfile.read(min(CHUNK, left))
                    if not chunk:
                        raise ConnectionError("upload interrupted")
                    f.write(chunk)
                    left -= len(chunk)
            os.replace(part, path)
        except Exception:
            if os.path.exists(part):
                os.remove(part)
            return self._reply(500, b"Upload failed", close=True)
        print(f"  received  {os.path.basename(path)}  ({length:,} bytes)")
        if self.server.on_receive:
            self.server.on_receive(os.path.basename(path), length)
        self._reply(200, json.dumps({"saved": os.path.basename(path)}).encode(), "application/json")


def start_server(folder, port, use_key=True):
    folder = os.path.abspath(folder)
    os.makedirs(folder, exist_ok=True)
    srv = Server(("0.0.0.0", port), Handler)
    srv.folder = folder
    srv.key = secrets.token_hex(3) if use_key else ""
    srv.on_receive = None
    url = f"http://{local_ip()}:{port}/" + (f"?key={srv.key}" if srv.key else "")
    return srv, url


def serve(args):
    srv, url = start_server(args.dir, args.port, not args.no_key)
    print("\nWiFi Share is running.")
    print(f"  Open this on your other device (same Wi-Fi):\n\n    {url}\n")
    print(f"  Received files are saved in: {srv.folder}")
    print("  Press Ctrl+C to stop.\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


def make_qr(text):
    """Tiny QR encoder (byte mode, error correction L, versions 1-5). Returns a bool matrix."""
    data = text.encode()
    caps = {1: (19, 7), 2: (34, 10), 3: (55, 15), 4: (80, 20), 5: (108, 26)}
    ver = next((v for v, (d, _) in caps.items() if len(data) + 2 <= d), None)
    if ver is None:
        raise ValueError("text too long for QR")
    nd, ne = caps[ver]
    bits = "0100" + format(len(data), "08b") + "".join(format(b, "08b") for b in data)
    bits += "0" * min(4, nd * 8 - len(bits))
    bits += "0" * (-len(bits) % 8)
    pad = 0
    while len(bits) < nd * 8:
        bits += format((0xEC, 0x11)[pad % 2], "08b")
        pad += 1
    cw = [int(bits[i:i + 8], 2) for i in range(0, len(bits), 8)]
    # Reed-Solomon error correction over GF(256)
    exp, log, x = [0] * 512, [0] * 256, 1
    for i in range(255):
        exp[i], log[x] = x, i
        x <<= 1
        if x & 256:
            x ^= 0x11D
    for i in range(255, 512):
        exp[i] = exp[i - 255]
    mul = lambda a, b: 0 if a == 0 or b == 0 else exp[log[a] + log[b]]
    gen = [1]
    for i in range(ne):
        nxt = [0] * (len(gen) + 1)
        for j, c in enumerate(gen):
            nxt[j] ^= c
            nxt[j + 1] ^= mul(c, exp[i])
        gen = nxt
    rem = [0] * ne
    for b in cw:
        f = b ^ rem[0]
        rem = rem[1:] + [0]
        for i in range(ne):
            rem[i] ^= mul(gen[i + 1], f)
    stream = "".join(format(b, "08b") for b in cw + rem)

    size = 17 + 4 * ver
    mod = [[False] * size for _ in range(size)]
    fn = [[False] * size for _ in range(size)]

    def put(x, y, dark, m=None):
        if 0 <= x < size and 0 <= y < size:
            (mod if m is None else m)[y][x] = dark
            fn[y][x] = True

    for i in range(size):
        put(6, i, i % 2 == 0)
        put(i, 6, i % 2 == 0)
    for cx, cy in ((3, 3), (size - 4, 3), (3, size - 4)):
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                put(cx + dx, cy + dy, max(abs(dx), abs(dy)) not in (2, 4))
    if ver > 1:
        c = size - 7
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                put(c + dx, c + dy, max(abs(dx), abs(dy)) != 1)

    def fmt(mask, m=None):
        d = (1 << 3) | mask  # error correction level L = 01
        r = d
        for _ in range(10):
            r = (r << 1) ^ ((r >> 9) * 0x537)
        b = (d << 10 | r) ^ 0x5412
        g = lambda i: (b >> i) & 1 == 1
        for i in range(6):
            put(8, i, g(i), m)
        put(8, 7, g(6), m)
        put(8, 8, g(7), m)
        put(7, 8, g(8), m)
        for i in range(9, 15):
            put(14 - i, 8, g(i), m)
        for i in range(8):
            put(size - 1 - i, 8, g(i), m)
        for i in range(8, 15):
            put(8, size - 15 + i, g(i), m)
        put(8, size - 8, True, m)

    fmt(0)  # reserve the format areas
    k = 0
    for right in range(size - 1, 0, -2):
        if right <= 6:  # skip the vertical timing column
            right -= 1
        for vert in range(size):
            for j in range(2):
                xx = right - j
                yy = size - 1 - vert if ((right + 1) & 2) == 0 else vert
                if not fn[yy][xx] and k < len(stream):
                    mod[yy][xx] = stream[k] == "1"
                    k += 1

    cond = [lambda x, y: (x + y) % 2 == 0, lambda x, y: y % 2 == 0,
            lambda x, y: x % 3 == 0, lambda x, y: (x + y) % 3 == 0,
            lambda x, y: (x // 3 + y // 2) % 2 == 0,
            lambda x, y: x * y % 2 + x * y % 3 == 0,
            lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
            lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0]

    def penalty(m):
        p = 0
        lines = ["".join("1" if v else "0" for v in row) for row in m]
        lines += ["".join("1" if m[y][x] else "0" for y in range(size)) for x in range(size)]
        for s in lines:
            run = 1
            for i in range(1, size):
                if s[i] == s[i - 1]:
                    run += 1
                else:
                    p += run - 2 if run >= 5 else 0
                    run = 1
            p += run - 2 if run >= 5 else 0
            p += 40 * (s.count("10111010000") + s.count("00001011101"))
        for y in range(size - 1):
            for x in range(size - 1):
                if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                    p += 3
        dark, tot = sum(map(sum, m)), size * size
        return p + 10 * (-(-abs(dark * 20 - tot * 10) // tot) - 1)

    best, best_p = None, None
    for mask in range(8):
        m = [row[:] for row in mod]
        for y in range(size):
            for x in range(size):
                if not fn[y][x] and cond[mask](x, y):
                    m[y][x] = not m[y][x]
        fmt(mask, m)
        p = penalty(m)
        if best_p is None or p < best_p:
            best, best_p = m, p
    return best


def gui():
    """Desktop window: QR code for phones, live list of received files."""
    import queue
    import subprocess
    import threading
    import time
    import tkinter as tk
    import webbrowser
    from tkinter import filedialog, messagebox

    try:  # crisp text on high-DPI Windows screens
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    BG, CARD, FG, DIM = "#0e1116", "#171b22", "#e8ecf2", "#8a94a6"
    ACC, ACC_HOVER, BTN, BTN_HOVER, GREEN = "#3b7bf6", "#5a92ff", "#262c36", "#323a47", "#3ddc84"
    FONT = "Segoe UI"

    default_dir = os.path.normpath(os.path.join(os.path.expanduser("~"), "Downloads", "WiFiShare"))
    cfg_dir = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "WiFiShare")
    cfg_path = os.path.join(cfg_dir, "config.json")

    def save_cfg(data):
        try:
            os.makedirs(cfg_dir, exist_ok=True)
            with open(cfg_path, "w") as f:
                json.dump(data, f)
        except OSError:
            pass

    try:
        with open(cfg_path) as f:
            saved = json.load(f).get("folder")
    except (OSError, ValueError, AttributeError):
        saved = None
    folder = os.path.normpath(saved) if saved and os.path.isdir(saved) else default_dir
    srv = url = None
    for port in range(8000, 8011):
        try:
            srv, url = start_server(folder, port)
            break
        except OSError:
            continue
    root = tk.Tk()
    if srv is None:
        messagebox.showerror("WiFi Share", "Could not start: ports 8000-8010 are all in use.")
        return
    events = queue.Queue()
    srv.on_receive = lambda name, size: events.put((name, size))
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    root.title("WiFi Share")
    root.configure(bg=BG)
    root.geometry("420x780")
    root.minsize(400, 740)

    head = tk.Frame(root, bg=BG)
    head.pack(fill="x", padx=24, pady=(22, 0))
    tk.Label(head, text="WiFi Share", font=(FONT, 20, "bold"), bg=BG, fg=FG).pack(side="left")
    tk.Label(head, text="\u25cf Ready", font=(FONT, 10), bg=BG, fg=GREEN).pack(side="right")
    tk.Label(root, text="Send files between devices on the same Wi-Fi", font=(FONT, 10),
             bg=BG, fg=DIM, anchor="w").pack(fill="x", padx=24, pady=(2, 16))

    card = tk.Frame(root, bg=CARD)
    card.pack(fill="x", padx=24)
    matrix = make_qr(url)
    n = len(matrix)
    cell = max(4, 240 // (n + 8))
    side = (n + 8) * cell
    cv = tk.Canvas(card, width=side, height=side, bg=CARD, highlightthickness=0)
    cv.pack(pady=(18, 10))
    r = 18
    pts = [r, 0, side - r, 0, side, 0, side, r, side, side - r, side, side, side - r, side,
           r, side, 0, side, 0, side - r, 0, r, 0, 0]
    cv.create_polygon(pts, smooth=True, fill="#ffffff", outline="")
    for y, row in enumerate(matrix):
        for x, dark in enumerate(row):
            if dark:
                cv.create_rectangle((x + 4) * cell, (y + 4) * cell, (x + 5) * cell, (y + 5) * cell,
                                    fill="#0e1116", outline="")
    tk.Label(card, text="Scan with your phone's camera", font=(FONT, 12, "bold"),
             bg=CARD, fg=FG).pack()
    tk.Label(card, text="or type this link into the browser:", font=(FONT, 9),
             bg=CARD, fg=DIM).pack(pady=(2, 4))
    tk.Label(card, text=url, font=("Consolas", 10), bg=CARD, fg=ACC_HOVER,
             wraplength=340).pack(padx=12, pady=(0, 16))

    def button(parent, text, cmd, primary=False):
        bg, hov = (ACC, ACC_HOVER) if primary else (BTN, BTN_HOVER)
        b = tk.Label(parent, text=text, font=(FONT, 10, "bold"), bg=bg, fg="#ffffff",
                     padx=14, pady=10, cursor="hand2")
        b.bind("<Button-1>", lambda e: cmd(b))
        b.bind("<Enter>", lambda e: b.config(bg=hov))
        b.bind("<Leave>", lambda e: b.config(bg=bg))
        return b

    def copy(b):
        root.clipboard_clear()
        root.clipboard_append(url)
        b.config(text="Copied \u2713")
        root.after(1200, lambda: b.config(text="Copy link"))

    state = {"folder": folder}

    def shorten(path, limit=42):
        return path if len(path) <= limit else "\u2026" + path[-(limit - 1):]

    def open_folder(_):
        path = os.path.normpath(state["folder"])
        os.makedirs(path, exist_ok=True)
        try:
            if sys.platform.startswith("win"):
                subprocess.Popen(["explorer", path])  # opens the folder in File Explorer
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except OSError:
            messagebox.showinfo("WiFi Share", f"Received files are saved in:\n{path}")

    def set_folder(path):
        path = os.path.normpath(path)
        try:
            os.makedirs(path, exist_ok=True)
            if not os.access(path, os.W_OK):
                raise OSError("not writable")
        except OSError:
            messagebox.showerror("WiFi Share", f"Can't save files to:\n{path}\n\nPick another folder.")
            return
        state["folder"] = srv.folder = path
        path_label.config(text=shorten(path))
        save_cfg({} if path == default_dir else {"folder": path})

    def choose_folder(_):
        new = filedialog.askdirectory(title="Choose where received files are saved",
                                      initialdir=state["folder"])
        if new:
            set_folder(new)

    btns = tk.Frame(root, bg=BG)
    btns.pack(fill="x", padx=24, pady=14)
    for i, (t, c, p) in enumerate([("Copy link", copy, True),
                                   ("Open in browser", lambda _: webbrowser.open(url), False),
                                   ("Open folder", open_folder, False)]):
        btns.columnconfigure(i, weight=1, uniform="b")
        button(btns, t, c, p).grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 6, 0))

    loc = tk.Frame(root, bg=CARD)
    loc.pack(fill="x", padx=24, pady=(0, 16))
    tk.Label(loc, text="Save received files to", font=(FONT, 9), bg=CARD, fg=DIM,
             anchor="w").pack(fill="x", padx=14, pady=(12, 0))
    path_label = tk.Label(loc, text=shorten(folder), font=("Consolas", 10), bg=CARD, fg=FG, anchor="w")
    path_label.pack(fill="x", padx=14, pady=(2, 8))
    loc_btns = tk.Frame(loc, bg=CARD)
    loc_btns.pack(fill="x", padx=14, pady=(0, 14))
    button(loc_btns, "Change\u2026", choose_folder).pack(side="left")
    button(loc_btns, "Reset to default", lambda _: set_folder(default_dir)).pack(side="left", padx=(8, 0))

    tk.Label(root, text="Received", font=(FONT, 12, "bold"), bg=BG, fg=FG,
             anchor="w").pack(fill="x", padx=24)
    feed = tk.Frame(root, bg=BG)
    feed.pack(fill="both", expand=True, padx=24, pady=(6, 16))
    empty = tk.Label(feed, text="Waiting for files\u2026", font=(FONT, 10), bg=BG, fg=DIM, anchor="w")
    empty.pack(fill="x")
    rows = []

    def human(b):
        for unit in ("B", "KB", "MB", "GB"):
            if b < 1024 or unit == "GB":
                return f"{b:.0f} {unit}" if unit == "B" else f"{b:.1f} {unit}"
            b /= 1024

    def add_row(name, size):
        empty.pack_forget()
        row = tk.Frame(feed, bg=CARD)
        short = name if len(name) <= 30 else name[:27] + "\u2026"
        tk.Label(row, text=short, font=(FONT, 10), bg=CARD, fg=FG, anchor="w").pack(
            side="left", padx=12, pady=9)
        tk.Label(row, text=f"{human(size)}  \u00b7  {time.strftime('%H:%M')}", font=(FONT, 9),
                 bg=CARD, fg=DIM).pack(side="right", padx=12)
        if rows:
            row.pack(fill="x", pady=3, before=rows[0])
        else:
            row.pack(fill="x", pady=3)
        rows.insert(0, row)
        while len(rows) > 6:
            rows.pop().destroy()

    def poll():
        try:
            while True:
                add_row(*events.get_nowait())
        except queue.Empty:
            pass
        root.after(300, poll)

    poll()
    root.mainloop()
    srv.shutdown()


def send(args):
    """Send a file to another running WiFi Share instance."""
    target = args.url if "://" in args.url else "http://" + args.url
    u = urllib.parse.urlparse(target)
    key = urllib.parse.parse_qs(u.query).get("key", [""])[0]
    if not os.path.isfile(args.file):
        sys.exit(f"No such file: {args.file}")
    qs = {"name": os.path.basename(args.file)}
    if key:
        qs["key"] = key
    endpoint = f"{u.scheme}://{u.netloc}/upload?{urllib.parse.urlencode(qs)}"
    size = os.path.getsize(args.file)
    with open(args.file, "rb") as f:
        req = urllib.request.Request(endpoint, data=f, method="POST",
                                     headers={"Content-Length": str(size)})
        try:
            with urllib.request.urlopen(req) as r:
                print("Sent:", json.load(r)["saved"])
        except Exception as e:
            sys.exit(f"Send failed: {e}")


def main():
    p = argparse.ArgumentParser(description="Send files between devices on the same Wi-Fi.")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("serve", help="start sharing (default)")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--dir", default="received", help="where received files go")
    s.add_argument("--no-key", action="store_true", help="disable the access key")
    t = sub.add_parser("send", help="send a file to another device")
    t.add_argument("file")
    t.add_argument("url", help="URL printed by the other device")
    if len(sys.argv) == 1:
        return gui()
    if sys.argv[1] not in ("serve", "send", "-h", "--help"):
        sys.argv.insert(1, "serve")
    args = p.parse_args()
    (send if args.cmd == "send" else serve)(args)


if __name__ == "__main__":
    main()
