---
skill_id: qa_integrity
type: global
nodes: [qa]
---
CRITICAL RULE: NEVER inline or mock production code implementations in the test file. You MUST import the target classes and functions from their respective modules according to the contract. Mocking the logic defeats the purpose of the test.
