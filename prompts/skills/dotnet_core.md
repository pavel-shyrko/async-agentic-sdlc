---
skill_id: dotnet_core
type: domain
triggers: [dotnet, csharp]
nodes: [techlead, developer, reviewer]
---
LANGUAGE TARGET: .NET (C#) — production-code rules for the .NET tech stack.

## Runtime & Sandbox
- Target .NET 10, executed in the isolated Docker sandbox (`mcr.microsoft.com/dotnet/sdk:10.0-alpine`).
- The solution MUST build cleanly under `dotnet build`; treat warnings as defects.

## Solution Layout (MANDATORY — root holds ONLY the .sln; projects live in subdirectories)
The gates run bare `dotnet restore` / `dotnet build` / `dotnet test` from the repository ROOT with no
project argument, so the repo MUST carry a root `.sln`. The `.sln` is the workspace the bare commands
resolve; the actual projects MUST sit in their own subdirectories. Use the canonical layout:

```
<repo root>/
  <Solution>.sln                                  # the ONLY project/solution file at the root
  .gitignore  LICENSE  README.md                  # repo metadata only
  src/<Project>/<Project>.csproj                  # production project + its sources (Models/…, etc.)
  tests/<Project>.Tests/<Project>.Tests.csproj    # test project + its *Tests.cs sources
```

- **NEVER place a `.csproj` at the repository root.** A root-level production project is the single
  biggest source of avoidable build-fail reroutes on this stack — its default recursive `**/*.cs` glob
  (and `obj/` output) collides with every sibling project. The three failure modes it causes, ALL of
  which the subdirectory layout eliminates with ZERO `<Compile Remove>` / `DefaultItemExcludes` band-aids:
  1. **`MSB1011`** ("more than one project or solution file") — a root `.csproj` next to the test
     `.csproj` (or the `.sln`) makes the bare root command ambiguous.
  2. **Cross-globbed test sources** — a root project's `**/*.cs` glob compiles `*Tests.cs` that live
     under it, pulling test-only types/usings into the production assembly.
  3. **`CS0579` duplicate assembly attributes** — a root project globs a nested project's generated
     `obj/**/*.AssemblyInfo.cs`, so the same `[Assembly*]` attribute is emitted twice → build break.
- The repo MUST carry a root solution file referencing EVERY project, or the build fails with `MSB1003`
  ("does not contain a project or solution file"). Either the classic `.sln` OR the newer `.slnx` (the
  XML format that .NET 10's `dotnet new sln` now emits by DEFAULT) is fine — `dotnet build`/`test`/`format`
  all accept both. A project under `src/`/`tests/` is fully visible to a root-level `dotnet build` **as
  long as the solution references it** — nesting is correct, not a problem.
- **TechLead**: lay out `files_to_modify` and the topology with `src/<Project>/…` and
  `tests/<Project>.Tests/…` paths (never a root `.csproj`), and list the root `.sln`. State the layout in
  `architectural_constraints` ("root holds only the .sln; production csproj under src/<Project>/; test
  csproj under tests/<Project>.Tests/"). For white-box tests of `internal` members, require the
  production `.csproj` to declare `InternalsVisibleTo("<Project>.Tests")` — that, NOT physical colocation,
  is how the separate test project reaches internals.
- **Developer**: realize this on the FIRST write — author the `.sln` (one `Project(...)` entry per
  `.csproj`, with the correct relative subdirectory path) or emit `dotnet new sln` + `dotnet sln add
  src/<Project>/<Project>.csproj` (and the test project). Put production sources only under
  `src/<Project>/` and never author a `*Tests.cs` (QA-owned). Any NEW `*.csproj` (INCLUDING the test
  project) MUST be registered in the root `.sln` in the SAME ticket, or a root-level build/test silently
  skips it.

## Project Archetype & Entry Point (MANDATORY — declare it, don't oscillate over it)
- A .NET project has ONE archetype, and it is fixed by the ticket, not guessed per cycle:
  - **CLI utility / application** → `<OutputType>Exe</OutputType>` PLUS exactly one entry point — a
    `Program.cs` with top-level statements (or a single `static Main`) that actually invokes the parser.
  - **Library** → `<OutputType>Library</OutputType>` (or omit it) and NO entry point file.
- **TechLead**: decide the archetype from the ticket/blueprint and state it in `architectural_constraints`
  (e.g. "OutputType=Exe; entry point in Program.cs"). For an **Exe**, you MUST list the entry-point file
  (`Program.cs`) in `files_to_modify` and the topology — an Exe is not buildable without one, so it is
  IN scope, never an out-of-whitelist extra. Do not declare `OutputType=Exe` while omitting the entry point.
- **Developer**: an `Exe` `.csproj` REQUIRES a real entry point — write it on the FIRST pass. A
  `Program.cs` that holds only the architectural-justification comment (no `Main`/top-level statements)
  fails to build with `CS5001` ("does not contain a static 'Main' method") and wastes a reroute. Include
  the leading justification comment AND working entry-point code in the same write.
- **Reviewer / Arbiter**: a minimal entry point that a contracted **Exe** `.csproj` needs to compile is
  legitimate, in-scope build glue (the Developer is authorized to add it) — APPROVE it; never flag it as
  a scope violation or direct its deletion. If the entry point is genuinely missing from `files_to_modify`
  and that blocks the build, that is a CONTRACT gap to amend (add it to the whitelist), not a Developer bug.

## Scaffolding / init ticket completeness (MANDATORY — the buildable+testable skeleton ships in ONE ticket)
The ticket that CREATES the project skeleton (the `.csproj`/`.sln`) MUST leave the repo BUILDABLE and
TESTABLE the moment it merges — never a config-only shell that defers the entry point or the test project
to a later ticket. A bare `.sln` + production `.csproj` with neither is the recurring first-ticket failure:
it `CS5001`-reroutes (Exe with no entry point) AND leaves QA's `*Tests.cs` orphaned (no test project in the
solution → `dotnet test` discovers ZERO tests and exits green with no coverage). In the SAME contract:
- **Production entry point** — for an `Exe`, `src/<Project>/Program.cs` (real `Main`/top-level statement)
  in `files_to_modify` (per Archetype above).
- **Test project skeleton** — `tests/<Project>.Tests/<Project>.Tests.csproj` (Microsoft.NET.Test.Sdk +
  xUnit + a `ProjectReference` to the production project) in `files_to_modify`, with BOTH projects
  registered in the root `.sln`. This is the compile target QA writes its `*Tests.cs` into; the test SOURCE
  itself stays QA-owned (never list `*Tests.cs`).
- **TechLead**: NEVER write "do not create C# source code files" into a scaffold contract for an `Exe`
  app — that instruction is exactly what strands the entry point and the test project out of scope. The
  entry point and the test `.csproj` are build glue: they are IN scope for the skeleton ticket even when
  the ticket text frames itself as "configuration only". Expand the contract to include them.

## Types & Guards
- Enable nullable reference types (`<Nullable>enable</Nullable>`) and honor the annotations. Guard
  arguments explicitly: throw `ArgumentNullException`/`ArgumentException` (or use `ArgumentNullException
  .ThrowIfNull`) at the boundary. No implicit narrowing casts — validate the exact expected type.
- Store constructor parameters as their declared types; no implicit coercion.

## Exception Handling
- Throw specific exception types for invalid input (e.g. `ArgumentException`, `FormatException`).
  NEVER use an empty `catch {}` and never swallow exceptions silently.
- Use `try`/`catch`/`finally`; dispose `IDisposable` resources with `using`. Distinguish failures by
  exception TYPE, not by `.Message` text.

## Namespace & Assembly Glue
- Organize code by `namespace` (there is NO package-init file). Keep one primary type per file named
  after the type. Wire collaborators via constructor Dependency Injection — do not new-up
  dependencies inside domain logic.
- Manage dependencies and the build in the `.csproj` (`PackageReference`). `dotnet test` requires a
  test project (`Microsoft.NET.Test.Sdk` + xUnit + a `ProjectReference` to the project under test),
  living at `tests/<Project>.Tests/<Project>.Tests.csproj` — its own subdirectory, never alongside the
  production project. The **Developer owns the test PROJECT FILE** (`<Project>.Tests.csproj`) as build
  glue — create it (with the leading justification comment), `ProjectReference` it to
  `../../src/<Project>/<Project>.csproj`, and register it in the root `.sln` — but NEVER the test SOURCE
  (`*Tests.cs`), which is QA-owned. Get the test `.csproj` in on the first pass so the QA gate has a
  project to compile into.

## Package References (MANDATORY — never pin a framework-provided package: NU1510)
A package that ships INSIDE the target framework (`System.Text.Json`, `System.Net.Http`, `System.Memory`,
`System.Threading.Tasks.*`, `System.Collections.Immutable`, …) is supplied implicitly by the .NET 10
runtime. Do NOT add an explicit `<PackageReference>` for it: on .NET ≥9 `dotnet restore` raises **`NU1510`**
("PackageReference … will not be pruned … likely unnecessary"), and with `<TreatWarningsAsErrors>true</…>`
(this stack treats warnings as defects) that warning is promoted to a **hard restore failure** that wastes a
compile-gate reroute. Rely on the implicit framework reference and just `using` the types. An explicit
reference is legitimate ONLY when you genuinely need a version NEWER than the framework supplies — and then
you must opt in deliberately with `<NoWarn>NU1510</NoWarn>` on that reference. `PackageReference` is for
OUT-OF-framework packages (e.g. `System.CommandLine`, `Microsoft.NET.Test.Sdk`, `xunit`).
- **TechLead**: do NOT list framework-provided packages in `core_libraries` — listing one makes the
  Developer add a redundant `<PackageReference>` it is told is MANDATORY, and that NU1510-fails the build.
  Constrain `core_libraries` to genuine out-of-framework dependencies.
- **Developer**: even if the contract names a framework-provided package, do NOT emit a `<PackageReference>`
  for it — `using` the types directly. The implicit framework reference covers it; an explicit one breaks
  restore.

## Security
- `dotnet list package --vulnerable --include-transitive` runs before review — zero tolerance for
  flagged vulnerable packages.

## Test infrastructure packages — use pre-warmed versions (MANDATORY)
The Docker sandbox resolves packages OFFLINE from a baked read-only fallback (`/opt/nuget-fallback`).
NuGet uses EXACT version identity — a `17.11.1` requirement is NOT satisfied by a `17.12.0` fallback entry.
Pinning an older or un-prewarm'd version forces a live internet restore that the sandboxed container cannot
reach, causing a NU1301 halt that costs a full retry cycle.

**TechLead**: Specify EXACTLY these versions in `core_libraries` for the test project — never a lower patch
or minor:
- `Microsoft.NET.Test.Sdk` → `17.12.0`
- `xunit` → `2.9.3`
- `xunit.runner.visualstudio` → `2.8.2`
- `coverlet.collector` → `6.0.2`
- `Moq` → `4.20.72` (if mocking is needed)
- `FluentAssertions` → `6.12.2` (if fluent assertion style is used)
- `Microsoft.AspNetCore.Mvc.Testing` → `10.0.0` (for REST API integration testing)

**Developer**: Never downgrade these versions. Even one minor-version step (e.g. `17.12.0` → `17.11.1`)
misses the baked fallback and will cause a NU1301 network halt in the offline sandbox.

## JSON Serialization with System.Text.Json (MANDATORY — no manual escaping)

### Developer
- When serializing a `JsonElement` value (array, object, or primitive) to a JSON string, ALWAYS use
  `JsonSerializer.Serialize(element)` — never build the JSON string manually via string concatenation or
  bracket + escaped-quote literals such as `$"\\\"" + value + "\\\""`.
- Manual construction always introduces escaping bugs (double-backslash, mismatched brackets, wrong
  whitespace). `JsonSerializer.Serialize` is the ONLY correct path.
- For a `JsonElement` of `ValueKind == Array`, iterate elements and serialize each with
  `JsonSerializer.Serialize(item)`, then join with `,` inside `[…]`. Do NOT use `GetRawText()` on the
  whole array without controlling whitespace — `GetRawText()` preserves the original input's whitespace
  (may include spaces after commas), which diverges from the compact format required by the contract.

### TechLead
- Array format examples in `architectural_constraints` and `acceptance_examples` MUST use **compact
  JSON** (no spaces after `,` or `:`). This matches what `JsonSerializer.Serialize` actually produces.
  Never mix spaced and compact forms across these two fields — a mismatch propagates to QA tests
  oscillating between `[1, 2, 3]` and `[1,2,3]` and triggers Arbiter misroutes.
- Example: write `["admin","user"]` — NOT `["admin", "user"]`. Any example that uses spaces after `,`
  or `:` will fail the gate when the Developer correctly uses `JsonSerializer.Serialize`.

## Recursive traversal with accumulated path/key prefix (TechLead — acceptance_examples obligation)
For any algorithm that recursively processes a nested structure while accumulating a path or key prefix
(e.g. JSON flattening, nested-property enumeration, tree serialization), the TechLead MUST author
`acceptance_examples` entries that cover these three non-obvious cases. They are invisible in happy-path
inputs and therefore not generated by QA without an explicit oracle:

1. **Root-level empty collection** — the root element is an empty object/array and the prefix is the
   zero-value (empty string `""`). The expected output is a single entry keyed by `""`, NOT an empty
   result. Any `string.IsNullOrEmpty(prefix)` guard on the write step silences this case; pinning it here
   makes the guard mechanically observable to the test suite.
2. **Nested empty collection** — an empty object/array at a non-root position (e.g. `{"a": {}}`); the
   expected output uses the parent path as the key (e.g. `{"a": ""}`).
3. **Recursion-depth boundary** — an input at exactly the declared maximum nesting depth (no exception) AND
   one at depth + 1 (raises the declared exception type — never a message).

Place these cases in `acceptance_examples`, NOT in `instruction` (`instruction` is for imperative
directives; golden-case pin belongs in the behavioral oracle the QA suite asserts verbatim).
