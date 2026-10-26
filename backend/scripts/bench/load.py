"""N concurrent users: browse cs.LG pages 1-5, open 2 papers per page, repeat page 1."""
import asyncio, sys, time, statistics, httpx
base = sys.argv[1]
lat = []
errors = 0
async def get(c, path, **params):
    global errors
    t = time.perf_counter(); r = await c.get(base + path, params=params, timeout=600); lat.append(time.perf_counter() - t)
    if r.status_code != 200:
        errors += 1
        return {"results": []}
    return r.json()
async def user(c, u):
    for page in range(1, 6):
        d = await get(c, "/api/browse/cs.LG", page=page)
        for a in d["results"][u % 3: u % 3 + 2]:
            await get(c, f"/api/articles/{a['arxiv_id']}")
    await get(c, "/api/browse/cs.LG", page=1)
async def main():
    async with httpx.AsyncClient() as c:
        t = time.perf_counter()
        await asyncio.gather(*(user(c, u) for u in range(int(sys.argv[2]))))
        wall = time.perf_counter() - t
        calls = int((await c.get("http://127.0.0.1:8999/calls")).text)
    lat.sort()
    print(f"requests={len(lat)} errors={errors} wall={wall:.1f}s arxiv_calls={calls} "
          f"p50={statistics.median(lat)*1000:.0f}ms p95={lat[int(len(lat)*.95)]*1000:.0f}ms max={lat[-1]*1000:.0f}ms")
asyncio.run(main())
