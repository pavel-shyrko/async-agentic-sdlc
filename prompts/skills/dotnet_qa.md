---
skill_id: dotnet_qa
type: domain
triggers: [dotnet, csharp]
nodes: [qa, reviewer]
---
LANGUAGE TARGET: .NET (C#) — concrete syntax for the .NET tech stack. The language-neutral rules
(exception fidelity, namespace/import fidelity, whole-file assembly, BVA strategy) live in the QA
system prompt; this skill only maps them to C# idioms.

## Testing Framework & Layout
- Use xUnit (`[Fact]` / `[Theory]`). Do NOT mix in NUnit or MSTest.
- Name the test file `<Name>Tests.cs` after the type under test (e.g. `Converter.cs` → `ConverterTests
  .cs`) and place it INSIDE the test project directory (`tests/<Name>.Tests/…`) — NEVER in the production
  source tree (`src/…`) beside the type under test. A `*Tests.cs` sitting next to production code is
  swept into the production project's `**/*.cs` glob and breaks the build (test-only types/usings
  cross-compiled into the production assembly; `CS0579` duplicate-attribute errors from the nested
  `obj/`). Emit ONLY test SOURCE (`*Tests.cs`), and ONLY into that test project directory.
- **Ownership boundary**: the test PROJECT FILE (`<Name>.Tests.csproj`, referencing `Microsoft.NET.Test
  .Sdk` + xUnit + a `ProjectReference` to the project under test, and registered in the root `.sln`) is
  **Developer-owned build glue** — do NOT create, edit, author, or `dotnet sln add` any `.csproj`.
- If the test project is MISSING or absent from the solution, that is a Developer/contract build defect:
  do NOT delete, prune, or regenerate your tests to work around it, and do NOT try to fix it from QA. The
  Reviewer routes a missing test project to the Developer channel; your tests stay as written.

## Namespace & Placement Fidelity (MANDATORY)
- The test FILE lives in the test project (`tests/<Name>.Tests/`), but the test class's `namespace` MUST
  still match the namespace of the type under test exactly as declared in the PRODUCTION CODE SNAPSHOT —
  never a collaborator's. A mismatch breaks symbol resolution and fails the build. Physical location ≠
  namespace: the file sits in the test project; the namespace mirrors the production type (white-box).
- White-box access to `internal` members reaches ACROSS the test-project boundary via the production
  project's `InternalsVisibleTo("<Name>.Tests")` — that is Developer-owned `.csproj` glue. Do NOT colocate
  the test with production code to get internal access, and do NOT author the `.csproj` to add the
  attribute yourself; if an `internal` is unreachable because the attribute is missing, that is a
  Developer/contract gap (the Reviewer routes it to the Developer channel), not a reason to move your test.
- A thin entrypoint (a `Program`/`Main` bootstrap that only wires up and delegates) has no white-box
  logic — emit at most a faithful minimal check in its OWN namespace.

## Test Shape
- One `[Fact]` per single behavior; use `[Theory]` with `[InlineData(...)]` rows for the input matrix
  so each case is isolated and independently reported.

## Assertions & Exceptions (concrete API for the system-prompt CRITICAL RULE)
- Assert exceptions with `Assert.Throws<TException>(() => ...)` — the exception TYPE only. NEVER assert
  on `.Message`, `.ToString()`, or any message-derived property.

## Imports
- `using <Namespace>;` exactly as declared by the topology contract / production snapshot.
