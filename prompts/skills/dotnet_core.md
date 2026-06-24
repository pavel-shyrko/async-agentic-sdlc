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

## Security
- `dotnet list package --vulnerable --include-transitive` runs before review — zero tolerance for
  flagged vulnerable packages.
