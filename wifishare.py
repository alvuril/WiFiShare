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
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>WiFi Share</title>
<style>
:root{--bg:#f6f7f9;--fg:#1c1e21;--card:#fff;--line:#d5d9de;--acc:#2563eb}
@media(prefers-color-scheme:dark){:root{--bg:#15171a;--fg:#e8eaed;--card:#1f2226;--line:#383c42;--acc:#6ea0ff}}
body{margin:0;font:16px system-ui,sans-serif;background:var(--bg);color:var(--fg)}
main{max-width:640px;margin:0 auto;padding:20px}
h1{font-size:1.4rem}h2{font-size:1rem;margin-top:28px}
#drop{border:2px dashed var(--line);border-radius:12px;padding:36px 16px;text-align:center;background:var(--card);cursor:pointer}
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
        self._reply(200, json.dumps({"saved": os.path.basename(path)}).encode(), "application/json")


def start_server(folder, port, use_key=True):
    folder = os.path.abspath(folder)
    os.makedirs(folder, exist_ok=True)
    srv = Server(("0.0.0.0", port), Handler)
    srv.folder = folder
    srv.key = secrets.token_urlsafe(6) if use_key else ""
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


def gui():
    """Small desktop window: double-click the .exe and go."""
    import threading
    import tkinter as tk
    import webbrowser
    from tkinter import messagebox

    folder = os.path.join(os.path.expanduser("~"), "Downloads", "WiFiShare")
    srv = None
    for port in range(8000, 8011):
        try:
            srv, url = start_server(folder, port)
            break
        except OSError:
            continue
    root = tk.Tk()
    root.title("WiFi Share")
    root.geometry("460x250")
    if srv is None:
        messagebox.showerror("WiFi Share", "Could not start: ports 8000-8010 are all in use.")
        return
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    pad = {"padx": 16, "pady": 4}
    tk.Label(root, text="WiFi Share", font=("Segoe UI", 16, "bold")).pack(pady=(14, 2))
    tk.Label(root, text="On your other device (same Wi-Fi), open this link:").pack(**pad)
    box = tk.Entry(root, justify="center")
    box.insert(0, url)
    box.config(state="readonly")
    box.pack(fill="x", **pad)

    def copy():
        root.clipboard_clear()
        root.clipboard_append(url)

    row = tk.Frame(root)
    row.pack(pady=8)
    tk.Button(row, text="Copy link", command=copy).pack(side="left", padx=4)
    tk.Button(row, text="Open in browser", command=lambda: webbrowser.open(url)).pack(side="left", padx=4)
    tk.Button(row, text="Open received files",
              command=lambda: os.startfile(folder) if hasattr(os, "startfile") else webbrowser.open(folder)
              ).pack(side="left", padx=4)
    tk.Label(root, text=f"Received files go to:\n{folder}", fg="gray").pack(**pad)
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
