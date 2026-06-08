---
skill_id: engineering_guide
type: global
nodes: [architect, developer, qa, reviewer]
---
# Global Engineering Guide & Code Style

## Tech Stack & Code Style
* **Runtime**: Python 3.11+ / Isolated Docker Sandbox (`python:3.11-slim`).
* **Testing**: Python `unittest` framework strictly. Using `pytest` is FORBIDDEN.
* **Type Guards**: Enforce explicit type guards against Python implicit subclassing. Example for integers: `if isinstance(n, int) and not isinstance(n, bool):`.
* **Security**: Zero tolerance for vulnerabilities. Mandatory Bandit SAST execution before review.
* **State Preservation**: Store parameter values passed into constructors exactly as their original allowed types. No implicit coercion (e.g., forcing `int` to `float`).
