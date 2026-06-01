# Pipeline & Repo Diagrams

Mermaid source for the project diagrams. Edit any label below and it re-renders
(GitHub renders Mermaid natively; locally use the Mermaid VS Code extension or
https://mermaid.live).

## Pipeline architecture

The deliverable: a pipeline that turns screenshots of a generated multi-page
site into a Harbor task, then grades an agent's HTML/CSS replication on a
continuous reward.

```mermaid
flowchart TD
    seed([seed]) --> sample["sample_spec()<br/>6 orthogonal axes + 5–7 page stems"]
    sample --> art["art_direct() — LLM<br/>design brief (JSON)"]
    art --> build["build_site() — LLM<br/>{file: html/css} + spec.json + brief.json"]

    build --> render

    subgraph render["② RENDER — single shared path (parity = #1 requirement)"]
        direction TB
        cfg["full_page @ 1280 / DSF=1 · local HTTP server (no file://)<br/>settle: networkidle → fonts → imgs · animations off<br/>scrollbar hidden · locale/TZ pinned · offline guard"]
    end

    render --> refshots["reference PNGs + reference source<br/>(ground truth)"]

    refshots -->|"agent sees ONLY screenshots"| agent["③ AGENT — Claude Code (Opus 4.7)<br/>writes its own HTML/CSS"]
    agent --> agentrender["render agent output<br/>(same shared config)"]

    refshots --> grade
    agentrender --> grade

    subgraph grade["④ GRADE — continuous reward, monotonic with fidelity"]
        direction TB
        gdetail["perceptual + structural + VLM-judge blend<br/>top-align + pad-to-max (no squish)<br/>reward = mean of per-page fidelity (missing page = 0)"]
    end

    grade --> harbor["⑤ HARBOR TASK<br/>instruction.md · Dockerfile · tests/test.sh → reward.txt<br/>solution/solve.sh validates the grader"]
```

## Repo layout

```mermaid
flowchart TD
    root["work-trial/"]

    root --> spec["task.md — spec (source of truth)<br/>message.md — creds (gitignored)<br/>CLAUDE.md — project instructions"]
    root --> docs["context.md — high-level status map<br/>decisions.md — D1–D4 locked decisions<br/>ideas.md — I1–I6 open ideas<br/>curr_prompt.md — generation prompt"]

    root --> pipeline["pipeline/"]
    pipeline --> prender["render.py — deterministic screenshot module"]
    pipeline --> pgen["generate.py — two-stage generator (spec→brief→build)"]
    pipeline --> pinit["__init__.py — exposes capture_page / capture_site"]
    pipeline --> preadme["README.md — render module docs"]

    root --> fixtures["Sample sites & shots"]
    fixtures --> e1["env_1/ + env_1_shots/ — 5-page food-delivery site"]
    fixtures --> e2["env_2/food-delivery/ — second sample site"]
    fixtures --> outsite["out/site-quartz99/ — generated site + spec/brief + shots"]

    root --> venv["venv/ — Python 3.13 + harbor 0.9.0 (gitignored)"]
```
