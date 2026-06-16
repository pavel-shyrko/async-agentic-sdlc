# Sandbox image for the dotnet-10-sdk environment. `dotnet test`/`dotnet restore` are built into the
# base; SAST is the generic Semgrep image. Writable HOME + NuGet/CLI caches for the non-root --user run.
FROM mcr.microsoft.com/dotnet/sdk:10.0-alpine
ENV HOME=/tmp \
    DOTNET_CLI_HOME=/tmp \
    NUGET_PACKAGES=/tmp/nuget \
    XDG_DATA_HOME=/tmp/.local \
    DOTNET_NOLOGO=1 \
    DOTNET_CLI_TELEMETRY_OPTOUT=1
