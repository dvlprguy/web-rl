# Replicate this website's design in HTML & CSS

You are given screenshots of every page of a multi-page website. Reproduce each
page's **visual design** as faithfully as possible using **static HTML and CSS**.

## What you have
The target screenshots are in `./target/`, one PNG per page:

- `target/about.png`
- `target/detail.png`
- `target/faq.png`
- `target/home.png`
- `target/pricing.png`
- `target/services.png`
- `target/team.png`

Each is a **full-page screenshot** (the entire scroll height) captured at a
**1280px-wide** desktop viewport. You may open and inspect these image files freely.

## What to produce
Create your site in a `./site/` directory. For every `target/<name>.png`, create
`site/<name>.html`, all linking a shared `site/style.css`, with a consistent
header/nav and footer across pages. Produce exactly these files:

site/about.html, site/detail.html, site/faq.html, site/home.html, site/pricing.html, site/services.html, site/team.html, site/style.css

## How you're judged
**Only on how closely each page you build — once rendered — matches its target
screenshot:** layout, proportions, spacing, colors, typography, and which
components are present and where. Match it as precisely as you can, page by page.

## Rules
- **Static HTML + CSS only.** Functionality is out of scope and **not graded** —
  links needn't work, forms needn't submit. Don't spend effort on behavior.
- **Must render fully offline.** No external URLs, CDNs, web fonts, or downloaded
  assets — pages are rendered in a sandbox with no network. Use system / web-safe
  fonts, and build any graphics with CSS or inline SVG.
- **Design for a 1280px-wide desktop viewport.** Pages are rendered and compared at
  this width; responsiveness is not required.
- **Be consistent across pages** — shared nav and footer, one cohesive design system.

Put everything you build under `./site/`.
