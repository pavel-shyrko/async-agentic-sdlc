---
skill_id: techlead_topology
type: topology
nodes: [techlead]
---
CRITICAL TOPOLOGY RULE: Place production code under a conventional source directory consistent with the Blueprint's File Topology and the target stack's idiom (e.g. a `src/` tree, or the stack's standard layout) — never dump production files at the repository root. Use the exact repo-root-relative paths the Blueprint specifies, and keep every ticket's paths consistent with that layout. Analyze the `EXISTING REPOSITORY TOPOLOGY`: you are STRICTLY FORBIDDEN from creating redundant root-level directories — if an existing package matches the business domain, route new files inside it rather than spawning a parallel tree.
