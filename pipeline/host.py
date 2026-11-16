"""What this computer can do: the one place that knows the operating system (plain Python, no imports beyond the
standard library and machine.py; docs/adapters.md "Host capabilities").

    python3 -I pipeline/host.py      prints the capabilities, the network modes and the GPU lock path

Questions it answers:

    capabilities()           the names an adapter's `requires` may list: accelerators (apple_silicon, cuda, cpu),
                             programs on PATH (blender) and network_denied / network_loopback_only when a child
                             process can be held to them
    unmet(requires)          one plain sentence per requirement this host does not meet ([] when all are met)
    sandboxed(argv, network) argv wrapped so the child runs with the network denied ("deny"), limited to this
                             computer ("loopback") or as it is ("allow"); HostError when the host cannot do it
    gpu_lock_path()          the machine-wide GPU lock file: the machine setting gpu_lock (no guess; a missing
                             setting is machine.MachineError naming the key and the file)
    rss_bytes(ru_maxrss)     resource.getrusage's ru_maxrss in bytes (its unit differs between systems)

Nothing else in the repository branches on the operating system; a test checks that.
"""
import functools
import platform
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import machine  # noqa: E402

ACCELERATORS = ("apple_silicon", "cuda", "cpu")
PROGRAMS = {"blender": "blender"}  # capability -> the program on PATH that provides it
NETWORK = {"deny": "network_denied", "loopback": "network_loopback_only"}  # sandbox mode -> capability it needs
KNOWN = (*ACCELERATORS, *PROGRAMS, *NETWORK.values())
MAC_SANDBOX = "/usr/bin/sandbox-exec"
MAC_PROFILES = {
    "deny": "(version 1)(allow default)(deny network*)",
    "loopback": "(version 1)(allow default)(deny network*)\n"
                '(allow network-inbound (local ip "localhost:*"))\n'
                '(allow network-outbound (remote ip "localhost:*"))\n'
                '(allow network-bind (local ip "localhost:*"))',
}
UNMET = {
    "apple_silicon": "an Apple Silicon Mac (this host is {system} on {machine_name})",
    "cuda": "an NVIDIA GPU with CUDA (nvidia-smi was not found on PATH)",
    "cpu": "a CPU",
    "blender": "Blender, run headless (`blender` was not found on PATH; install it from https://www.blender.org)",
    "network_denied": "a way to deny a child process the network ({why})",
    "network_loopback_only": "a way to limit a child process to this computer's own network ({why})",
}


class HostError(RuntimeError):
    """The host cannot do what was asked; the message says what and why."""


def _system():
    return platform.system()


def _is_mac():
    return _system() == "Darwin"


def accelerators():
    """The accelerators found, best first; `cpu` is always there."""
    found = []
    if _is_mac() and platform.machine() == "arm64":
        found.append("apple_silicon")
    if shutil.which("nvidia-smi"):
        found.append("cuda")
    return [*found, "cpu"]


@functools.lru_cache(maxsize=None)
def _linux_netns():
    """True when an unprivileged network namespace can be made (unshare -rn), the Linux way to deny the network."""
    tool = shutil.which("unshare")
    if _system() != "Linux" or not tool:
        return False
    try:
        return subprocess.run([tool, "-rn", "true"], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def network_modes():
    """The sandbox modes this host can apply: always "allow", plus "deny" and "loopback" where supported."""
    modes = ["allow"]
    if _is_mac() and Path(MAC_SANDBOX).is_file():
        modes += ["deny", "loopback"]
    elif _linux_netns():
        modes.append("deny")
    return modes


def _why_no_network_mode():
    if _is_mac():
        return f"{MAC_SANDBOX} is missing"
    if _system() == "Linux":
        return "`unshare -rn` is not available or user namespaces are off"
    return f"no sandbox is known for {_system()}"


def programs():
    """The program capabilities found on PATH (blender)."""
    return [name for name, program in PROGRAMS.items() if shutil.which(program)]


def capabilities():
    modes = network_modes()
    return [*accelerators(), *programs(), *(NETWORK[mode] for mode in NETWORK if mode in modes)]


def unmet(requires):
    """One sentence per name in REQUIRES that this host lacks; an unknown name is an error, not a pass."""
    have = set(capabilities())
    problems = []
    for name in requires:
        if name not in KNOWN:
            problems.append(f"'{name}' is not a capability this tool knows (known: {', '.join(KNOWN)})")
        elif name not in have:
            problems.append("needs " + UNMET[name].format(system=_system(), machine_name=platform.machine(),
                                                         why=_why_no_network_mode()))
    return problems


def sandboxed(argv, network):
    """ARGV (a list) wrapped for NETWORK ("allow", "deny" or "loopback"); HostError when the host cannot apply it."""
    argv = [str(part) for part in argv]
    if network == "allow":
        return argv
    if network not in NETWORK:
        raise HostError(f"unknown network mode {network!r} (known: allow, {', '.join(NETWORK)})")
    if network not in network_modes():
        raise HostError("cannot run with the network " + ("denied" if network == "deny" else "limited to this computer")
                        + f": {_why_no_network_mode()}; the run is refused rather than run with the network open")
    if _is_mac():
        return [MAC_SANDBOX, "-p", MAC_PROFILES[network], *argv]
    return [shutil.which("unshare"), "-rn", *argv]


def prove_network_denied(network="deny"):
    """Raise HostError unless a child under NETWORK is refused an outside address by the sandbox itself (an offline
    computer's timeout does not count; no packet leaves when the denial works)."""
    probe = "import socket; socket.create_connection(('1.1.1.1', 443), 1)"
    result = subprocess.run(sandboxed([sys.executable, "-I", "-c", probe], network), capture_output=True, text=True,
                            timeout=10, check=False)
    denied = ("Operation not permitted", "Network is unreachable")  # the sandbox's refusal, not a slow network
    if result.returncode == 0 or not any(text in result.stderr for text in denied):
        raise HostError("the network denial check failed: a sandboxed child was not refused the network")


def gpu_lock_path(environ=None, home=None):
    """The machine-wide GPU lock file (the machine setting gpu_lock). Only adapters whose entry says `gpu` take it,
    so a computer that runs only the stand-in never needs the setting."""
    return machine.path("gpu_lock", environ, home)


def rss_bytes(ru_maxrss):
    """ru_maxrss is bytes on macOS and kilobytes on Linux."""
    return ru_maxrss if _is_mac() else ru_maxrss * 1024


def main():
    print(f"system: {_system()} {platform.machine()}")
    print(f"capabilities: {', '.join(capabilities())}")
    print(f"network modes: {', '.join(network_modes())}")
    try:
        print(f"gpu lock: {gpu_lock_path()}")
    except machine.MachineError as error:
        print(f"gpu lock: {error}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
