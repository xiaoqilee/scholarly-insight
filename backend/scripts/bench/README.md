# Benchmark

Simulated arXiv (200 ms latency) on port 8999, backend with a 0.3 s politeness gap.

```bash
cd backend/scripts/bench
uvicorn fake_arxiv:app --port 8999 &
cd ../.. && ARXIV_BASE_URL=http://127.0.0.1:8999/api/query ARXIV_MIN_INTERVAL_S=0.3 \
  CLIENT_RATE_LIMIT=100000 uvicorn app.main:app --port 8000 --workers 4 &
python scripts/bench/load.py http://127.0.0.1:8000 20   # 20 concurrent users
```

Each user browses cs.LG pages 1 to 5, opens 2 papers per page, then revisits page 1.
