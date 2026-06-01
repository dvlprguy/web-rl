# Pipeline Diagrams (ASCII)

Plain-text diagrams — edit any label directly, no rendering needed. Renders in
any terminal, editor, or markdown viewer. (Mermaid versions live in `diagram.md`.)

## Abstracted — the four-stage loop

```
   ┌───────────┐     ┌───────────┐     ┌───────────┐     ┌───────────┐
   │ ①GENERATE │────▶│ ②RENDER   │────▶│ ③AGENT    │────▶│ ④GRADE    │
   │ a site    │     │ to ground │     │ replicates│     │ continuous│
   │ (HTML/CSS)│     │ truth     │     │ from shots│     │ reward    │
   └───────────┘     └─────┬─────┘     └─────┬─────┘     └───────────┘
                           │                 │
                           └────── same ──────┘
                            render path (parity)
                                                          → ⑤ Harbor task
```

## Detailed — full pipeline

```
┌──────────────────────────────────────────────────────────────────────────┐
│                    RL ENV PIPELINE: screenshots → HTML/CSS                 │
│                       (Harbor tasks, graded vs Opus 4.7)                    │
└──────────────────────────────────────────────────────────────────────────┘

  ① GENERATE                     ② RENDER (shared)            ③ AGENT
  ─────────────                  ──────────────────           ──────────────
  generate.py                    render.py                    Claude Code
                                                              (Opus 4.7)
  seed                           full_page @ 1280 / DSF=1
   │                             local HTTP server (no file://)      │
   ▼                             settle: networkidle→fonts→imgs      │
  sample_spec()                  anims off · scrollbar hid           │
   6 orthogonal axes             locale/TZ pinned · offline guard    │
   + 5–7 page stems              ┌──────────────┐                    │
   │                             │ ONE render    │ sees ONLY  ◄───────┘
   ▼                             │ path for BOTH │ screenshots
  art_direct()  ──LLM──►         │ ref & agent   │     │
   design brief (JSON)           │ (parity = #1) │     ▼ writes own HTML/CSS
   │                             └──────┬───────┘   ┌──────────────┐
   ▼                                    │           │ render AGENT │
  build_site() ──LLM──►                 ▼           │ same config  │
   {file: html/css}              reference PNGs     └──────┬───────┘
   + spec.json + brief.json       + ref source             │
                                  (ground truth)            │
                                         └──────────┬───────┘
                                                    ▼
                                  ④ GRADE
                                  ────────────────────────────────────────
                                  continuous reward, monotonic w/ fidelity
                                  perceptual + structural + VLM judge blend
                                  D3: top-align + pad-to-max (no squish)
                                  mean of per-page fidelity (missing = 0)
                                                    │
                                                    ▼
                                  ⑤ HARBOR TASK WIRING
                                  instruction.md · Dockerfile · tests/test.sh
                                  → reward.txt    · solution/solve.sh validates
```
