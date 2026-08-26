# BERA orientation

This file is **not authoritative**. It orients agents to the repository.
Do not copy detailed OpenSpec requirements here.

## Precedence

1. OpenSpec
2. repository contracts
3. architecture docs
4. AI contract schemas/fixtures
5. `context.md`

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

`openspec/changes/multi-market-search-semantics/` is implemented through
staged PRs A–E. Do not implement later stages early.

## Current implementation stage

Implementation PR A (search intent, snapshot, bounded acquisition, metrics,
and status) is on `main`. `TrackerState` still uses the existing GUI search
path and is not wired to the PR A core. PRs B–E remain unimplemented.
