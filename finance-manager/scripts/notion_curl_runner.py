#!/usr/bin/env python3
"""Notion 网络降级期的 finance_cli.py 传输层包装器。

用法: python3 notion_curl_runner.py < payload.json（替代直接跑 finance_cli.py）
背景: 2026-11-10 晚实测，api.notion.com 直连与 env 代理同时间歇 SSL EOF/
RemoteDisconnected（单路成功率约 1/3），finance_cli 内置 urlopen 无重试。
本包装器 monkeypatch urllib.request.urlopen 为 curl 实现：直连/代理交替
重试 12 次，connect-timeout 5s 快速失败，max-time 60s 保证大响应体完整。
非 2xx 会抛 HTTPError，仍由 finance_cli 自己的 429/5xx 退避逻辑接管。
"""
import io, os, subprocess, sys, tempfile, urllib.request, urllib.error, runpy
from email.message import Message

PROXY = 'http://127.0.0.1:7900'
CLI = '/home/garry/.hermes/plugins/finance/finance_cli.py'

class _Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return None

def urlopen(req, timeout=30, *a, **k):
    url = req.full_url
    method = req.get_method()
    hdrs = dict(req.header_items())
    data = req.data
    errs = []
    for i in range(12):
        route = ['-x', PROXY] if i % 2 else []
        cmd = ['curl', '-sS', '--connect-timeout', '5', '--max-time', '120'] + route + ['-X', method]
        for hk, hv in hdrs.items():
            cmd += ['-H', f'{hk}: {hv}']
        f = tempfile.NamedTemporaryFile(delete=False); f.close()
        cmd += ['-o', f.name, '-w', '%{http_code}', url]
        bfp = None
        if data is not None:
            bfp = tempfile.NamedTemporaryFile(delete=False, suffix='.json'); bfp.write(data); bfp.close()
            cmd += ['--data-binary', '@' + bfp.name]
        try:
            p = subprocess.run(cmd, input=b'', capture_output=True, timeout=70)
            if bfp:
                try: os.unlink(bfp.name)
                except OSError: pass
        except subprocess.TimeoutExpired:
            errs.append('t%d curl-timeout' % i); os.unlink(f.name); continue
        code = p.stdout.decode().strip()
        if code in ('', '000'):
            errs.append('t%d %s' % (i, p.stderr.decode().strip()[:100]))
            os.unlink(f.name); continue
        body = open(f.name, 'rb').read(); os.unlink(f.name)
        c = int(code)
        if 200 <= c < 300:
            return _Resp(body)
        hdr = Message(); hdr['Content-Type'] = 'application/json'
        raise urllib.error.HTTPError(url, c, code, hdr, io.BytesIO(body))
    raise urllib.error.URLError('all curl tries failed: ' + ' | '.join(errs[-3:]))

urllib.request.urlopen = urlopen
sys.argv = ['finance_cli.py']
runpy.run_path(CLI, run_name='__main__')
