---
name: bera-ui-productization
description: Productizes the BERA Python + Reflex GUI toward a professional procurement and market-intelligence SaaS look, covering dashboard shell, marketplace comparison views, product cards, tracking views, responsive layout, visual hierarchy, and product imagery. Use when working on the BERA GUI, dashboard, Alibaba/Facebook/Mercado Libre comparison, product cards, tracking views, Reflex layout, Lucide icons, or visual hierarchy. Native Reflex only; never migrate to React, Next.js, or Vite, and never install shadcn as if this were a React project.
---

# BERA UI Productization

## PURPOSE

Use this skill whenever working on the BERA GUI, dashboard, marketplace
comparison views, product cards, tracking views, responsive layout,
visual hierarchy or product imagery.

BERA is a Python + Reflex application.

## PRIMARY VISUAL DIRECTION

Professional procurement / market-intelligence SaaS.

Visual hierarchy inspired by:

1. shadcn dashboard-01
2. Cruip Mosaic dashboard patterns
3. selective 21st.dev patterns
4. selective Origin UI controls
5. Lucide icons through Reflex

Do not combine unrelated design systems.

## TECHNOLOGY RULES

- Native Reflex first.
- Tailwind/CSS utilities through supported Reflex mechanisms.
- Use rx.icon / Lucide.
- Do not migrate to React.
- Do not migrate to Next.js.
- Do not create a Vite frontend.
- Do not install shadcn as if this were a React project.
- Do not add GSAP for normal dashboard interactions.
- Do not use Aceternity visual effects in core workflows.
- Do not add TanStack Table unless advanced data-grid requirements genuinely
  justify it.

## VISUAL SYSTEM

Desktop SaaS shell:

- dark navy/charcoal sidebar
- bright neutral workspace
- white surfaces
- subtle borders
- 8–12px radius
- restrained shadows
- indigo/violet BERA primary accent
- modern sans-serif typography
- strong price hierarchy
- readable 13–14px body text
- no tiny developer-tool text
- no glassmorphism
- no neon
- no large gradients
- no excessive pills

## CORE BERA PATTERN

Whenever cross-marketplace data is available, prioritize:

              Alibaba | Facebook | Mercado Libre

Each marketplace cell should show:

- its own listing image if safely available
- listing title
- primary price
- important marketplace-specific metadata
- relevance
- external listing action

Never fake marketplace images or prices.

If image is missing:

    show a polished "Sin imagen" placeholder.

Never reuse one marketplace's image as another marketplace's listing image.

## MONETARY SAFETY

Never change business logic while doing visual work.

Preserve:

- Decimal money
- currency provenance
- no implicit FX
- "$" alone is not globally USD
- Facebook-Venezuela normalization semantics
- Facebook Free/Gratis/zero/missing-price filtering
- Alibaba pricing/tracking behavior
- Mercado Libre currency behavior

Facebook Free listings shown must remain zero.

## DESIGN PRIORITIES

A user should understand within seconds:

1. what product is being evaluated
2. Alibaba price
3. Facebook Venezuela price
4. Mercado Libre Venezuela price
5. whether listings appear comparable
6. what action can be taken next

## SECONDARY INFORMATION

Do not dump all metadata permanently.

Use:

- accordions
- details sections
- muted metadata
- compact badges

Alibaba tracking history should be collapsed by default.

## RESPONSIVE

Desktop priority:

1280
1440
1920

Comparison matrices may horizontal-scroll rather than compress into unreadable
columns.

## ACCESSIBILITY

- visible focus
- keyboard navigation
- meaningful button labels
- alt text
- sufficient contrast
- don't communicate state only by color

## IMAGE SAFETY

Only public http/https image URLs.

Reject/ignore:

- javascript:
- data:
- embedded credentials
- tokenized/private data when identifiable
- raw provider payload

No extra scraping merely to obtain images.

## TESTING

For GUI work always run:

ruff format .
ruff check .
ruff format --check .
mypy src tests tools
python -m pytest

No external provider calls during visual development.

Do not read .env.

## WORKFLOW

Before editing:

1. inspect existing GUI architecture
2. identify reusable styles/components
3. inspect existing view models
4. determine whether image URLs already exist
5. make the smallest safe design changes

After implementation:

1. run quality gates
2. launch Reflex offline
3. validate 1440px visually
4. produce screenshots
5. perform at most one deliberate refinement pass
6. report changed files and any business-layer changes

Do not merge automatically.
