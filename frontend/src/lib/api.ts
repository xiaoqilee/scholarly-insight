export type Paper = {
  arxiv_id: string;
  latest_version: string;
  title: string;
  authors: string[];
  primary_category: string;
  published: string;
  updated: string;
  abs_url: string;
  pdf_url: string;
  summary?: string;
  categories?: string[];
  doi?: string;
  journal_ref?: string;
  comment?: string;
};

const abstracts = [
  "We analyze solution strategies for LeetCode dynamic programming problems and present a structured method for identifying states, transitions, and reusable optimization patterns.",
  "This study examines graph problems published on LeetCode and compares breadth-first search, depth-first search, shortest-path, and union-find approaches across common constraints.",
  "We introduce a benchmark based on LeetCode submissions for evaluating whether code-generation models can produce correct, efficient, and explainable algorithmic solutions.",
];

export const papers: Paper[] = [
  {
    arxiv_id: "2505.14278",
    latest_version: "v2",
    title: "A Systematic Study of Dynamic Programming Patterns on LeetCode",
    authors: ["Maya Chen", "Elias Hoffman", "Priya Raman"],
    primary_category: "cs.DS",
    published: "2025-05-21",
    updated: "2025-06-02",
    abs_url: "https://arxiv.org/abs/2505.14278",
    pdf_url: "https://arxiv.org/pdf/2505.14278",
    summary: abstracts[0],
    categories: ["cs.DS", "cs.PL", "cs.SE"],
    doi: "10.48550/arXiv.2505.14278",
    comment: "18 pages, 7 figures",
  },
  {
    arxiv_id: "2505.13142",
    latest_version: "v1",
    title: "Graph Algorithm Strategies for LeetCode Problem Solving",
    authors: ["Noah Williams", "Sara Ahmed", "Luis Ortega"],
    primary_category: "cs.DS",
    published: "2025-05-19",
    updated: "2025-05-19",
    abs_url: "https://arxiv.org/abs/2505.13142",
    pdf_url: "https://arxiv.org/pdf/2505.13142",
    summary: abstracts[1],
    categories: ["cs.DS", "cs.PL"],
    journal_ref: "LeetCode Problem Solving Workshop (2025)",
  },
  {
    arxiv_id: "2505.11903",
    latest_version: "v3",
    title: "Evaluating Code Generation Models with LeetCode Problems",
    authors: ["Aiko Tanaka", "Daniel Brooks"],
    primary_category: "cs.LG",
    published: "2025-05-17",
    updated: "2025-05-28",
    abs_url: "https://arxiv.org/abs/2505.11903",
    pdf_url: "https://arxiv.org/pdf/2505.11903",
    summary: abstracts[2],
    categories: ["cs.AI", "cs.SE", "cs.LG"],
    doi: "10.48550/arXiv.2505.11903",
  },
  {
    arxiv_id: "2505.10881",
    latest_version: "v1",
    title: "Time and Space Complexity Prediction for LeetCode Submissions",
    authors: ["Amelia Park", "Jon Bell", "Ravi Kumar"],
    primary_category: "cs.SE",
    published: "2025-05-15",
    updated: "2025-05-15",
    abs_url: "https://arxiv.org/abs/2505.10881",
    pdf_url: "https://arxiv.org/pdf/2505.10881",
    summary: "We study automated complexity analysis using accepted LeetCode submissions and propose a model for predicting asymptotic runtime and memory usage from source code.",
    categories: ["cs.SE", "cs.PL", "cs.DS"],
  },
];

export const categories = [
  { code: "cs.DS", name: "LeetCode Algorithms & Data Structures", count: "12.4k", color: "violet" },
  { code: "cs.PL", name: "LeetCode Programming Techniques", count: "8.7k", color: "blue" },
  { code: "cs.AI", name: "AI Solvers for LeetCode", count: "6.2k", color: "cyan" },
  { code: "cs.SE", name: "LeetCode Code Quality", count: "4.8k", color: "amber" },
  { code: "cs.LG", name: "Learning from LeetCode Submissions", count: "3.9k", color: "green" },
  { code: "cs.CC", name: "LeetCode Complexity Analysis", count: "3.1k", color: "rose" },
];

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

export async function searchPapers(query = "", category = "") {
  if (API_BASE_URL) {
    const params = new URLSearchParams({ q: query, category, page: "1", page_size: "10" });
    const response = await fetch(`${API_BASE_URL}/api/search?${params}`);
    if (!response.ok) throw new Error("Search request failed");
    return response.json();
  }
  const needle = query.toLowerCase();
  const results = papers.filter(
    (paper) =>
      (!needle ||
        `${paper.title} ${paper.authors.join(" ")} ${paper.summary}`.toLowerCase().includes(needle)) &&
      (!category || paper.primary_category === category),
  );
  return { total_results: results.length, page: 1, page_size: 10, total_pages: 1, source: "mock", cached: false, stale: false, query, results };
}
