---
skill_id: qa_math_guardrail
type: domain
nodes: [qa]
triggers: [math, analytics, geometry, float, numbers]
---
CRITICAL MATH TESTING RULE: Do not hardcode floating-point expectations for standard geometric calculations; calculate them dynamically (e.g., `expected_area = math.pi * radius ** 2`) and use `math.isclose()`. 
EXCEPTION: When testing extreme boundary values that intentionally exceed Python's float limits (`sys.float_info.max`), you MUST hardcode `float('inf')` as the expected value to prevent `OverflowError` during test execution.