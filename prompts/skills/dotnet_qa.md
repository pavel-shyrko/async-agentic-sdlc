---
skill_id: dotnet_qa
type: domain
triggers: [dotnet, csharp]
nodes: [qa, reviewer]
enabled: false
---
LANGUAGE TARGET: .NET (C#) — concrete syntax for the .NET tech stack. The language-neutral rules
(exception fidelity, namespace/import fidelity, whole-file assembly, BVA strategy) live in the QA
system prompt; this skill only maps them to C# idioms.

## MANDATORY PRE-WRITE SCAN — Execute BEFORE authoring any test

Before writing a single test, scan the production code snapshot for these three patterns. Each one
has a mandatory response. Missing any of them causes deterministic gate failures.

**1. `OnStarting` callbacks**
- DETECT: search snapshot for `context.Response.OnStarting(` AND any test that uses `DefaultHttpContext`
- APPLY: replace `DefaultHttpContext`'s feature with `FakeHttpResponseFeature` (see
  "ASP.NET Core Middleware — OnStarting Callbacks" section below for the full pattern)
- Skipping this produces `Expected: <status>. Actual: 200` failures — the callbacks never fire

**2. BCL exception helpers**
- DETECT: search snapshot for `ArgumentException.ThrowIfNullOrEmpty`, `ArgumentNullException.ThrowIfNull`,
  or `JsonDocument.Parse`
- APPLY:
  - `ThrowIfNullOrEmpty(null, …)` → use `Assert.ThrowsAny<ArgumentException>()` (raises `ArgumentNullException`)
  - `JsonDocument.Parse(badJson)` → use `Assert.ThrowsAny<JsonException>()` (raises `JsonReaderException`)
  - Full table in "Assertions & Exceptions" below
- Skipping this produces `Expected: typeof(ArgumentException). Actual: typeof(ArgumentNullException)` failures

**3. Empty-string header parameters via WebApplicationFactory**
- DETECT: any `[InlineData]` row where a header parameter is `""`
- APPLY: remove those rows entirely — the in-memory transport strips empty headers before middleware runs
- Full rule in "WebApplicationFactory Integration Tests" below

## Testing Framework & Layout
- Use xUnit (`[Fact]` / `[Theory]`). Do NOT mix in NUnit or MSTest.
- Name the test file `<Name>Tests.cs` after the type under test (e.g. `Converter.cs` → `ConverterTests
  .cs`) and place it INSIDE the test project directory (`tests/<Name>.Tests/…`) — NEVER in the production
  source tree (`src/…`) beside the type under test. A `*Tests.cs` sitting next to production code is
  swept into the production project's `**/*.cs` glob and breaks the build (test-only types/usings
  cross-compiled into the production assembly; `CS0579` duplicate-attribute errors from the nested
  `obj/`). Emit ONLY test SOURCE (`*Tests.cs`), and ONLY into that test project directory.
- **Assembly-level attributes** (`[assembly: ...]`, e.g. `[assembly: CollectionBehavior(...)]`) MUST appear in exactly ONE `.cs` file per test project — conventionally the alphabetically-first test file. NEVER repeat any `[assembly: ...]` declaration in a second test file in the same project: C# `CS0579` ("Duplicate attribute") will fail the build. When adding a new test file alongside an existing one, check every existing `*Tests.cs` for `[assembly: ...]` lines and omit them from the new file.
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
- **BCL exception hierarchy — use `Assert.ThrowsAny<T>()` not `Assert.Throws<T>()`** for cases where
  the .NET BCL raises a *derived* type:
  - `ArgumentException.ThrowIfNullOrEmpty(null, ...)` → throws `ArgumentNullException` (subclass of
    `ArgumentException`). Use `Assert.ThrowsAny<ArgumentException>()`.
  - `JsonDocument.Parse(badJson)` → throws `JsonReaderException` (subclass of `JsonException`). Use
    `Assert.ThrowsAny<JsonException>()`.
  - Rule of thumb: **`Assert.Throws<T>()`** for user-defined/custom exceptions where the exact type is
    guaranteed by your own code; **`Assert.ThrowsAny<T>()`** for BCL helpers that may raise a derived
    subclass. Mixing these up causes exact-match failures at the gate even when the production code is
    correct.

## Imports
- `using <Namespace>;` exactly as declared by the topology contract / production snapshot.

