"""Loopback-only authenticated JSON control, with commands marshalled to Qt."""
import json
import queue
import secrets
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from recording import dump

class ControlAPI:
    def __init__(self,engine,local):
        self.engine=engine
        self.commands=queue.Queue()
        self.token=secrets.token_urlsafe(32)
        self.preview_jpeg=b''
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def reply(self,status,value,content_type='application/json; charset=utf-8'):
                payload=value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=False,allow_nan=False).encode('utf-8')
                self.send_response(status);self.send_header('Content-Type',content_type)
                self.send_header('Content-Length',str(len(payload)));self.end_headers()
                try:self.wfile.write(payload)
                except (BrokenPipeError,ConnectionResetError):pass
            def allowed(self):
                if not secrets.compare_digest(self.headers.get('Authorization',''),'Bearer '+owner.token):
                    self.reply(401,{'error':'Bearer token required'});return False
                # Prevent browser pages from using local commands via CORS/CSRF.
                if self.headers.get('Origin'):
                    self.reply(403,{'error':'Browser origins are not accepted'});return False
                return True
            def do_GET(self):
                if not self.allowed():return
                if self.path=='/status':self.reply(200,owner.engine.status())
                elif self.path=='/camera/options':self.reply(200,owner.engine.camera_options)
                elif self.path=='/preview.jpg':self.reply(200,owner.preview_jpeg,'image/jpeg')
                else:self.reply(404,{'error':'Unknown endpoint'})
            def do_POST(self):
                if not self.allowed():return
                if self.path!='/command':self.reply(404,{'error':'Unknown endpoint'});return
                try:
                    size=int(self.headers.get('Content-Length','0'))
                    if not 0<size<=65536:raise ValueError('Invalid body length')
                    body=json.loads(self.rfile.read(size))
                    answer=queue.Queue(maxsize=1)
                    owner.commands.put((body,answer))
                    result=answer.get(timeout=15)
                    self.reply(200 if result.get('ok') else 400,result)
                except Exception as exc:self.reply(400,{'error':str(exc)})
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.server.daemon_threads=True
        self.url=f'http://127.0.0.1:{self.server.server_port}'
        self.control_path=Path(local)/'control.json'
        dump(self.control_path,dict(url=self.url,token=self.token,pid=__import__('os').getpid()))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True,name='loopback-control')
        self.thread.start()

    def close(self):
        self.server.shutdown();self.server.server_close()
        # Keep endpoint file for diagnosis; token is valid only while this process runs.

