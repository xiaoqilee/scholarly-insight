import { FormEvent, useMemo, useState } from "react";
import {
  Link,
  NavLink,
  Outlet,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router";
import { categories, papers, type Paper } from "../lib/api";

const navigation = [
  ["/", "Discover"],
  ["/search", "Search Papers"],
  ["/categories", "Browse Categories"],
  ["/trending", "Trending"],
  ["/saved", "Saved Papers"],
  ["/history", "Reading History"],
];

const trends = [
  ["LeetCode dynamic programming", "2,481"],
  ["LeetCode graph problems", "2,104"],
  ["LeetCode sliding window", "1,876"],
  ["LeetCode binary trees", "1,429"],
  ["LeetCode two pointers", "1,206"],
  ["LeetCode interview patterns", "988"],
];

export function AppShell() {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    navigate(`/search?q=${encodeURIComponent(query)}`);
  }

  return (
    <div className="site">
      <header className="masthead">
        <div className="masthead-inner">
          <Link className="wordmark" to="/">
            Scholarly Insight
          </Link>
          <span className="tagline">Powered by arXiv</span>
          <form className="header-search" onSubmit={submit}>
            <input
              aria-label="Search all papers"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search papers..."
            />
            <button>Search</button>
          </form>
        </div>
      </header>
      <nav className="primary-nav" aria-label="Primary navigation">
        <div className="primary-nav-inner">
          {navigation.map(([to, label]) => (
            <NavLink key={to} to={to} end={to === "/"}>
              {label}
            </NavLink>
          ))}
        </div>
      </nav>
      <main className="content">
        <Outlet />
      </main>
      <footer>
        <span>Scholarly Insight</span>
        <span>Paper metadata provided by arXiv.</span>
        <span>Prototype edition</span>
      </footer>
    </div>
  );
}

function SearchForm({ initial = "" }: { initial?: string }) {
  const [query, setQuery] = useState(initial);
  const navigate = useNavigate();

  return (
    <form
      className="large-search"
      onSubmit={(event) => {
        event.preventDefault();
        navigate(`/search?q=${encodeURIComponent(query)}`);
      }}
    >
      <label htmlFor="main-search">Search titles, authors, abstracts, or subjects</label>
      <div>
        <input
          id="main-search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        placeholder="e.g. LeetCode dynamic programming"
        />
        <button>Search papers</button>
      </div>
      <p>
        Suggestions:{" "}
        <Link to="/search?q=dynamic programming">dynamic programming</Link>,{" "}
        <Link to="/search?q=graph problems">graph problems</Link>,{" "}
        <Link to="/search?q=sliding window">sliding window</Link>
      </p>
    </form>
  );
}

export function DiscoverPage() {
  return (
    <div>
      <section className="intro">
        <SearchForm />
      </section>

      <div className="home-columns">
        <section>
          <SectionTitle title="Latest research" link="/search" linkLabel="View all papers" />
          <div className="paper-list">
            {papers.slice(0, 3).map((paper) => (
              <PaperCard key={paper.arxiv_id} paper={paper} />
            ))}
          </div>
        </section>
        <aside>
          <section className="side-box">
            <h2>Trending searches</h2>
            <ol>
              {trends.slice(0, 5).map(([term, count]) => (
                <li key={term}>
                  <Link to={`/search?q=${term}`}>{term}</Link>
                  <small>{count} searches</small>
                </li>
              ))}
            </ol>
            <Link className="more-link" to="/trending">
              View all trending searches
            </Link>
          </section>
          <section className="side-box">
            <h2>Browse subjects</h2>
            <ul className="subject-links">
              {categories.slice(0, 5).map((category) => (
                <li key={category.code}>
                  <Link to={`/categories/${category.code}`}>{category.name}</Link>
                  <code>{category.code}</code>
                </li>
              ))}
            </ul>
            <Link className="more-link" to="/categories">
              All categories
            </Link>
          </section>
        </aside>
      </div>
    </div>
  );
}

function SectionTitle({
  title,
  link,
  linkLabel,
}: {
  title: string;
  link?: string;
  linkLabel?: string;
}) {
  return (
    <div className="section-title">
      <h2>{title}</h2>
      {link && <Link to={link}>{linkLabel}</Link>}
    </div>
  );
}

