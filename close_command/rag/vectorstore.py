"""
ChromaDB vector store manager for Close Command.
Four collections: historical_exceptions, elimination_precedents,
policy_documents, period_journals.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)

# Guard chromadb import — crashes on Python 3.14 due to protobuf/grpc issue
try:
    import chromadb
    _CHROMADB_AVAILABLE = True
except Exception as _chroma_err:
    chromadb = None  # type: ignore
    _CHROMADB_AVAILABLE = False
    logger.warning("chromadb unavailable: %s — RAG features disabled", _chroma_err)

# Use SentenceTransformer if available (local dev), otherwise fall back to
# chromadb's built-in ONNX MiniLM embedder (no torch — works on Streamlit Cloud)
_USE_SENTENCE_TRANSFORMERS = False
if _CHROMADB_AVAILABLE:
    try:
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
        _USE_SENTENCE_TRANSFORMERS = True
    except Exception:
        _USE_SENTENCE_TRANSFORMERS = False

COLLECTION_NAMES = [
    "historical_exceptions",
    "elimination_precedents",
    "policy_documents",
    "period_journals",
]


class CloseCommandVectorStore:
    """Manages ChromaDB collections for Close Command RAG."""

    def __init__(self, persist_directory: str = "./close_command_vectorstore") -> None:
        if not _CHROMADB_AVAILABLE:
            raise ImportError("chromadb is not available in this environment — RAG features disabled")
        self.persist_directory = persist_directory
        try:
            self._client = chromadb.PersistentClient(path=persist_directory)
            # Use SentenceTransformer locally; fall back to ONNX on Streamlit Cloud
            if _USE_SENTENCE_TRANSFORMERS:
                self._embedding_fn = SentenceTransformerEmbeddingFunction(
                    model_name="sentence-transformers/all-MiniLM-L6-v2"
                )
            else:
                from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2
                self._embedding_fn = ONNXMiniLM_L6_V2()
            self._collections: dict[str, chromadb.Collection] = {}
            self._init_collections()
            logger.info("VectorStore initialised at %s", persist_directory)
        except Exception as exc:
            logger.error("VectorStore init failed: %s", exc)
            raise

    # ──────────────────────────────────────────────────────────────────────
    # Collection setup
    # ──────────────────────────────────────────────────────────────────────

    def _init_collections(self) -> None:
        """Create or get all four ChromaDB collections."""
        for name in COLLECTION_NAMES:
            try:
                collection = self._client.get_or_create_collection(
                    name=name,
                    embedding_function=self._embedding_fn,
                    metadata={"hnsw:space": "cosine"},
                )
                self._collections[name] = collection
                logger.debug("Collection ready: %s", name)
            except Exception as exc:
                logger.error("Failed to init collection %s: %s", name, exc)
                raise

    def _get_collection(self, name: str) -> chromadb.Collection:
        if name not in self._collections:
            raise KeyError(f"Unknown collection: {name}")
        return self._collections[name]

    # ──────────────────────────────────────────────────────────────────────
    # Add documents
    # ──────────────────────────────────────────────────────────────────────

    def add_historical_exception(self, exception_data: dict) -> str:
        """Index a historical matching exception. Returns the document id."""
        try:
            doc_id = exception_data.get("txn_id") or str(uuid.uuid4())
            seller = exception_data.get("seller_entity", "")
            buyer = exception_data.get("buyer_entity", "")
            rule_code = exception_data.get("rule_code", "")
            gap_pct = exception_data.get("gap_pct", 0.0)
            root_cause = exception_data.get("root_cause", "unknown")
            resolution = exception_data.get("resolution", "")
            period = exception_data.get("period", "")

            document = (
                f"Exception: {seller} vs {buyer} | Rule: {rule_code} | "
                f"Gap: {gap_pct:.2f}% | Root cause: {root_cause} | "
                f"Resolution: {resolution} | Period: {period}"
            )
            metadata = {
                "seller_entity": seller,
                "buyer_entity": buyer,
                "rule_code": rule_code,
                "gap_pct": float(gap_pct),
                "root_cause": root_cause,
                "resolution": resolution,
                "period": period,
                "doc_type": "historical_exception",
            }

            collection = self._get_collection("historical_exceptions")
            collection.upsert(
                ids=[doc_id],
                documents=[document],
                metadatas=[metadata],
            )
            logger.debug("Indexed historical exception id=%s", doc_id)
            return doc_id
        except Exception as exc:
            logger.error("add_historical_exception failed: %s", exc)
            raise

    def add_elimination_precedent(self, entry_data: dict) -> str:
        """Index an elimination entry as a precedent. Returns the document id."""
        try:
            doc_id = entry_data.get("txn_id") or str(uuid.uuid4())
            rule_code = entry_data.get("rule_code", "")
            seller = entry_data.get("seller", "")
            buyer = entry_data.get("buyer", "")
            account = entry_data.get("account", "")
            amount_usd = entry_data.get("amount_usd", 0.0)
            entity_method = entry_data.get("entity_method", "GLOBAL")
            pcon = entry_data.get("pcon", 100.0)
            period = entry_data.get("period", "")

            document = (
                f"Precedent Rule: {rule_code} | Seller: {seller} | Buyer: {buyer} | "
                f"Account: {account} | Amount USD: {amount_usd:,.2f} | "
                f"Method: {entity_method} | pcon: {pcon}% | Period: {period}"
            )
            metadata = {
                "rule_code": rule_code,
                "seller": seller,
                "buyer": buyer,
                "account": account,
                "amount_usd": float(amount_usd),
                "entity_method": entity_method,
                "pcon": float(pcon),
                "period": period,
                "doc_type": "elimination_precedent",
            }

            collection = self._get_collection("elimination_precedents")
            collection.upsert(
                ids=[doc_id],
                documents=[document],
                metadatas=[metadata],
            )
            logger.debug("Indexed elimination precedent id=%s", doc_id)
            return doc_id
        except Exception as exc:
            logger.error("add_elimination_precedent failed: %s", exc)
            raise

    def add_policy_document(self, doc_data: dict) -> str:
        """Index a policy document. Returns the document id."""
        try:
            doc_id = doc_data.get("doc_id") or str(uuid.uuid4())
            title = doc_data.get("title", "")
            content = doc_data.get("content", "")
            category = doc_data.get("category", "")
            rule_code = doc_data.get("rule_code", "")

            document = f"Policy: {title} | Category: {category} | {content}"
            metadata = {
                "title": title,
                "category": category,
                "rule_code": rule_code,
                "doc_type": "policy_document",
            }

            collection = self._get_collection("policy_documents")
            collection.upsert(
                ids=[doc_id],
                documents=[document],
                metadatas=[metadata],
            )
            logger.debug("Indexed policy document id=%s", doc_id)
            return doc_id
        except Exception as exc:
            logger.error("add_policy_document failed: %s", exc)
            raise

    def add_period_journal(self, journal_data: dict) -> str:
        """Index a period journal entry. Returns the document id."""
        try:
            doc_id = journal_data.get("txn_id") or str(uuid.uuid4())
            seller = journal_data.get("seller", "")
            buyer = journal_data.get("buyer", "")
            rule_code = journal_data.get("rule_code", "")
            account = journal_data.get("account", "")
            amount_usd = journal_data.get("amount_usd", 0.0)
            period = journal_data.get("period", "")
            scenario = journal_data.get("scenario", "")

            document = (
                f"Journal: {seller} -> {buyer} | Rule: {rule_code} | "
                f"Account: {account} | Amount USD: {amount_usd:,.2f} | "
                f"Period: {period} | Scenario: {scenario}"
            )
            metadata = {
                "seller": seller,
                "buyer": buyer,
                "rule_code": rule_code,
                "account": account,
                "amount_usd": float(amount_usd),
                "period": period,
                "scenario": scenario,
                "doc_type": "period_journal",
            }

            collection = self._get_collection("period_journals")
            collection.upsert(
                ids=[doc_id],
                documents=[document],
                metadatas=[metadata],
            )
            logger.debug("Indexed period journal id=%s", doc_id)
            return doc_id
        except Exception as exc:
            logger.error("add_period_journal failed: %s", exc)
            raise

    # ──────────────────────────────────────────────────────────────────────
    # Query
    # ──────────────────────────────────────────────────────────────────────

    def query_historical_exceptions(
        self, query_text: str, n_results: int = 3
    ) -> list[dict]:
        """Query the historical_exceptions collection by similarity."""
        try:
            collection = self._get_collection("historical_exceptions")
            count = collection.count()
            if count == 0:
                return []
            n = min(n_results, count)
            results = collection.query(
                query_texts=[query_text],
                n_results=n,
                include=["documents", "metadatas", "distances"],
            )
            return self._format_query_results(results)
        except Exception as exc:
            logger.error("query_historical_exceptions failed: %s", exc)
            return []

    def query_elimination_precedents(
        self, query_text: str, rule_code: str, n_results: int = 3
    ) -> list[dict]:
        """Query the elimination_precedents collection, filtered by rule_code."""
        try:
            collection = self._get_collection("elimination_precedents")
            count = collection.count()
            if count == 0:
                return []
            n = min(n_results, count)
            where_filter: dict[str, Any] = {"rule_code": {"$eq": rule_code}} if rule_code else {}
            query_kwargs: dict[str, Any] = {
                "query_texts": [query_text],
                "n_results": n,
                "include": ["documents", "metadatas", "distances"],
            }
            if where_filter:
                query_kwargs["where"] = where_filter
            results = collection.query(**query_kwargs)
            return self._format_query_results(results)
        except Exception as exc:
            logger.error("query_elimination_precedents failed: %s", exc)
            return []

    def query_policy_documents(
        self, query_text: str, n_results: int = 5
    ) -> list[dict]:
        """Query the policy_documents collection."""
        try:
            collection = self._get_collection("policy_documents")
            count = collection.count()
            if count == 0:
                return []
            n = min(n_results, count)
            results = collection.query(
                query_texts=[query_text],
                n_results=n,
                include=["documents", "metadatas", "distances"],
            )
            return self._format_query_results(results)
        except Exception as exc:
            logger.error("query_policy_documents failed: %s", exc)
            return []

    def query_period_journals(
        self, query_text: str, period: str, n_results: int = 3
    ) -> list[dict]:
        """Query the period_journals collection, filtered by period."""
        try:
            collection = self._get_collection("period_journals")
            count = collection.count()
            if count == 0:
                return []
            n = min(n_results, count)
            where_filter: dict[str, Any] = {"period": {"$eq": period}} if period else {}
            query_kwargs: dict[str, Any] = {
                "query_texts": [query_text],
                "n_results": n,
                "include": ["documents", "metadatas", "distances"],
            }
            if where_filter:
                query_kwargs["where"] = where_filter
            results = collection.query(**query_kwargs)
            return self._format_query_results(results)
        except Exception as exc:
            logger.error("query_period_journals failed: %s", exc)
            return []

    # ──────────────────────────────────────────────────────────────────────
    # Seeding
    # ──────────────────────────────────────────────────────────────────────

    def seed_policy_documents(self) -> None:
        """Seed the policy_documents collection with all 28 elimination rules
        and entity hierarchy information."""
        try:
            from data.rules import ELIMINATION_RULES
            from data.entities import ENTITY_REGISTRY

            seeded_count = 0

            # Seed elimination rules
            for rule_code, rule in ELIMINATION_RULES.items():
                doc_data = {
                    "doc_id": f"policy-rule-{rule_code}",
                    "title": f"Elimination Rule {rule_code}: {rule['description']}",
                    "content": (
                        f"Category: {rule['category']}. "
                        f"Dr Account: {rule['dr_account']}. "
                        f"Cr Account: {rule['cr_account']}. "
                        f"Formula: {rule['formula_description']}. "
                        f"NCI Applicable: {rule['nci_applicable']}. "
                        f"Gate Conditions: {'; '.join(rule['gate_conditions'])}."
                    ),
                    "category": rule["category"],
                    "rule_code": rule_code,
                }
                self.add_policy_document(doc_data)
                seeded_count += 1

            # Seed entity hierarchy info
            for entity_code, entity in ENTITY_REGISTRY.items():
                doc_data = {
                    "doc_id": f"policy-entity-{entity_code}",
                    "title": f"Entity Profile: {entity_code} - {entity['entity_name']}",
                    "content": (
                        f"Entity Code: {entity_code}. "
                        f"Name: {entity['entity_name']}. "
                        f"Method: {entity['entity_method']}. "
                        f"Currency: {entity['currency']}. "
                        f"pcon: {entity['pcon']}%. "
                        f"pown: {entity['pown']}%. "
                        f"Parent: {entity.get('parent', 'None')}. "
                        f"NCI Entity: {entity['is_nci']}. "
                        f"Description: {entity['description']}."
                    ),
                    "category": "ENTITY_PROFILE",
                    "rule_code": "",
                }
                self.add_policy_document(doc_data)
                seeded_count += 1

            logger.info("Seeded %d policy documents", seeded_count)
        except Exception as exc:
            logger.error("seed_policy_documents failed: %s", exc)
            raise

    # ──────────────────────────────────────────────────────────────────────
    # Stats
    # ──────────────────────────────────────────────────────────────────────

    def get_collection_stats(self) -> dict:
        """Return document counts for all four collections."""
        stats: dict[str, int] = {}
        for name, collection in self._collections.items():
            try:
                stats[name] = collection.count()
            except Exception as exc:
                logger.warning("Could not count collection %s: %s", name, exc)
                stats[name] = -1
        return stats

    # ──────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _format_query_results(results: dict) -> list[dict]:
        """Normalise ChromaDB query results into a flat list of dicts."""
        formatted: list[dict] = []
        try:
            ids = results.get("ids", [[]])[0]
            documents = results.get("documents", [[]])[0]
            metadatas = results.get("metadatas", [[]])[0]
            distances = results.get("distances", [[]])[0]

            for i, doc_id in enumerate(ids):
                formatted.append(
                    {
                        "id": doc_id,
                        "document": documents[i] if i < len(documents) else "",
                        "metadata": metadatas[i] if i < len(metadatas) else {},
                        "distance": distances[i] if i < len(distances) else 1.0,
                        "similarity": round(
                            1.0 - (distances[i] if i < len(distances) else 1.0), 4
                        ),
                    }
                )
        except Exception as exc:
            logger.error("_format_query_results failed: %s", exc)
        return formatted
