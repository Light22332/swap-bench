"""HTTP 层的测试：起一个真的服务（随机端口）用裸连接发请求。

覆盖：keep-alive 下 POST 的请求体必须被读掉——路由不读 body 时也不能让
剩下的字节串成下一条请求行（以前表现为 501 Unsupported method），以及
正常的 GET/POST 分发。

跑法：python tools/tests/test_http.py
"""
import http.client
import json
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

    def post(path, payload=None, raw=None):
        body = raw if raw is not None else json.dumps(payload)
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("POST", path, body=body.encode("utf-8"),
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp, data

    print("畸形 Content-Length：非数字/负数都回 400，不挂死不吞请求")
    for bad_len in ("abc", "-1"):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.putrequest("POST", "/api/upload")
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Content-Length", bad_len)   # 只发头
        conn.endheaders()
        r = conn.getresponse()
        body = r.read().decode("utf-8", "replace")
        conn.close()
        check(f"Content-Length={bad_len} 回 400", r.status == 400, str(r.status))
        check(f"Content-Length={bad_len} 说清楚是哪的问题",
              "Content-Length" in body, body[:100])

    print("请求体不是 JSON：统一回 400，不再当成空对象放过去")
    for path in ("/api/upload", "/api/settings", "/api/config", "/api/run"):
        r, body = post(path, raw="{这不是 JSON")
        text = body.decode("utf-8", "replace")
        check(f"{path} 非 JSON 回 400", r.status == 400, str(r.status))
        check(f"{path} 提示「不是 JSON」", "不是 JSON" in text, text[:100])

    print("参数类型不对：400 而不是 500")
    r, body = post("/api/upload", {"name": "a.jpg"})
    check("缺 data 回 400 且说清楚字段名",
          r.status == 400 and "data 字段" in body.decode(), body[:120])
    r, body = post("/api/upload", {"name": "a.jpg", "data": "!!!!!!"})
    check("坏 base64 回 400",
          r.status == 400 and "base64" in body.decode(), body[:120])
    r, body = post("/api/run", {"person": [], "garments": []})
    check("run 的 person 传数组回 400",
          r.status == 400 and "person" in body.decode(), body[:120])
    r, body = post("/api/cancel", {"job_id": {"a": 1}})
    check("cancel 的 job_id 传对象回 400",
          r.status == 400 and "job_id" in body.decode(), body[:120])
    r, body = post("/api/config", {"backend": 123})
    check("config 的 backend 传数字回 400",
          r.status == 400 and "backend" in body.decode(), body[:120])
    r, body = post("/api/config", [1, 2])
    check("config 传数组回 400",
          r.status == 400 and "JSON 对象" in body.decode(), body[:120])

    print("404 说人话、响应头不泄露运行时版本")
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", "/api/job/nope")
    r = conn.getresponse()
    body = r.read().decode("utf-8", "replace")
    server = r.getheader("Server") or ""
    conn.close()
    check("/api/job 不存在回 404", r.status == 404, str(r.status))
    check("404 是中文提示", "没有这个任务" in body, body[:100])
    check("Server 头不带 Python 版本", "Python" not in server, server)
finally:
    srv.shutdown()
    srv.server_close()

print()
if FAILED:
    print(f"FAILED {len(FAILED)} 项：" + "、".join(FAILED))
    sys.exit(1)
print("全部通过")
