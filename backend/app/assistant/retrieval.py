"""Local hybrid context retrieval for ticket drafting.

The index is intentionally local and ephemeral: SQLite remains the source of
truth, and knowledge files can be edited without a migration or rebuild step.
LlamaIndex node/retriever primitives provide the context contract while bm25s
keeps Windows installs free of a C++ compiler dependency.
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

import bm25s
from llama_index.core import QueryBundle
from llama_index.core.schema import NodeWithScore, TextNode

from ..state.store import TicketStore

PROJECT_ROOT = Path(__file__).resolve().parents[3]
KNOWLEDGE_ROOT = PROJECT_ROOT / "knowledge"


def _tokens(text: str) -> list[str]:
    lowered = (text or "").lower()
    tokens: list[str] = []
    for part in re.findall(r"[\u4e00-\u9fff]+|[a-z0-9_]{2,}", lowered):
        if re.fullmatch(r"[a-z0-9_]+", part):
            tokens.append(part)
            continue
        if len(part) <= 2:
            tokens.append(part)
        else:
            tokens.extend(part[index:index + 2] for index in range(len(part) - 1))
            tokens.extend(part[index:index + 3] for index in range(len(part) - 2))
    return list(dict.fromkeys(tokens))


def _token_text(text: str) -> str:
    return " ".join(_tokens(text))


def _knowledge_chunks() -> list[tuple[str, str, str]]:
    chunks: list[tuple[str, str, str]] = []
    if not KNOWLEDGE_ROOT.is_dir():
        return chunks
    for path in sorted(KNOWLEDGE_ROOT.glob("*.md")):
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        title = next((line.lstrip("# ") for line in content.splitlines() if line.startswith("# ")), path.stem)
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()]
        for index, paragraph in enumerate(paragraphs):
            chunks.append((f"{path.name}#{index + 1}", f"{title} / {path.name}", paragraph))
    return chunks


class LocalTicketRetriever:
    """Search SOP documents and historical tickets with BM25."""

    def search(self, query: str, top_k: int = 6) -> dict[str, list[dict[str, Any]]]:
        documents: list[TextNode] = []
        for source_id, title, text in _knowledge_chunks():
            documents.append(
                TextNode(
                    text=text,
                    id_=source_id,
                    metadata={"kind": "knowledge", "title": title, "source": source_id},
                )
            )
        for ticket in TicketStore.list_tickets(limit=200):
            text = "\n".join(
                value for value in (
                    ticket.get("title"),
                    ticket.get("description"),
                    ticket.get("primary_dept"),
                    ticket.get("status"),
                ) if value
            )
            documents.append(
                TextNode(
                    text=text,
                    id_=ticket["id"],
                    metadata={
                        "kind": "ticket",
                        "title": ticket.get("title", ""),
                        "ticket_id": ticket["id"],
                        "status": ticket.get("status", ""),
                        "department": ticket.get("primary_dept", ""),
                    },
                )
            )

        empty = {"knowledge": [], "similar_tickets": []}
        query_tokens = _tokens(query)
        if not documents or not query_tokens:
            return empty

        corpus = [_token_text(node.text) for node in documents]
        corpus_tokens = bm25s.tokenize(
            corpus,
            stopwords=[],
            token_pattern=r"\S+",
            show_progress=False,
            return_ids=False,
        )
        index = bm25s.BM25()
        index.index(corpus_tokens, show_progress=False)
        query_token_ids = bm25s.tokenize(
            [" ".join(query_tokens)],
            stopwords=[],
            token_pattern=r"\S+",
            show_progress=False,
            return_ids=False,
        )
        results, scores = index.retrieve(
            query_token_ids,
            k=min(top_k, len(documents)),
            show_progress=False,
        )

        knowledge: list[dict[str, Any]] = []
        tickets: list[dict[str, Any]] = []
        result_ids = results[0].tolist() if hasattr(results[0], "tolist") else list(results[0])
        score_values = scores[0].tolist() if hasattr(scores[0], "tolist") else list(scores[0])
        for raw_index, raw_score in zip(result_ids, score_values, strict=False):
            score = float(raw_score)
            if score <= 0 or math.isnan(score):
                continue
            node: TextNode = documents[int(raw_index)]
            ranked = NodeWithScore(node=node, score=score)
            item = {
                "title": ranked.node.metadata.get("title"),
                "snippet": ranked.node.text[:260],
                "score": round(ranked.score or 0.0, 4),
            }
            if ranked.node.metadata.get("kind") == "knowledge":
                item["source"] = ranked.node.metadata.get("source")
                knowledge.append(item)
            else:
                item.update({
                    "id": ranked.node.metadata.get("ticket_id"),
                    "status": ranked.node.metadata.get("status"),
                    "department": ranked.node.metadata.get("department"),
                })
                tickets.append(item)

        return {
            "knowledge": knowledge[:4],
            "similar_tickets": tickets[:4],
        }

    def search_bundle(self, query: str, top_k: int = 6) -> tuple[QueryBundle, dict[str, list[dict[str, Any]]]]:
        bundle = QueryBundle(query_str=query)
        return bundle, self.search(bundle.query_str, top_k=top_k)


local_retriever = LocalTicketRetriever()
