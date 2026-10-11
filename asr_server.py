# -*- coding: utf-8 -*-
"""本地后端：静态托管原型页面 + 百度语音识别代理（密钥仅存于 baidu_config.json，不进前端/仓库）。"""
import json
import os
import ssl
import time
import urllib.request
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

# 本机 Python 缺少根证书/存在代理拦截时仍可调用百度接口（仅限本地原型调试）
SSL_CTX = ssl._create_unverified_context()

BASE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(BASE, 'baidu_config.json'), encoding='utf-8') as f:
    CFG = json.load(f)

_token_cache = {'token': None, 'expire_at': 0}


def get_access_token():
    if _token_cache['token'] and time.time() < _token_cache['expire_at']:
        return _token_cache['token']
    params = 'grant_type=client_credentials&client_id=%s&client_secret=%s' % (
        CFG['api_key'], CFG['secret_key'])
    req = urllib.request.Request(CFG['token_url'], data=params.encode('utf-8'), method='POST')
    with urllib.request.urlopen(req, timeout=10, context=SSL_CTX) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    token = data.get('access_token')
    if token:
        _token_cache['token'] = token
        _token_cache['expire_at'] = time.time() + int(data.get('expires_in', 2592000)) - 60
    return token


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=BASE, **kw)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store, max-age=0')
        super().end_headers()

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.end_headers()

    def do_POST(self):
        if self.path != '/asr':
            self._json({'ok': False, 'msg': 'not found'}, 404)
            return
        try:
            length = int(self.headers.get('Content-Length', 0))
            payload = json.loads(self.rfile.read(length).decode('utf-8'))
            speech = payload.get('speech', '')
            audio_len = payload.get('len', 0)
            token = get_access_token()
            if not token:
                self._json({'ok': False, 'msg': '获取百度 access_token 失败'})
                return
            body = json.dumps({
                'format': 'pcm', 'rate': 16000, 'channel': 1,
                'cuid': CFG['cuid'], 'dev_pid': CFG['dev_pid'],
                'token': token, 'speech': speech, 'len': audio_len,
            }).encode('utf-8')
            req = urllib.request.Request(
                CFG['asr_url'], data=body, method='POST',
                headers={'Content-Type': 'application/json', 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=15, context=SSL_CTX) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            if data.get('err_no') == 0 and data.get('result'):
                self._json({'ok': True, 'text': data['result'][0]})
            else:
                self._json({'ok': False, 'err_no': data.get('err_no'),
                            'msg': data.get('err_msg', '识别失败')})
        except Exception as e:  # noqa: BLE001
            self._json({'ok': False, 'msg': str(e)}, 500)

    def log_message(self, fmt, *args):
        print('[asr_server] %s' % (fmt % args))


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8765))
    print('serving on http://localhost:%d' % port)
    ThreadingHTTPServer(('0.0.0.0', port), Handler).serve_forever()
