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
  test project (`Microsoft.NET.Test.Sdk` + xUnit) — ensure that scaffolding exists for the QA gate.

## Security
- `dotnet list package --vulnerable --include-transitive` runs before review — zero tolerance for
  flagged vulnerable packages.
