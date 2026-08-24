"""Adversarial tests against DockerExecutor's actual isolation.

Everything else in this suite asserts that the right *flags* are passed. That proves
the intent, not the effect. These run real commands inside a real container and check
what they can actually reach — which is the only thing that makes the claims in
SECURITY.md and the threat model more than an assertion about a string.

Marked `live` because they need a Docker daemon; deselected by default.

    uv run pytest -m live -q

The commands below are the ones an attacker would try first: read the host, write
outside the workspace, reach the network, execute from tmp, escalate privileges, and
find the Docker socket — which is the classic container escape.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tapeloop.sandbox.base import ExecResult
from tapeloop.sandbox.docker import DockerExecutor

pytestmark = pytest.mark.live

IMAGE = "python:3.12-slim"


@pytest.fixture(scope="module")
def executor() -> DockerExecutor:
    ex = DockerExecutor(image=IMAGE)
    if not ex.available():
        pytest.skip("docker binary not on PATH")
    probe = ex.run("true", cwd=Path.cwd(), timeout=180)
    if probe.exit_code != 0:
        pytest.skip(f"docker daemon unavailable: {probe.stderr[:120]}")
    return ex


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "allowed.txt").write_text("in the workspace", encoding="utf-8")
    (tmp_path / "SECRET-outside.txt").write_text("must not be readable", encoding="utf-8")
    return ws


def _run(ex: DockerExecutor, ws: Path, cmd: str) -> ExecResult:
    return ex.run(cmd, cwd=ws, timeout=90)


# ============================================== positive control
def test_the_container_can_do_the_job_it_exists_for(
    executor: DockerExecutor, workspace: Path
) -> None:
    """Isolation that breaks the feature is not isolation, it is a broken feature."""
    r = _run(executor, workspace, "cat allowed.txt && echo written > made.txt")
    assert r.exit_code == 0, r.stderr
    assert "in the workspace" in r.stdout
    assert (workspace / "made.txt").read_text(encoding="utf-8").strip() == "written"


# ============================================== filesystem containment
def test_the_host_filesystem_is_not_reachable(executor: DockerExecutor, workspace: Path) -> None:
    """The parent directory holds a secret. The workspace is the only mount."""
    r = _run(executor, workspace, "cat ../SECRET-outside.txt")
    assert r.exit_code != 0
    assert "must not be readable" not in r.stdout


def test_host_paths_resolve_to_the_image_not_the_mac(
    executor: DockerExecutor, workspace: Path
) -> None:
    """/etc/passwd exists inside, but it is the image's, not the host's."""
    r = _run(executor, workspace, "cat /etc/passwd")
    assert "darkangel" not in r.stdout.lower()
    r2 = _run(executor, workspace, "ls /Users 2>&1; ls /host_mnt 2>&1")
    assert "No such file" in r2.stdout or r2.exit_code != 0


def test_the_root_filesystem_is_read_only(executor: DockerExecutor, workspace: Path) -> None:
    for target in ("/etc/evil", "/usr/bin/evil", "/root/evil"):
        r = _run(executor, workspace, f"echo x > {target}")
        assert r.exit_code != 0, f"{target} was writable"
        assert (
            "read-only" in (r.stderr + r.stdout).lower()
            or "permission denied" in (r.stderr + r.stdout).lower()
        )


def test_tmp_is_writable_but_not_executable(executor: DockerExecutor, workspace: Path) -> None:
    """noexec on tmp: a downloaded payload has nowhere to run from."""
    r = _run(
        executor,
        workspace,
        "printf '#!/bin/sh\\necho pwned\\n' > /tmp/x && chmod +x /tmp/x && /tmp/x",
    )
    assert r.exit_code != 0, "a script in /tmp executed"
    assert "pwned" not in r.stdout


# ============================================== network
def test_the_network_is_off(executor: DockerExecutor, workspace: Path) -> None:
    """The exfiltration path. --network=none should make every attempt fail fast."""
    r = _run(executor, workspace, "getent hosts pypi.org; echo rc=$?")
    assert "rc=0" not in r.stdout, "DNS resolved"

    r2 = _run(
        executor,
        workspace,
        "python -c \"import socket;socket.create_connection(('1.1.1.1',53),timeout=5)\" 2>&1",
    )
    assert r2.exit_code != 0, "an outbound TCP connection succeeded"


def test_no_routable_interface_exists(executor: DockerExecutor, workspace: Path) -> None:
    """A fresh netns also contains down tunnel stubs -- tunl0, gre0, sit0 and friends --
    whenever those kernel modules are loaded on the host. They carry nothing. What must
    be absent is a *configured* interface; an eth0 with an address is what connectivity
    looks like, and the DNS and TCP tests above are the real proof."""
    r = _run(executor, workspace, "cat /proc/net/dev")
    names = [line.split(":")[0].strip() for line in r.stdout.splitlines() if ":" in line]
    assert not [n for n in names if n.startswith(("eth", "en", "wl"))], names
    assert "lo" in names


# ============================================== privilege
def test_capabilities_are_dropped(executor: DockerExecutor, workspace: Path) -> None:
    """--cap-drop=ALL. mount is the one that matters most: it is how you get the host disk."""
    # The authoritative check. Everything else is a probe that a platform quirk can
    # confound; an empty effective-capability set cannot be argued with.
    caps = _run(executor, workspace, "grep CapEff /proc/self/status").stdout
    value = caps.split()[-1] if caps.strip() else "ffffffffffffffff"
    assert int(value, 16) == 0, f"effective capabilities are not empty: {value}"

    # Behavioural confirmation. `chown` is deliberately NOT probed: on Docker Desktop
    # for macOS the bind mount emulates ownership and reports success regardless, so
    # it tests the volume driver rather than CAP_CHOWN.
    for cmd in ("mount -t proc proc /mnt", "mknod /tmp/dev c 1 3"):
        r = _run(executor, workspace, cmd)
        assert r.exit_code != 0, f"privileged operation succeeded: {cmd}"


def test_no_new_privileges_is_set(executor: DockerExecutor, workspace: Path) -> None:
    r = _run(executor, workspace, "grep NoNewPrivs /proc/self/status")
    assert "NoNewPrivs:\t1" in r.stdout or "NoNewPrivs:  1" in r.stdout.replace("\t", "  ")


# ============================================== the classic escape
def test_the_docker_socket_is_not_mounted(executor: DockerExecutor, workspace: Path) -> None:
    """Mounting /var/run/docker.sock is *the* container escape. It must not be there."""
    r = _run(executor, workspace, "ls -la /var/run/docker.sock")
    assert r.exit_code != 0
    r2 = _run(executor, workspace, "find / -name 'docker.sock' -maxdepth 6 2>/dev/null | head")
    assert r2.stdout.strip() == "", f"a docker socket is reachable: {r2.stdout}"


def test_host_processes_are_invisible(executor: DockerExecutor, workspace: Path) -> None:
    r = _run(executor, workspace, "ls /proc | grep -c '^[0-9]*$'")
    assert int(r.stdout.strip() or 0) < 20, "host PID namespace appears to be shared"


# ============================================== resource limits
def test_memory_is_capped(executor: DockerExecutor, workspace: Path) -> None:
    """A runaway allocation must die, not take the host down with it.

    The pages have to be *touched*. `bytearray(2GB)` alone maps zero pages
    copy-on-write and stays a few hundred KB resident, so it sails past a cgroup limit
    that is doing its job -- which is how the first version of this test simultaneously
    accused a working sandbox and proved nothing.
    """
    script = (
        'python -c "\n'
        "chunks=[]\n"
        "for i in range(20):\n"
        "    b=bytearray(100*1024*1024)\n"
        "    for off in range(0,len(b),4096): b[off]=1\n"
        "    chunks.append(b)\n"
        "print('SURVIVED')\"\n"
    )
    r = executor.run(script, cwd=workspace, timeout=180)
    assert r.exit_code != 0, "2 GB of resident memory survived a 512m limit"
    assert "SURVIVED" not in r.stdout
    assert r.exit_code == 137 or "killed" in (r.stdout + r.stderr).lower()


def test_a_hung_command_is_killed(executor: DockerExecutor, workspace: Path) -> None:
    r = executor.run("sleep 300", cwd=workspace, timeout=5)
    assert r.timed_out
    assert r.as_tool_output().startswith("ERROR: timed out")


def test_the_container_does_not_survive_the_command(
    executor: DockerExecutor, workspace: Path
) -> None:
    """--rm. A run that leaves containers behind leaks state between steps."""
    import subprocess

    before = subprocess.run(
        ["docker", "ps", "-aq"], capture_output=True, text=True, check=False
    ).stdout.count("\n")
    _run(executor, workspace, "echo hello")
    after = subprocess.run(
        ["docker", "ps", "-aq"], capture_output=True, text=True, check=False
    ).stdout.count("\n")
    assert after <= before, "a container was left behind"
