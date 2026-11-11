"""CLI control for a running FerroDSP Lab window (JSON in, JSON out)."""
import bootstrap
import argparse
import json
import urllib.request
import urllib.error
from pathlib import Path

def request(command=None,endpoint='/status'):
    auth=json.loads((bootstrap.LOCAL/'control.json').read_text(encoding='utf-8'))
    data=None if command is None else json.dumps(command).encode('utf-8')
    req=urllib.request.Request(auth['url']+('/command' if command else endpoint),data=data,
                               headers={'Authorization':'Bearer '+auth['token'],'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=20) as r:
            return r.read()
    except urllib.error.HTTPError as exc:
        return exc.read()

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('command',nargs='?',help='JSON command, e.g. {"action":"status"}; default GET status')
    p.add_argument('--snapshot',type=Path)
    a=p.parse_args()
    if a.snapshot:
        a.snapshot.write_bytes(request(endpoint='/preview.jpg'))
        print(str(a.snapshot))
    else:
        result=request(json.loads(a.command) if a.command else None)
        print(result.decode('utf-8'))
