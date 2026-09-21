"""Tiny local stand-in for the licence worker (UI smokes only)."""
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from datetime import date, timedelta
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        q = parse_qs(urlparse(self.path).query); key = (q.get("key") or [""])[0]
        if key == "KEY-TEST-GOOD-0001": body = {"status": "SUCCESS", "type": "FULL", "owner": "Smoke", "expires": (date.today() + timedelta(days=9)).isoformat()}
        elif key == "KEY-TEST-MAXD-0001": body = {"status": "MAX_DEVICES_REACHED", "message": "سقف تعداد دستگاه مجاز تکمیل شده است"}
        else: body = {"status": "INVALID", "message": "لایسنس یافت نشد"}
        data = json.dumps(body, ensure_ascii=False).encode(); self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def log_message(self, *a): pass
HTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 8099), H).serve_forever()
