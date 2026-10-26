# Scholarly Insight: GitHub setup

## 1. Create the repo on GitHub
Go to https://github.com/new, name it `scholarly-insight`, leave "Add a README" **unchecked**, click Create.

## 2. Push this code
Unzip `scholarly-insight-backend.zip`, then from inside the `scholarly-insight` folder:

```bash
git init
git add .
git commit -m "Backend: arXiv search with bootcamp data structures"
git branch -M main
git remote add origin https://github.com/<your-username>/scholarly-insight.git
git push -u origin main
```

Using the GitHub CLI instead: `gh repo create scholarly-insight --public --source=. --push`

## 3. Add teammates
Repo → Settings → Collaborators → Add people.

## 4. Each teammate runs it
```bash
git clone https://github.com/<your-username>/scholarly-insight.git
cd scholarly-insight/backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pytest                             # 122 tests, offline, ~5s
python -m scripts.smoke_live       # checks the real arXiv API (~10s)
uvicorn app.main:app --reload      # open http://localhost:8000/docs
```

Requires Python 3.10+.

## 5. Suggested workflow
```bash
git checkout -b feature/frontend-search
# ...work...
git add . && git commit -m "Add search page"
git push -u origin feature/frontend-search
```
Then open a pull request on GitHub and have a teammate review before merging to `main`.

## Layout
```
backend/
  app/
    main.py           API endpoints
    service.py        cache tiers, windows, single-flight, batching
    arxiv_client.py   query builder, Atom parser, HTTP client
    ratelimit.py      shared arXiv rate limiter
    suggest.py        autocomplete index
    dsa/              hand-built structures (LRU, trie, stack parser, queue, binary search, heap, edit distance)
  tests/              unit, API and randomized oracle tests
  scripts/            smoke_live.py, bench/
```
