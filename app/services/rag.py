import re
from collections import Counter

from app.db import execute, fetch_all


def split_chunks(text: str, chunk_size: int = 650) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return []
    words = cleaned.split(" ")
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for word in words:
        current.append(word)
        current_len += len(word) + 1
        if current_len >= chunk_size:
            chunks.append(" ".join(current))
            current = []
            current_len = 0
    if current:
        chunks.append(" ".join(current))
    return chunks


def index_document(source_name: str, text: str, tool: str) -> int:
    chunks = split_chunks(text)
    count = 0
    for chunk in chunks:
        execute(
            "INSERT INTO knowledge_chunks(source_name, chunk_text, tool) VALUES(?,?,?)",
            (source_name, chunk, tool),
        )
        count += 1
    return count


def _score(query: str, chunk: str) -> float:
    q_words = re.findall(r"[a-zA-Zа-яА-Я0-9]+", query.lower())
    c_words = re.findall(r"[a-zA-Zа-яА-Я0-9]+", chunk.lower())
    if not q_words or not c_words:
        return 0.0
    q_count = Counter(q_words)
    c_count = Counter(c_words)
    common = sum(min(q_count[w], c_count[w]) for w in q_count)
    return common / max(len(set(q_words)), 1)


def search_knowledge(query: str, top_k: int = 5) -> list[dict]:
    rows = fetch_all(
        "SELECT id, source_name, chunk_text, tool FROM knowledge_chunks ORDER BY id DESC LIMIT 300"
    )
    ranked = []
    for row in rows:
        s = _score(query, row["chunk_text"])
        if s > 0:
            ranked.append(
                {
                    "id": row["id"],
                    "source_name": row["source_name"],
                    "tool": row["tool"],
                    "chunk_text": row["chunk_text"],
                    "score": round(s, 3),
                }
            )
    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked[:top_k]
