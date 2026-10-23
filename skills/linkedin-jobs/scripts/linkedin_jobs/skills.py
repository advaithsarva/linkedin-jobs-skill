"""Skill taxonomy + deterministic extraction (no LLM, no network). Extend via config `extra_skills`."""
from __future__ import annotations

import re
from functools import lru_cache

# canonical name -> aliases (case-insensitive unless noted)
SKILLS: dict[str, list[str]] = {
    # languages
    "Python": ["python", "python3"], "Java": ["java"], "JavaScript": ["javascript", "js", "ecmascript"],
    "TypeScript": ["typescript"], "C++": ["c++", "cpp"], "C#": ["c#", "csharp"], "Go": ["golang"],
    "Rust": ["rust"], "Kotlin": ["kotlin"], "Swift": ["swift"], "Scala": ["scala"], "Ruby": ["ruby"],
    "PHP": ["php"], "R": ["r programming", "r language", "rstudio"], "SQL": ["sql", "t-sql", "pl/sql"],
    "Bash": ["bash", "shell scripting"], "MATLAB": ["matlab"], "Julia": ["julia lang"], "Dart": ["dart"],
    # web / backend
    "React": ["react", "react.js", "reactjs"], "Next.js": ["next.js", "nextjs"], "Vue": ["vue", "vue.js"],
    "Angular": ["angular"], "Node.js": ["node.js", "nodejs", "node"], "Express": ["express.js", "expressjs"],
    "Django": ["django"], "Flask": ["flask"], "FastAPI": ["fastapi"], "Spring Boot": ["spring boot", "spring"],
    ".NET": [".net", "dotnet", "asp.net"], "Rails": ["ruby on rails", "rails"], "GraphQL": ["graphql"],
    "REST APIs": ["rest api", "rest apis", "restful"], "gRPC": ["grpc"], "HTML/CSS": ["html", "css", "html5", "css3"],
    "Tailwind": ["tailwind", "tailwindcss"], "Microservices": ["microservices", "microservice"],
    # data / ML / AI
    "Machine Learning": ["machine learning", "ml"], "Deep Learning": ["deep learning"],
    "NLP": ["nlp", "natural language processing"], "Computer Vision": ["computer vision", "cv"],
    "LLMs": ["llm", "llms", "large language model", "large language models"],
    "Generative AI": ["generative ai", "genai", "gen ai"], "RAG": ["rag", "retrieval augmented generation",
                                                                      "retrieval-augmented generation"],
    "Reinforcement Learning": ["reinforcement learning", "rlhf"], "PyTorch": ["pytorch", "torch"],
    "TensorFlow": ["tensorflow"], "Keras": ["keras"], "scikit-learn": ["scikit-learn", "sklearn"],
    "Hugging Face": ["hugging face", "huggingface", "transformers"], "LangChain": ["langchain"],
    "LlamaIndex": ["llamaindex", "llama index"], "OpenAI API": ["openai api", "openai"],
    "Pandas": ["pandas"], "NumPy": ["numpy"], "SciPy": ["scipy"], "Spark": ["spark", "pyspark", "apache spark"],
    "Hadoop": ["hadoop"], "Kafka": ["kafka"], "Airflow": ["airflow"], "dbt": ["dbt"], "ETL": ["etl", "elt"],
    "Data Analysis": ["data analysis", "data analytics"], "Statistics": ["statistics", "statistical modeling"],
    "A/B Testing": ["a/b testing", "ab testing", "experimentation"], "Tableau": ["tableau"],
    "Power BI": ["power bi", "powerbi"], "Excel": ["excel", "microsoft excel"], "MLOps": ["mlops"],
    "Feature Engineering": ["feature engineering"], "Time Series": ["time series", "forecasting"],
    "XGBoost": ["xgboost", "lightgbm"], "OpenCV": ["opencv"], "CUDA": ["cuda"], "Quantum Computing": [
        "quantum computing", "qiskit", "pennylane", "cirq"],
    # databases
    "PostgreSQL": ["postgresql", "postgres"], "MySQL": ["mysql"], "MongoDB": ["mongodb", "mongo"],
    "Redis": ["redis"], "Elasticsearch": ["elasticsearch", "opensearch"], "Cassandra": ["cassandra"],
    "DynamoDB": ["dynamodb"], "SQLite": ["sqlite"], "Snowflake": ["snowflake"], "BigQuery": ["bigquery"],
    "Vector Databases": ["vector database", "vector db", "pinecone", "weaviate", "faiss", "chroma", "milvus"],
    # cloud / devops
    "AWS": ["aws", "amazon web services"], "Azure": ["azure"], "GCP": ["gcp", "google cloud"],
    "Docker": ["docker"], "Kubernetes": ["kubernetes", "k8s"], "Terraform": ["terraform"],
    "CI/CD": ["ci/cd", "cicd", "continuous integration", "github actions", "jenkins", "gitlab ci"],
    "Linux": ["linux", "unix"], "Git": ["git", "github", "gitlab"], "DevOps": ["devops"], "SRE": ["sre"],
    "Serverless": ["serverless", "lambda"], "Ansible": ["ansible"], "Prometheus": ["prometheus", "grafana"],
    # mobile / other
    "Android": ["android"], "iOS": ["ios"], "Flutter": ["flutter"], "React Native": ["react native"],
    "Unity": ["unity"], "Embedded": ["embedded systems", "embedded", "rtos", "firmware"],
    "Testing": ["unit testing", "pytest", "junit", "selenium", "test automation", "qa"],
    "Cybersecurity": ["cybersecurity", "cyber security", "infosec", "penetration testing"],
    "Blockchain": ["blockchain", "solidity", "web3"], "Data Structures & Algorithms": [
        "data structures", "algorithms", "dsa"], "System Design": ["system design", "distributed systems"],
    "Agile": ["agile", "scrum"], "Jira": ["jira"], "Figma": ["figma"],
    "Research": ["research", "publications", "arxiv"], "Communication": ["communication skills"],
}
SKILLS["Testing"] = ["unit testing", "pytest", "junit", "selenium", "test automation", "qa engineer",
                     "quality assurance", "integration testing"]

