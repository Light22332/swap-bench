"""HTTP 层的测试：起一个真的服务（随机端口）用裸连接发请求。

覆盖：keep-alive 下 POST 的请求体必须被读掉——路由不读 body 时也不能让
剩下的字节串成下一条请求行（以前表现为 501 Unsupported method），以及
正常的 GET/POST 分发。

跑法：python tools/tests/test_http.py
"""
import http.client
import os
import sys
import threading
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from app.api import server as api_server                        # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


srv = ThreadingHTTPServer(("127.0.0.1", 0), api_server.Handler)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

try:
    print("keep-alive：POST 空体之后，同一连接还能正常发 GET")
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("POST", "/api/nope", body="{}",
                 headers={"Content-Type": "application/json"})
    r1 = conn.getresponse()
    r1.read()
    check("未知 POST 回 404", r1.status == 404, str(r1.status))

    # 不重开连接：如果请求体没读掉，这一条会被解析成 "{}GET ..." 然后 501
    conn.request("GET", "/img?path=samples%2Fdemo_person_a.jpg&w=64&fmt=webp")
    r2 = conn.getresponse()
    body = r2.read()
    check("同一连接的下一条 GET 不是 501", r2.status == 200, str(r2.status))
    check("GET 拿到的是 WebP 缩略图",
          (r2.getheader("Content-Type") or "").startswith("image/webp") and len(body) > 100,
          r2.getheader("Content-Type") or "")
    conn.close()

    print("普通分发：GET /api/config 的读法没变")
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", "/api/config")
    r3 = conn.getresponse()
    body3 = r3.read()
    check("GET /api/config 回 200", r3.status == 200 and b"backend" in body3,
          str(r3.status))
    conn.close()

    print("keep-alive：POST /api/cancel（会读 body）之后还能发 GET")
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("POST", "/api/cancel", body='{"job_id": "none"}',
                 headers={"Content-Type": "application/json"})
    r4 = conn.getresponse()
    r4.read()
    conn.request("GET", "/api/config")
    r5 = conn.getresponse()
    r5.read()
    check("cancel 之后同一连接 GET 正常", r5.status == 200, str(r5.status))
    conn.close()

    print("请求体上限：超过 MAX_BODY 直接回 413，不往内存里读")
    old = api_server.MAX_BODY
    api_server.MAX_BODY = 1024
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.putrequest("POST", "/api/upload")
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Content-Length", "2048")   # 只发头，不发体
        conn.endheaders()
        r6 = conn.getresponse()
        body6 = r6.read().decode("utf-8", "replace")
        check("超大请求体回 413", r6.status == 413, str(r6.status))
        check("413 说清楚单张上限", "30MB" in body6, body6[:120])
        conn.close()
    finally:
        api_server.MAX_BODY = old
finally:
    srv.shutdown()
    srv.server_close()

print()
if FAILED:
    print(f"FAILED {len(FAILED)} 项：" + "、".join(FAILED))
    sys.exit(1)
print("全部通过")
