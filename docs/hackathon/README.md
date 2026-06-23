# Cyberthone 2026 — Hackathon Dossier

**3-day build sprint · June 26–28, 2026 · Warsaw · Free entry**

This directory collects everything about the **Cyberthone 2026** hackathon: the mission
briefings, the judge scorecard, and our working notes. It is **documentation only** — it does
not feed the runtime engine. (Engine/agent rules live in `.claude/rules/` and `prompts/`.)

## Event logistics

| | |
| --- | --- |
| **Event** | Cyberthone 2026 — cyberpunk-flavored build sprint |
| **Dates** | June 26–28, 2026 (3 days) |
| **Venue** | Godel office, Warsaw — "Neon Forge Hall", Warsaw Financial Center, Emilii Plater 53 / 12th floor |
| **Cost** | Free entry; solo welcome — squads form on arrival |
| **Organizer** | Godel Technologies (AI & RnD Function, .NET PR, Marketing Team) |
| **Stack** | Open |
| **Bonus objective** | Come in costume → extra gift |

## ⏰ Key deadlines

- **Mission 00 (SDLC spec) — due before June 24, 08:00.** Mandatory prerequisite; no spec submitted → instant disqualification (and no confirmed invitation).
- **Build submission — June 27, 14:00 cutoff.**
- **Finalists announced — June 27, 17:00.** Jury reviews every submission; **top 10** teams advance.
- **The Final — June 28.** Only the 10 finalists pitch live to the jury and compete for the top 3 places.

## Schedule

| Day | Date | Theme | Notable slots |
| --- | --- | --- | --- |
| 01 | June 26 | Mission Drop | 15:00 Access Granted (badge + welcome kit) · 16:00 Mission Broadcast (full walkthrough, Mission reveal, scoring matrix, resource briefing → teams start building). "Execute it exactly as stated — no improvisation." |
| 02 | June 27 | Build & Cutoff | 14:00 submission cutoff · 17:00 top-10 finalists announced |
| 03 | June 28 | The Final | Finalists pitch live to the jury · live judging 18:30 · top 3 awarded |

## Judges

| Judge | Role |
| --- | --- |
| Victor Nekrasov | Technical Chief Technology Officer |
| Andrew Afanasenko | Chief Operations Officer |
| Elena Polubochko | Chief Delivery Officer |
| Anastassia Davidzenka | VP of Professional Services |
| Andrei Salanoi | VP AI Engineering |
| Nadzeya Mernaya | Head of AI & Research & Development |
| Alexander Belenkov | Head of AI Practice Function |

## Layout

| Path | What it holds |
| --- | --- |
| [`agentic-sdlc-specification-v1.md`](agentic-sdlc-specification-v1.md) | **Deliverable #1** — the Agentic SDLC Specification (Mission 00 mandatory prerequisite). Code-grounded: maps the Token Burners Factory engine to all five spec sections (1.1–1.5). |
| [`missions/`](missions/) | The 11 mission transmissions (`00`–`10`), saved verbatim as received. |
| [`acceptance-criteria.md`](acceptance-criteria.md) | The Judge Cheat Sheet — 135-pt scorecard across 7 dimensions, grade bands, and instant-DQ rules. This is what the demo is scored against. |

## Mission index

| # | File | Title |
| --- | --- | --- |
| 00 | [missions/00-mission-briefing.md](missions/00-mission-briefing.md) | Mission Briefing — Design & Implement an Agent-Driven SDLC & Software Factory |
| 01 | _pending_ | _to be received_ |
| 02 | _pending_ | _to be received_ |
| 03 | _pending_ | _to be received_ |
| 04 | _pending_ | _to be received_ |
| 05 | _pending_ | _to be received_ |
| 06 | _pending_ | _to be received_ |
| 07 | _pending_ | _to be received_ |
| 08 | _pending_ | _to be received_ |
| 09 | _pending_ | _to be received_ |
| 10 | _pending_ | _to be received_ |

## How our entry maps to the brief

**Token Burners Factory** *is* the deliverable: an agentic SDLC engine (3 planes — nexus /
development / deployment — chaining PO → SA → TPM → TechLead → Developer → QA → Reviewer →
DevOps via machine-readable contracts) plus the live FinOps reporting that dimension 7 grades.
As missions arrive, record here how each one is satisfied by the existing engine vs. what still
needs building.

### Final-deliverable status (Mission 00)
1. **Agentic SDLC Spec** — ✅ [agentic-sdlc-specification-v1.md](agentic-sdlc-specification-v1.md).
2. **Agent architecture diagram** — partial: a physical-plane Mermaid diagram is embedded in the spec §0;
   the full C4 model lives in [../ARCHITECTURE.md](../ARCHITECTURE.md).
3. **Working prototype** — ✅ the engine itself (`main.py` → `src/`).
4. **Demo project built by agents** — to run live (`--idea … --auto-execute`).
5. **Evaluation report (what worked / collapsed)** — pending.