_CASE_SENSITIVE = {"rust", "swift", "ruby", "dart", "unity", "spring", "julia lang", "transformers", "lambda",
                   "node", "express", "flask", "cv", "research", "embedded", "agile", "excel"}
_NO_SELF_ALIAS = {"Testing", "Research", "Communication", "Agile", "Embedded"}
# soft / catch-all skills: useful to detect, useless as "learn this next" advice
GENERIC_SKILLS = {"Communication", "Research", "Agile", "Jira"}
_BOUNDARY_L = r"(?<![\w+#.])"
_BOUNDARY_R = r"(?![\w+#]|\.\w)"


@lru_cache(maxsize=8)
def _compiled(extra_key: tuple) -> tuple[re.Pattern[str], dict[str, str]]:
    table = {k: list(v) for k, v in SKILLS.items()}
    for k, v in extra_key:
        table.setdefault(k, []).extend(v)
    alias_to_canon: dict[str, str] = {}
    for canon, aliases in table.items():
        own = [] if canon in _NO_SELF_ALIAS else [canon.lower()]  # "testing"/"research" alone are just English
        for a in [*own, *aliases]:
            alias_to_canon[a.lower()] = canon
    alts = sorted(alias_to_canon, key=len, reverse=True)
    pat = re.compile(_BOUNDARY_L + "(" + "|".join(re.escape(a) for a in alts) + ")" + _BOUNDARY_R, re.I)
    return pat, alias_to_canon


def extract_skills(text: str, extra: dict[str, list[str]] | None = None) -> dict[str, int]:
    """Return {canonical_skill: mention_count} found in text, most frequent first."""
    pat, amap = _compiled(tuple(sorted((k, tuple(v)) for k, v in (extra or {}).items())))
    counts: dict[str, int] = {}
    for m in pat.finditer(text):
        word = m.group(1)
        # Everyday English words that are also skills only count when capitalised ("Rust", not "rust").
        if word.lower() in _CASE_SENSITIVE and not word[0].isupper():
            continue
        canon = amap[word.lower()]
        counts[canon] = counts.get(canon, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


_STOP = set("""a an the and or of for to in on at by with from as is are be was were will would can could should may might
this that these those it its you your we our they their i he she them us not no yes all any each every more most
other such than then there here what which who whom whose when where why how also into over under about above
below up down out off again further once only own same so too very just etc per including include includes
experience experienced work working works job role team teams company companies ability able strong good great
excellent knowledge skills skill understanding years year plus preferred required requirements responsibilities
responsibility candidate candidates position positions looking join opportunity benefits salary apply application
de la le les des du un une et en pour avec sur dans par que qui der die das und mit für von zu im ist ein eine
el los las del y con para por una es se su al lo como mas más do da dos das os um uma para com que não""".split())


_NOT_SKILL = set("""present current bachelor master science degree university college school hospital
january february march april may june july august september october november december monday tuesday""".split())


def extract_terms(text: str, top: int = 12) -> dict[str, int]:
    """Profession-agnostic fallback: key words and two-word phrases (no taxonomy needed).

    Used when a resume or posting is outside the built-in tech taxonomy (nursing, accounting, design, trades...).
    Phrases never span punctuation or line breaks, so "IV therapy, ACLS certified" cannot yield "Therapy Acls".
    """
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    if len(first.split()) <= 4 and not re.search(r"\d", first):  # a resume's first line is usually the person's name
        text = text.replace(first, " ", 1)
    short = len(text) < 2500  # a one-page resume repeats little, so one mention is enough there
    counts: dict[str, int] = {}
    for segment in re.split(r"[\n.,;:()|/\u2022\u2013\u2014!?]+", text):
        prev = None
        for raw in re.findall(r"[^\W\d_][\w'+#-]{1,}", segment):
            w = raw.lower()
            if w in _STOP or (len(w) < 3 and not raw.isupper()):
                prev = None
                continue
            counts[w] = counts.get(w, 0) + 1
            if prev:
                counts[f"{prev} {w}"] = counts.get(f"{prev} {w}", 0) + 1
            prev = w
    floor = 1 if short else 2
    phrases = {k: v for k, v in counts.items() if " " in k and v >= floor}
    words = {k: v for k, v in counts.items() if " " not in k and v >= 2}
    for ph in phrases:  # a word that only ever appears inside a kept phrase is redundant
        for w in ph.split():
            if w in words and words[w] <= phrases[ph]:
                words.pop(w)
    # acronyms (ACLS, EHR, GAAP, CAD) and mid-sentence proper nouns (Epic, Workday) are strong skill signals
    marks: dict[str, int] = {}
    for m in re.finditer(r"\b([A-Z]{2,6}|[A-Z][a-z]{3,})\b", text):
        w = m.group(1)
        at_start = m.start() == 0 or text[max(0, m.start() - 2):m.start()] in (". ", "\n")
        if w.lower() in _STOP or w.lower() in _NOT_SKILL or (at_start and not w.isupper()):
            continue
        marks[w if w.isupper() else w.title()] = 2
    merged: dict[str, int] = {**{k.title(): v for k, v in phrases.items()}, **{k.title(): v for k, v in words.items()}}
    for k, v in marks.items():
        merged[k] = max(merged.get(k, 0), v)
    ranked = sorted(merged.items(), key=lambda kv: (-kv[1], -len(kv[0])))
    return dict(ranked[:top])
