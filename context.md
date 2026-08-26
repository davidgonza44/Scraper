# BERA orientation

This file is **not authoritative**. It orients agents to the repository.
Do not copy detailed OpenSpec requirements here.

## Precedence

1. OpenSpec
2. repository implementation/contracts
3. architecture docs
4. AI schemas/golden fixtures
5. `context.md` / implementation convenience

## What BERA is

BERA Price Tracker is a procurement/market-intelligence tool for comparing
Alibaba, Facebook Marketplace, and Mercado Libre listings.

## Stack

Python 3.12, Ports & Adapters, Reflex-native GUI. Do not migrate the
frontend to React, Next.js, or Vite.

## Architecture map

- Application core: `src/bera_price_tracker/application/`
- Provider adapters: `src/bera_price_tracker/infrastructure/providers/`
- GUI: `src/bera_price_tracker/gui/`
- Search-session core: `src/bera_price_tracker/application/search_session.py`
- Architecture diagrams: `docs/architecture/`
- AI contract pack: `docs/ai-contracts/`, `schemas/ai-contracts/`,
  `tests/fixtures/ai-contracts/`

## Active staged OpenSpec change

The change `openspec/changes/multi-market-search-semantics/` is planned as
staged implementation PRs A–E. Only Implementation PR A is currently
implemented on main. PRs B–E remain unimplemented. Do not implement later
stages early.

## Current implementation stage

Implementation PR A (search intent, snapshot, bounded acquisition, metrics,
and status) is on `main`. `TrackerState` still uses the existing GUI search
path and is not wired to the PR A core. PRs B–E remain unimplemented.
