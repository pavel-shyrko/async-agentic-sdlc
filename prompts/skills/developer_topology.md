---
skill_id: developer_topology
type: topology
nodes: [developer]
---
CRITICAL PATHING RULE: All contract paths are strictly relative to the repository root ({code_dir}). Create every file preserving the EXACT `file_path` listed in the `TOPOLOGY CONTRACT` block below. Contract paths ALREADY include any leading `src/` segment, so do NOT prepend another one, and do NOT nest directories (e.g. writing to `src/src/`). Obey exact paths.
