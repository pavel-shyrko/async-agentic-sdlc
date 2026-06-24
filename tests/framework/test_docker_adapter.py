"""Unit tests for the hardened Docker sandbox adapter. ``create_subprocess_exec`` is always mocked —
no real docker — so the assembled argv (hardening flags, env injection, network, image) is asserted."""
import os
import unittest
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

from src.shared.core import docker_adapter
from src.shared.core.docker_adapter import run_in_image, execute_in_sandbox
from src.shared.core.environments import SUPPORTED_ENVIRONMENTS

_REPO = "/abs/repo"


def _empty_stream() -> MagicMock:
    reader = MagicMock()
    reader.readline = AsyncMock(return_value=b"")
    return reader


def _mock_proc(rc: int = 0) -> MagicMock:
    proc = MagicMock()
    proc.stdout = _empty_stream()
    proc.stderr = _empty_stream()
    proc.wait = AsyncMock(return_value=rc)
    proc.returncode = rc
    return proc


class RunInImageTests(unittest.IsolatedAsyncioTestCase):
    @mock.patch("src.shared.core.docker_adapter.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_argv_has_hardening_env_and_network(self, mock_exec: AsyncMock) -> None:
        mock_exec.return_value = _mock_proc(0)

        rc, out, err = await run_in_image(
            "img:tag", "go test ./...", _REPO,
            env={"HOME": "/tmp", "GOCACHE": "/tmp/.cache/go-build"}, network="bridge",
        )

        self.assertEqual(rc, 0)
        argv = list(mock_exec.call_args.args)
        # Network as requested + the least-privilege hardening flags.
        self.assertEqual(argv[:3], ["docker", "run", "--rm"])
        self.assertIn("--network", argv)
        self.assertEqual(argv[argv.index("--network") + 1], "bridge")
        for flag in ("--memory", "--pids-limit", "--cpus", "--cap-drop", "--tmpfs"):
            self.assertIn(flag, argv)
        self.assertEqual(argv[argv.index("--cap-drop") + 1], "ALL")
        # Env injected as --env KEY=VALUE pairs.
        self.assertIn("HOME=/tmp", argv)
        self.assertIn("GOCACHE=/tmp/.cache/go-build", argv)
        # Mount + image + shell command at the tail.
        self.assertIn(f"{_REPO}:/workspace", argv)
        self.assertEqual(argv[-4:], ["img:tag", "sh", "-c", "go test ./..."])

    @mock.patch("src.shared.core.docker_adapter.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_default_network_is_none(self, mock_exec: AsyncMock) -> None:
        mock_exec.return_value = _mock_proc(0)
        await run_in_image("img:tag", "pytest", _REPO)
        argv = list(mock_exec.call_args.args)
        self.assertEqual(argv[argv.index("--network") + 1], "none")

    async def test_rejects_multiline_command(self) -> None:
        with self.assertRaises(ValueError):
            await run_in_image("img:tag", "a\nb", _REPO)

    _CACHE = {"name": "sdlc-cache-x", "mount": "/cache", "env": {"NUGET_PACKAGES": "/cache/nuget"}}

    @mock.patch("src.shared.core.docker_adapter.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_cache_volume_read_only_by_default(self, mock_exec: AsyncMock) -> None:
        mock_exec.return_value = _mock_proc(0)
        await run_in_image("img:tag", "dotnet build", _REPO, network="none", cache_volume=self._CACHE)
        argv = list(mock_exec.call_args.args)
        self.assertIn("sdlc-cache-x:/cache:ro", argv)                     # RO unless restore phase
        self.assertIn("NUGET_PACKAGES=/cache/nuget", argv)                # cache env injected
        self.assertEqual(argv[-4:], ["img:tag", "sh", "-c", "dotnet build"])  # tail intact

    @mock.patch("src.shared.core.docker_adapter.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_cache_volume_writable_on_restore(self, mock_exec: AsyncMock) -> None:
        mock_exec.return_value = _mock_proc(0)
        await run_in_image(
            "img:tag", "dotnet restore", _REPO, network="bridge",
            cache_volume=self._CACHE, cache_writable=True,
        )
        argv = list(mock_exec.call_args.args)
        self.assertIn("sdlc-cache-x:/cache", argv)                        # RW (no :ro suffix)
        self.assertNotIn("sdlc-cache-x:/cache:ro", argv)

    @mock.patch("src.shared.core.docker_adapter.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_cache_env_overrides_base_env(self, mock_exec: AsyncMock) -> None:
        mock_exec.return_value = _mock_proc(0)
        await run_in_image(
            "img:tag", "dotnet restore", _REPO, network="bridge",
            env={"NUGET_PACKAGES": "/tmp/nuget"}, cache_volume=self._CACHE, cache_writable=True,
        )
        argv = list(mock_exec.call_args.args)
        self.assertIn("NUGET_PACKAGES=/cache/nuget", argv)                # cache wins
        self.assertNotIn("NUGET_PACKAGES=/tmp/nuget", argv)

    @mock.patch.dict(os.environ, {"HTTPS_PROXY": "http://proxy:8080", "NO_PROXY": "localhost"}, clear=False)
    @mock.patch("src.shared.core.docker_adapter.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_proxy_passthrough_bridge_only(self, mock_exec: AsyncMock) -> None:
        mock_exec.return_value = _mock_proc(0)
        await run_in_image("img:tag", "dotnet restore", _REPO, network="bridge")
        argv = list(mock_exec.call_args.args)
        self.assertIn("HTTPS_PROXY=http://proxy:8080", argv)
        self.assertIn("NO_PROXY=localhost", argv)

        mock_exec.reset_mock()
        await run_in_image("img:tag", "dotnet test", _REPO, network="none")
        argv = list(mock_exec.call_args.args)
        self.assertNotIn("HTTPS_PROXY=http://proxy:8080", argv)           # isolated phase stays clean


class ExecuteInSandboxTests(unittest.IsolatedAsyncioTestCase):
    @mock.patch("src.shared.core.docker_adapter.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_injects_env_sandbox_env_and_image(self, mock_exec: AsyncMock) -> None:
        mock_exec.return_value = _mock_proc(0)
        env_id = "go-1.23-cli"

        await execute_in_sandbox(env_id, "go test ./...", _REPO, network="none")

        argv = list(mock_exec.call_args.args)
        spec = SUPPORTED_ENVIRONMENTS[env_id]
        self.assertIn(spec["image"], argv)
        # The persistent cache volume's env overrides the matching tmpfs sandbox_env key, so assert the
        # EFFECTIVE merged value reaches the container (cache env wins on conflict).
        overrides = (spec.get("cache_volume") or {}).get("env") or {}
        for k, v in {**spec["sandbox_env"], **overrides}.items():
            self.assertIn(f"{k}={v}", argv)
        # The env's cache volume is mounted (read-only on this non-restore call).
        if spec.get("cache_volume"):
            cv = spec["cache_volume"]
            self.assertIn(f"{cv['name']}:{cv['mount']}:ro", argv)

    async def test_rejects_unknown_environment(self) -> None:
        with self.assertRaises(ValueError):
            await execute_in_sandbox("no-such-env", "pytest", _REPO)


class SandboxCpuCapTests(unittest.IsolatedAsyncioTestCase):
    """The sandbox CPU cap is env-overridable (config-constant-convention) and defaults to 4 — more cores
    speed CPU-bound gates (notably the semgrep SAST scan). The value flows verbatim into the docker argv."""

    @mock.patch("src.shared.core.docker_adapter.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_cpus_value_flows_to_argv(self, mock_exec: AsyncMock) -> None:
        mock_exec.return_value = _mock_proc(0)
        await run_in_image("img:tag", "pytest", _REPO)
        argv = list(mock_exec.call_args.args)
        self.assertEqual(argv[argv.index("--cpus") + 1], docker_adapter._SANDBOX_CPUS)

    def test_default_is_four_when_env_unset(self) -> None:
        import importlib
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SANDBOX_CPUS", None)
            reloaded = importlib.reload(docker_adapter)
            self.addCleanup(importlib.reload, docker_adapter)  # restore the real-env constant after
            self.assertEqual(reloaded._SANDBOX_CPUS, "4")

    def test_env_override_is_honored(self) -> None:
        import importlib
        with mock.patch.dict(os.environ, {"SANDBOX_CPUS": "1"}):
            reloaded = importlib.reload(docker_adapter)
            self.addCleanup(importlib.reload, docker_adapter)
            self.assertEqual(reloaded._SANDBOX_CPUS, "1")


if __name__ == "__main__":
    unittest.main()
