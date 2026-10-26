"""Subset of the arXiv taxonomy used for browse menus.

Full list: https://arxiv.org/category_taxonomy
"""
CATEGORIES: dict[str, dict[str, str]] = {
    "cs": {
        "cs.AI": "Artificial Intelligence",
        "cs.CL": "Computation and Language",
        "cs.CR": "Cryptography and Security",
        "cs.CV": "Computer Vision and Pattern Recognition",
        "cs.DB": "Databases",
        "cs.DC": "Distributed, Parallel, and Cluster Computing",
        "cs.DS": "Data Structures and Algorithms",
        "cs.HC": "Human-Computer Interaction",
        "cs.IR": "Information Retrieval",
        "cs.LG": "Machine Learning",
        "cs.NE": "Neural and Evolutionary Computing",
        "cs.PL": "Programming Languages",
        "cs.RO": "Robotics",
        "cs.SE": "Software Engineering",
    },
    "math": {
        "math.CO": "Combinatorics",
        "math.OC": "Optimization and Control",
        "math.PR": "Probability",
        "math.ST": "Statistics Theory",
    },
    "physics": {
        "astro-ph.CO": "Cosmology and Nongalactic Astrophysics",
        "cond-mat.str-el": "Strongly Correlated Electrons",
        "hep-th": "High Energy Physics - Theory",
        "quant-ph": "Quantum Physics",
    },
    "q-bio": {"q-bio.NC": "Neurons and Cognition", "q-bio.GN": "Genomics"},
    "q-fin": {
        "q-fin.CP": "Computational Finance",
        "q-fin.PM": "Portfolio Management",
        "q-fin.ST": "Statistical Finance",
    },
    "stat": {"stat.ML": "Machine Learning", "stat.ME": "Methodology"},
    "eess": {"eess.SP": "Signal Processing", "eess.IV": "Image and Video Processing"},
    "econ": {"econ.EM": "Econometrics"},
}

ALL_CODES = {code for group in CATEGORIES.values() for code in group} | set(CATEGORIES)
