# -*- coding: utf-8 -*-
# /asr 端到端验证脚本（避免 bash 内联中文/编码问题）
import base64, io, json, math, struct, urllib.request


def post(path, token, raw, fname, ctype):
    boundary = '----xtasr'
    body = (b'--' + boundary.encode() + b'\r\nContent-Disposition: form-data; name="file"; filename="'
            + fname.encode() + b'"\r\nContent-Type: ' + ctype.encode() + b'\r\n\r\n'
            + raw + b'\r\n--' + boundary.encode() + b'--\r\n')
    r = urllib.request.Request('http://127.0.0.1:7780' + path, data=body, headers={
        'Content-Type': 'multipart/form-data; boundary=' + boundary,
        'Authorization': 'Bearer ' + token})
    return json.load(urllib.request.urlopen(r, timeout=90))


r = urllib.request.Request('http://127.0.0.1:7780/api/auth/login',
                           data=json.dumps({'username': 'admin', 'password': 'admin123'}).encode(),
                           headers={'Content-Type': 'application/json'})
tok = json.load(urllib.request.urlopen(r, timeout=30))['access_token']

sr = 16000
n = sr
buf = io.BytesIO()
buf.write(b'RIFF')
buf.write(struct.pack('<I', 36 + n * 2))
buf.write(b'WAVEfmt ')
buf.write(struct.pack('<IHHIIHH', 16, 1, 1, sr, sr * 2, 2, 16))
buf.write(b'data')
buf.write(struct.pack('<I', n * 2))
for i in range(n):
    buf.write(struct.pack('<h', int(6000 * math.sin(2 * math.pi * 440 * i / sr))))

resp = post('/api/drawing/asr', tok, buf.getvalue(), 'test.wav', 'audio/wav')
print('ASR resp:', json.dumps(resp, ensure_ascii=False))
