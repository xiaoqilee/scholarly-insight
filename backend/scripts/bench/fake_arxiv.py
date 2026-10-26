import asyncio, sys
from urllib.parse import parse_qs
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
from tests.conftest import feed_xml, aid
calls = 0
async def app(scope, receive, send):
    global calls
    if scope["type"] != "http": return
    calls += 1
    p = {k: v[0] for k, v in parse_qs(scope["query_string"].decode()).items()}
    if scope["path"] == "/calls":
        body = str(calls - 1).encode()
    else:
        await asyncio.sleep(0.2)  # arXiv response latency
        if "id_list" in p:
            ids = p["id_list"].split(","); body = feed_xml(ids, len(ids), 0)
        else:
            s, m = int(p["start"]), int(p["max_results"]); ids = [aid(n) for n in range(s, min(s + m, 5000))]
            body = feed_xml(ids, 5000, s)
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/atom+xml")]})
    await send({"type": "http.response.body", "body": body})
