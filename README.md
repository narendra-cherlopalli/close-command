# ⚗️ Close Command

**Agentic Financial Close Engine — Group Consolidation for the AI Era**

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2+-1C3C3C?style=flat-square)](https://github.com/langchain-ai/langgraph)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.35+-FF4B4B?style=flat-square&logo=streamlit&logoColor=white)](https://streamlit.io)
[![Status](https://img.shields.io/badge/Status-Early_Build-EF9F27?style=flat-square)]()
[![License](https://img.shields.io/badge/License-MIT-22C55E?style=flat-square)](LICENSE)

---

> **Close Command** is an agentic system for the group financial close — intercompany elimination, journal entry generation, multi-currency consolidation, and human-in-the-loop review. Built on LangGraph, RAG, and MCP. Designed from 25 years of FP&A experience, with the governance standards that survive an external audit.

---

## ⚠️ Status: early build, entry point only

This repository currently contains the **Streamlit application entry point** (`main.py`) and this README. The agent modules, RAG layer, MCP servers, ML models, and governance package referenced below are being added incrementally — see [Roadmap](#roadmap) for what's built versus what's in progress.

`main.py` will not run standalone yet — it imports from `close_command/agents/`, `close_command/orchestrator/`, `close_command/rag/`, and other packages that are not yet in this repo. This is published early intentionally, to document the architecture and design principles before the full codebase lands.

---

## What this is

Most finance AI projects generate text. Close Command is designed to generate **auditable double-entry journal entries** from matched intercompany transactions, run them through a validation pipeline, pause for human review, and produce a consolidated group P&L and balance sheet.

The architecture enforces a hard separation between what AI determines (root cause hypotheses, anomaly flags, variance commentary) and what deterministic rules execute (journal amounts, rule code selection, consolidation percentages). That separation is not a design preference — it is a financial control.

---

## Architecture (target)

```
Data Sources (ERP / CSV / Excel)
         │
         ▼
┌─────────────────────────────────────────────────────┐
│              LangGraph Orchestrator                  │
│     State graph · HITL interrupt · Checkpointing    │
└──────┬──────────┬──────────┬──────────┬─────────────┘
       │          │          │          │
       ▼          ▼          ▼          ▼
 Ingestion    Matching   Elimination  Validation
  Agent        Agent       Agent       Agent
  (format     (bilateral  (double-    (HFM rules
  detect,     IC match,   entry       balance
  FX conv)    gap score)  journals)   proof)
       │          │          │          │
       └──────────┴──────────┴──────────┘
                           │
                    ┌──────▼──────┐
                    │   Review    │  ← HITL Gate
                    │   Agent     │    (LangGraph
                    └──────┬──────┘     interrupt)
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
        Output Agent           Consolidation Agent
        (JLF · Excel ·         (PCon% · Group P&L
         Audit trail)           · Balance Sheet)
              │
              ▼
     ┌────────────────┐     ┌────────────────┐
     │   RAG Layer    │     │   MCP Servers  │
     │  VectorStore   │     │  ERP · Notify  │
     │  Retriever     │     │  Storage · Auth│
     │  Indexer       │     │  Audit         │
     └────────────────┘     └────────────────┘
```

---

## Key design principles

**1. Deterministic before probabilistic.** Journal amounts, rule code selection, and consolidation percentages are always computed deterministically. The LLM advisory layer sits above, never underneath, the calculation layer.

**2. Governance is architecture.** Escalation paths, audit trails, HITL approval gates, and rollback capability are designed into the graph topology — not bolted on as configuration after deployment.

**3. Named ownership before deployment.** Every agent requires a named human accountable for its outputs before the pipeline runs. The system refuses to start if ownership fields are blank.

**4. Audit trail at runtime.** Every agent decision — what it decided, why, which threshold triggered escalation — is captured in an immutable hash-chained audit log at the moment of action.

**5. Evaluation against prior period baselines.** ValidationAgent compares every journal against historical patterns via the RAG layer. A correct-format journal with an unusual amount is flagged before the HITL gate.

These principles are enforced structurally — see `main.py` for the session-state initialisation, ownership validation gate, and audit event hooks already wired into the entry point.

---

## Pipeline stages (target)

| Agent | What it does | Key output | Status |
|---|---|---|---|
| **IngestionAgent** | Detects format, validates, converts FX | Normalised DataFrame | 🔲 Not yet pushed |
| **MatchingAgent** | Bilateral IC matching, gap scoring, root cause via RAG | Matched pairs + exception list | 🔲 Not yet pushed |
| **EliminationAgent** | Generates double-entry journals, handles NCI and PCon% | Elimination journal entries | 🔲 Not yet pushed |
| **ValidationAgent** | HFM rule checks, balance proof, prior period comparison | Validated journal set | 🔲 Not yet pushed |
| **ReviewAgent** | HITL gate — review cards, close readiness check | Review result + close gate | 🔲 Not yet pushed |
| **OutputAgent** | Generates JLF, Excel audit pack, audit trail | Downloadable outputs | 🔲 Not yet pushed |
| **ConsolidationAgent** | Applies eliminations at PCon%, aggregates group statements | Consolidated statements | 🔲 Not yet pushed |

---

## Tech stack (target)

| Layer | Technology |
|---|---|
| Orchestration | LangGraph 0.2+ (state graph, checkpointing, interrupt) |
| LLM | Anthropic Claude |
| Vector store | ChromaDB (dev) / pgvector (production) |
| UI | Streamlit 1.35+ |
| Data | pandas, openpyxl |
| MCP | mcp Python SDK |
| Database | SQLite (dev) / PostgreSQL (production) |

---

## Quickstart

This will not fully run yet — the agent packages it imports are not in this repository. Once the full codebase is pushed, setup will be:

```bash
git clone https://github.com/<your-username>/close-command.git
cd close-command
pip install -r requirements.txt
cp .env.example .env
# Edit .env with ANTHROPIC_API_KEY at minimum
streamlit run main.py
```

`main.py` is published now so the architecture and governance design are visible before the rest of the codebase lands.

---

## Roadmap

- [x] Streamlit entry point with session state, ownership gate, audit event hooks
- [ ] `close_command/agents/` — 8-agent pipeline
- [ ] `close_command/orchestrator/` — LangGraph state graph
- [ ] `close_command/rag/` — embedder, vectorstore, retriever, indexer
- [ ] `close_command/mcp/` — ERP, Notify, Storage, Audit, Auth servers
- [ ] `close_command/governance/` — named ownership, master data validation
- [ ] `close_command/database/` — persistence layer, master data store
- [ ] `close_command/ui/` — tab modules (Master Data, Data Import, Command Center, etc.)
- [ ] `close_command/ml/` — confidence scoring, anomaly detection, deviation thresholds
- [ ] Rollback capability — reversal journal generation
- [ ] Sample data + `requirements.txt` + `.env.example`

---

## Background

Close Command was built from 25 years of FP&A experience — having watched the same finance transformation cycle play out at organisations of every size and industry. The failure pattern is consistent: the vision is correct, the data layer is not ready, and the project stalls before it reaches production.

This project is the technical implementation of a different approach — governance designed in before the first production run, not retrofitted after.

---

## License

MIT — see `LICENSE` for details.

---

## Author

**Narendra Cherlopalli** — FP&A leader with 25 years in group consolidation, financial close, and enterprise finance transformation. Building at the intersection of agentic AI and financial governance.
