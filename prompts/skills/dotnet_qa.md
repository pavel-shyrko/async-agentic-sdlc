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
- Name the test file `<Name>Tests.cs` colocated with the type under test (e.g. `Converter.cs` →
  `ConverterTests.cs`). Assume the contract provides the test project (a `.csproj` referencing
  `Microsoft.NET.Test.Sdk` + the xUnit packages and the project under test); emit the test class into it.

## Namespace & Placement Fidelity (MANDATORY)
- The test class's `namespace` MUST match the namespace of the type under test exactly as declared in
  its sibling in the PRODUCTION CODE SNAPSHOT — never a collaborator's. A mismatch breaks `internal`
  visibility and symbol resolution and fails the whole build.
- Use an external test namespace / `InternalsVisibleTo` ONLY when the contract exposes a public API;
  otherwise stay in the production type's own namespace (white-box).
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
