```md
# PROJECT: GHOSTWIRE — Corporate Intelligence Grid
*"Information is currency. Insight is power. Alignment is survival."*

This system turns raw company data into operational advantage — client-facing, employee-facing, and internal command-level.

---

## 1. 🎯 OBJECTIVE
Build an AI-powered platform that:
1. Acts as a **public-facing AI agent** (clients + candidates)
2. Processes **internal human feedback into actionable intelligence**
3. Automatically **assembles optimal teams for new projects**

All powered by a **shared intelligence layer**.

---

## 2. 🧩 SYSTEM ARCHITECTURE

### Core Principle:
> **One brain, multiple interfaces**

---

### 2.1 KNOWLEDGE CORE (Central AI Layer)
This is the backbone. All features depend on it.

#### Data Domains:
* Company data (website, case studies)
* Job openings
* Employee profiles (CVs, skills, history)
* Feedback data (performance reviews)
* Project requirements

---

### Storage:
* Structured DB: PostgreSQL
* Vector DB: Weaviate / Pinecone

---

### Responsibilities:
* Semantic search
* Context retrieval (RAG)
* Feature extraction
* Scoring & summarization

---

## 3. 🤖 MODULE 1 — PUBLIC AI CHATBOT

### Interface:
Embedded on website (godeltech.com)

---

### Capabilities:

#### For Clients:
* Company overview
* Case studies
* Tech expertise
* Delivery models

#### For Candidates:
* Open positions
* Requirements
* Application guidance

---

### Architecture:

#### Input:
Natural language query

#### Pipeline:
1. Intent detection (client vs candidate)
2. Retrieve context (RAG)
3. Generate response via Claude

---

### Claude Prompt Spec:
```text
SYSTEM:
You are a corporate AI agent representing a high-end software engineering company.
Tone: confident, precise, human—not robotic.

RULES:
- Never hallucinate capabilities
- Use only provided context
- If unsure → ask clarification

USER:
<query>

CONTEXT:
<retrieved documents>

OUTPUT:
Clear, structured answer

```

---

### Constraints:

* Response time < 2s
* Grounded answers only (no hallucinations)

---

## 4. 🧠 MODULE 2 — FEEDBACK INTELLIGENCE ENGINE

> *Raw feedback is noise. Insight is signal.*

---

### Input:

* Peer reviews
* Manager reviews
* Self-assessments

---

### Output:

#### For Team Managers (TM):

* Summary of strengths
* Key concerns
* Behavioral patterns
* Risk signals (burnout, conflict)

---

### Processing Pipeline:

1. Text ingestion
2. Sentiment analysis
3. Theme extraction
4. Pattern detection
5. Summary generation (Claude)

---

### Claude Prompt Spec:

```text
SYSTEM:
You are an organizational intelligence AI.

TASK:
Analyze performance feedback and extract:
- strengths
- weaknesses
- behavioral signals
- risks

RULES:
- Be objective
- Avoid vague statements
- Highlight patterns across multiple inputs

INPUT:
<feedback set>

OUTPUT:
Structured summary

```

---

### Output Schema:

```json
{
  "strengths": [],
  "weaknesses": [],
  "risks": [],
  "team_dynamics_signals": [],
  "confidence_score": 0.0
}

```

---

## 5. ⚙️ MODULE 3 — AI TEAM ASSEMBLER

> *Wrong team, wrong outcome. Always.*

---

### Input:

* New project description
* Requirements
* Constraints (timeline, budget, timezone)

---

### Data Used:

* Employee profiles
* Past project history
* Feedback intelligence
* Skill vectors

---

### Pipeline:

#### Step 1 — Project Analysis

Claude extracts:

* Required skills
* Seniority levels
* Team composition
* Risk factors

---

#### Step 2 — Candidate Scoring

Each employee scored on:

| Dimension | Method |
| --- | --- |
| Skill Match | Embeddings |
| Experience Fit | Rule-based |
| Feedback Score | Derived metric |
| Availability | Scheduling data |
| Team Compatibility | Graph-based |

---

#### Step 3 — Team Optimization

Goal: Maximize:

* Skill coverage
* Collaboration probability
* Delivery success likelihood

---

### Output:

```json
{
  "team": [
    {
      "employee_id": "uuid",
      "role": "backend",
      "match_score": 0.92
    }
  ],
  "gaps": [],
  "risks": [],
  "alternatives": []
}

```

---

### Claude Prompt Spec:

```text
SYSTEM:
You are a high-level technical staffing AI.

TASK:
Select the best possible team for a project.

CRITERIA:
- Skills
- Experience
- Feedback signals
- Team synergy

OUTPUT:
- team selection
- reasoning
- risks

```

---

## 6. 🔄 SHARED COMPONENTS

### 6.1 Employee Intelligence Profile

Unified model combining:

* CV data
* Skills
* Feedback summaries
* Project history

---

### 6.2 Embedding Layer

Used across:

* Chatbot (RAG)
* Matching
* Feedback clustering

---

### 6.3 Explainability Engine

Every decision must output:

* Why this answer
* Why this person/team

---

## 7. 🖥️ FRONTEND INTERFACES

### Public:

* Chat widget

### Internal:

* Feedback dashboard
* Team assembly UI

---

## 8. ⚙️ TECH STACK

* Backend: Python (FastAPI)
* Frontend: React
* AI: Claude API
* Vector DB: Weaviate / Pinecone
* Infra: GCP (aligned with requirement)

---

## 9. 🔐 NON-FUNCTIONAL REQUIREMENTS

* GDPR compliant (critical)
* Role-based access control
* Audit logs for AI decisions
* No exposure of sensitive employee data externally

---

## 10. 🧪 MVP SCOPE

Deliver first:

1. Chatbot (RAG-based)
2. Feedback summarization
3. Basic team matching (no optimization yet)

---

## 11. ⚠️ FAILURE CONDITIONS

System fails if:

* Chatbot hallucinates
* Feedback summaries are generic
* Team selection ignores behavioral data
* Modules operate independently (no shared intelligence)

---

## 12. 🧬 CYBERPUNK DIRECTIVE

> *This is not a chatbot. Not an HR tool. Not a recommender.*
> *This is a decision system operating inside a corporate battlefield.*

* If it only retrieves data → it’s dead weight
* If it doesn’t influence decisions → it’s irrelevant
* If it can’t explain itself → it can’t be trusted

**Directive: Build intelligence, not features.**

---

END OF FILE

```

```