export function PaperCard({ paper }: { paper: Paper }) {
  return (
    <article className="paper">
      <div className="paper-meta">
        <Link to={`/categories/${paper.primary_category}`}>{paper.primary_category}</Link>
        <span>{new Date(paper.published).toLocaleDateString()}</span>
        <span>arXiv:{paper.arxiv_id}</span>
      </div>
      <h3>
        <Link to={`/paper/${paper.arxiv_id}`}>{paper.title}</Link>
      </h3>
      <p className="authors">{paper.authors.join(", ")}</p>
      {paper.summary && <p className="abstract">{paper.summary}</p>}
      <p className="paper-links">
        <Link to={`/paper/${paper.arxiv_id}`}>Abstract and details</Link>
        {" | "}
        <a href={paper.pdf_url} target="_blank" rel="noreferrer">
          PDF
        </a>
        {" | "}
        <button title="Prototype only">Save paper</button>
      </p>
    </article>
  );
}

export function SearchPage() {
  const [params, setParams] = useSearchParams();
  const route = useParams();
  const current = params.get("q") ?? "";
  const [query, setQuery] = useState(current);
  const [advanced, setAdvanced] = useState(false);
  const [category, setCategory] = useState(route.category ?? "");
  const [sort, setSort] = useState("relevance");

  const results = useMemo(() => {
    const needle = current.toLowerCase();
    return papers.filter(
      (paper) =>
        (!needle ||
          `${paper.title} ${paper.authors.join(" ")} ${paper.summary}`
            .toLowerCase()
            .includes(needle)) &&
        (!category || paper.primary_category === category),
    );
  }, [current, category]);

  function submit(event: FormEvent) {
    event.preventDefault();
    setParams(query ? { q: query } : {});
  }

  return (
    <div>
      <PageHeading
        title="Search Papers"
        text="Search the arXiv research archive using keywords and structured filters."
      />
      <form className="search-form" onSubmit={submit}>
        <label>
          Search query
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Title, author, abstract, or keyword"
          />
        </label>
        <button>Search</button>
        <button type="button" className="plain-button" onClick={() => setAdvanced(!advanced)}>
          {advanced ? "Hide" : "Show"} advanced search
        </button>
      </form>

      {advanced && (
        <div className="advanced-search">
          <label>
            Boolean expression
            <input placeholder={'title:"LeetCode graphs" AND author:Smith NOT cs.AI'} />
          </label>
          <p>Supports AND, OR, NOT, parentheses, quoted phrases, and field names.</p>
        </div>
      )}

      <div className="search-layout">
        <aside className="filter-panel">
          <h2>Refine results</h2>
          {["Keyword", "Title", "Author", "Abstract keywords"].map((label) => (
            <label key={label}>
              {label}
              <input />
            </label>
          ))}
          <label>
            Research category
            <select value={category} onChange={(event) => setCategory(event.target.value)}>
              <option value="">All categories</option>
              {categories.map((item) => (
                <option value={item.code} key={item.code}>
                  {item.code} — {item.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Published after
            <input type="date" />
          </label>
          <label>
            Published before
            <input type="date" />
          </label>
          <label>
            Sort by
            <select value={sort} onChange={(event) => setSort(event.target.value)}>
              <option value="relevance">Relevance</option>
              <option value="submitted">Submission date</option>
              <option value="updated">Last updated</option>
            </select>
          </label>
          <button
            className="plain-button"
            onClick={() => {
              setCategory("");
              setQuery("");
              setParams({});
            }}
          >
            Clear all filters
          </button>
        </aside>

        <section>
          <div className="results-summary">
            <strong>{results.length} results</strong>
            {current && <span> for “{current}”</span>}
          </div>
          {results.length ? (
            <div className="paper-list">
              {results.map((paper) => (
                <PaperCard key={paper.arxiv_id} paper={paper} />
              ))}
            </div>
          ) : (
            <EmptyState
              title="No papers found"
              text="Try using fewer keywords or selecting a different category."
            />
          )}
          <div className="pagination">
            <button disabled>Previous</button>
            <button className="current">1</button>
            <button>2</button>
            <button>3</button>
            <button>Next</button>
          </div>
        </section>
      </div>
    </div>
  );
}

export function PaperDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [copied, setCopied] = useState(false);
  const paper = papers.find((item) => item.arxiv_id === id) ?? papers[0];

  async function copyLink() {
    await navigator.clipboard?.writeText(window.location.href);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  }

  return (
    <div>
      <button className="back-link" onClick={() => navigate(-1)}>
        ← Back to results
      </button>
      <article className="detail">
        <div className="detail-main">
          <p className="paper-meta">
            {paper.primary_category} · arXiv:{paper.arxiv_id}
            {paper.latest_version}
          </p>
          <h1>{paper.title}</h1>
          <p className="detail-authors">{paper.authors.join(", ")}</p>
          <p className="detail-actions">
            <a href={paper.abs_url} target="_blank" rel="noreferrer">
              Open on arXiv
            </a>
            {" | "}
            <a href={paper.pdf_url} target="_blank" rel="noreferrer">
              View PDF
            </a>
            {" | "}
            <button onClick={copyLink}>{copied ? "Link copied" : "Copy paper link"}</button>
            {" | "}
            <button title="Prototype only">Save paper</button>
          </p>
          <section className="full-abstract">
            <h2>Abstract</h2>
            <p>{paper.summary}</p>
          </section>
          {paper.comment && (
            <section>
              <h2>Comments</h2>
              <p>{paper.comment}</p>
            </section>
          )}
        </div>
        <aside className="metadata">
          <h2>Paper information</h2>
          <dl>
            <dt>Published</dt>
            <dd>{new Date(paper.published).toLocaleDateString()}</dd>
            <dt>Last updated</dt>
            <dd>{new Date(paper.updated).toLocaleDateString()}</dd>
            <dt>Version</dt>
            <dd>{paper.latest_version}</dd>
            <dt>Categories</dt>
            <dd>{paper.categories?.join(", ")}</dd>
            {paper.doi && (
              <>
                <dt>DOI</dt>
                <dd>{paper.doi}</dd>
              </>
            )}
            {paper.journal_ref && (
              <>
                <dt>Journal reference</dt>
                <dd>{paper.journal_ref}</dd>
              </>
            )}
          </dl>
        </aside>
      </article>
    </div>
  );
}

export function BrowsePage() {
  const [query, setQuery] = useState("");
  const visible = categories.filter((category) =>
    `${category.name} ${category.code}`.toLowerCase().includes(query.toLowerCase()),
  );

  return (
    <div>
      <PageHeading
        title="Browse Categories"
        text="Explore research using the arXiv subject classification system."
      />
      <label className="category-search">
        Find a category
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Name or category code"
        />
      </label>
      <section className="category-table">
        <h2>Computer Science</h2>
        <div className="table-head">
          <span>Code</span>
          <span>Subject</span>
          <span>Papers</span>
        </div>
        {visible.map((category) => (
          <Link to={`/categories/${category.code}`} key={category.code}>
            <code>{category.code}</code>
            <strong>{category.name}</strong>
            <span>{category.count}</span>
          </Link>
        ))}
      </section>
      <p className="new-papers-note">
        <strong>New Papers:</strong> Category pages can be filtered to show papers added
        since a selected date.
      </p>
    </div>
  );
}

export function TrendingPage() {
  return (
    <div className="narrow">
      <PageHeading
        title="Trending Searches"
        text="Frequently searched research topics from Scholarly Insight users."
      />
      <p className="notice">
        These figures reflect searches recorded by this application. They do not
        represent worldwide research activity.
      </p>
      <table className="trending-table">
        <thead>
          <tr>
            <th>Rank</th>
            <th>Search term</th>
            <th>Queries this week</th>
          </tr>
        </thead>
        <tbody>
          {trends.map(([term, count], index) => (
            <tr key={term}>
              <td>{index + 1}</td>
              <td>
                <Link to={`/search?q=${term}`}>{term}</Link>
              </td>
              <td>{count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function FuturePage({ type }: { type: "saved" | "history" }) {
  const saved = type === "saved";
  return (
    <div className="narrow">
      <PageHeading
        title={saved ? "Saved Papers" : "Reading History"}
        text={
          saved
            ? "A future home for bookmarked research papers."
            : "A future chronological list of recently viewed papers."
        }
      />
      <p className="notice">
        Preview only. This feature is not connected to accounts or persistent storage.
      </p>
      <EmptyState
        title={saved ? "No saved papers" : "No reading history"}
        text={
          saved
            ? "Bookmarked papers will appear here when saving is enabled."
            : "Recently viewed papers will appear here when history is enabled."
        }
      />
    </div>
  );
}

function PageHeading({ title, text }: { title: string; text: string }) {
  return (
    <header className="page-heading">
      <h1>{title}</h1>
      <p>{text}</p>
    </header>
  );
}

function EmptyState({ title, text }: { title: string; text: string }) {
  return (
    <div className="empty-state">
      <h2>{title}</h2>
      <p>{text}</p>
      <Link to="/">Return to Discover</Link>
    </div>
  );
}