## WebApplicationFactory Integration Tests — Structurally Untestable Inputs (MANDATORY)

The ASP.NET in-memory transport used by `WebApplicationFactory<TEntryPoint>` + `HttpClient` silently
drops HTTP header values that are the **empty string `""`** before the request reaches Kestrel or any
middleware. A test that sends `request.Headers.TryAddWithoutValidation("X-Foo", "")` will find no
header in the pipeline → middleware validation never runs → the framework returns 404 (no route match),
not 400 (validation rejection). This is a deterministic transport limitation, not a production bug.

### QA
- **NEVER emit `[InlineData]` rows (or any equivalent parametrized rows) that pass an empty string `""`
  as a header value through `WebApplicationFactory` / `HttpClient.SendAsync`.** These cases are
  structurally untestable via the in-memory transport. Omit them entirely — do NOT treat `""` as a
  canonical boundary input for header parameters in integration tests.
- To test empty/missing header validation, write a UNIT test that calls the middleware/handler directly
  in-process (bypassing `WebApplicationFactory`), where the empty string is observable.

### Reviewer
- When the test-runner log shows `Assert.Equal() Failure: Expected: BadRequest / Actual: NotFound` for
  an `[InlineData]` case where one of the header parameters is `""`, this is the in-memory-transport
  stripping pattern — NOT a production bug. The production code is correct.
- Set `code_quality_approved: true`. In `qa_diagnostic_payload`, emit an explicit named removal
  directive: state the exact method name and the `[InlineData]` parameter values to remove, and
  explain that empty-string header values are untestable via `WebApplicationFactory`. Mark those
  specific rows as prohibited in future cycles (not just "remove these" — name the untestable input
  class so QA does not re-derive them).

## ASP.NET Core Middleware — `OnStarting` Callbacks in Unit Tests (MANDATORY)

When a middleware under test registers callbacks via `context.Response.OnStarting(...)`, bare
`DefaultHttpContext` does NOT fire them — the default `IHttpResponseFeature` implementation collects
but never executes `OnStarting` callbacks unless `Response.StartAsync()` is called through a feature
that actually fires them.

### QA — required pattern for unit tests

Replace the default feature with a stub that fires the callbacks before `_next` returns:

```csharp
private sealed class FakeHttpResponseFeature : HttpResponseFeature
{
    private readonly List<Func<object, Task>> _callbacks = new();
    private readonly List<object> _states = new();

    public override void OnStarting(Func<object, Task> callback, object state)
    {
        _callbacks.Add(callback);
        _states.Add(state);
    }

    public async Task FireOnStartingAsync()
    {
        for (int i = 0; i < _callbacks.Count; i++)
            await _callbacks[i](_states[i]);
    }
}
```

Wire it into each test method that exercises `OnStarting`-registered behavior:

```csharp
var context = new DefaultHttpContext();
var fakeFeature = new FakeHttpResponseFeature();
context.Features.Set<IHttpResponseFeature>(fakeFeature);

RequestDelegate next = async ctx =>
{
    await fakeFeature.FireOnStartingAsync();   // fire before next completes
    ctx.Response.Body = Stream.Null;
};

var middleware = new MyMiddleware(next, ...);
await middleware.InvokeAsync(context);

Assert.Equal(expectedStatus, context.Response.StatusCode);
```

- DETECT the need: if the production snapshot contains `context.Response.OnStarting(` and the test
  uses `DefaultHttpContext`, ALWAYS apply this pattern — do not omit it and do not rely on
  `WebApplicationFactory` for unit-level status/header assertions on the same behavior.
- Integration tests via `WebApplicationFactory` already fire `OnStarting` correctly (they go through
  the full pipeline). If both unit and integration coverage are present, the integration test is the
  authoritative behavioral check; the unit test is for isolation.

### Reviewer
- When the test-runner shows `Assert.Equal() Failure: Expected: <status>. Actual: 200` for a
  middleware test that uses `DefaultHttpContext`, the root cause is the missing `FakeHttpResponseFeature`
  stub — NOT a production bug. The production code is correct.
- Set `code_quality_approved: true`. In `qa_diagnostic_payload`, emit the `FakeHttpResponseFeature`
  pattern verbatim and instruct QA to replace `DefaultHttpContext`'s default `IHttpResponseFeature`
  before calling `InvokeAsync`.
