"""Test the Windows setup, start and test scripts without installing or launching anything.

The scripts are PowerShell, so these run only on Windows. Anything that would change the machine uses -CheckOnly or
-DryRun, or points -ProjectRoot at an empty temporary folder. Starting PowerShell takes seconds, so every invocation is
run once, in parallel, when the module starts; the tests then check the recorded results.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
POWERSHELL = shutil.which("powershell")
WINDOWS_ONLY = unittest.skipUnless(sys.platform == "win32" and POWERSHELL, "the scripts are for Windows PowerShell")
HAS_VENV = (ROOT / ".venv" / "Scripts" / "python.exe").exists()

_temp_folders: list[tempfile.TemporaryDirectory] = []
RESULTS: dict[str, subprocess.CompletedProcess] = {}


def run_script(name: str, *args: str, timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPTS / name), *args],
        capture_output=True, text=True, timeout=timeout, cwd=ROOT)


def parse_check() -> subprocess.CompletedProcess:
    files = ", ".join(f"'{path}'" for path in sorted(SCRIPTS.glob("*.ps1")))
    command = (f"$bad = 0; foreach ($f in @({files})) {{ $errors = $null; $tokens = $null; "
               "[void][System.Management.Automation.Language.Parser]::ParseFile($f, [ref]$tokens, [ref]$errors); "
               "foreach ($e in $errors) { Write-Output \"$f : $e\"; $bad++ } }; exit $bad")
    return subprocess.run([POWERSHELL, "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=60)


def temp_folder(setup=None) -> str:
    folder = tempfile.TemporaryDirectory()
    _temp_folders.append(folder)
    if setup:
        setup(Path(folder.name))
    return folder.name


def setUpModule() -> None:
    if not (sys.platform == "win32" and POWERSHELL):
        return
    empty = temp_folder()
    with_example = temp_folder(lambda p: (p / ".env.example").write_text("LOG_LEVEL=INFO\n", encoding="ascii"))

    def fake_venv(path: Path) -> None:  # start.ps1 only checks that the interpreter file exists
        (path / ".venv" / "Scripts").mkdir(parents=True)
        (path / ".venv" / "Scripts" / "python.exe").write_bytes(b"")

    no_env = temp_folder(fake_venv)
    before_listing = sorted(p.name for p in Path(with_example).iterdir())

    jobs = {
        "parse": parse_check,
        "dry": lambda: run_script("start.ps1", "-DryRun", "-User", "steve"),
        "options": lambda: run_script("start.ps1", "-DryRun", "-NoPlayer", "-Preview", "-Dashboard"),
        "badname-chars": lambda: run_script("start.ps1", "-DryRun", "-User", "bad name; calc"),
        "badname-short": lambda: run_script("start.ps1", "-DryRun", "-User", "ab"),
        "badname-subst": lambda: run_script("start.ps1", "-DryRun", "-User", "a$(whoami)b"),
        "both": lambda: run_script("start.ps1", "-DryRun", "-User", "steve", "-NoPlayer"),
        "neither": lambda: run_script("start.ps1", "-DryRun"),
        "start-not-set-up": lambda: run_script("start.ps1", "-User", "steve", "-ProjectRoot", empty),
        "start-no-env": lambda: run_script("start.ps1", "-User", "steve", "-ProjectRoot", no_env),
        "setup-empty": lambda: run_script("setup.ps1", "-CheckOnly", "-ProjectRoot", with_example),
        "test-not-set-up": lambda: run_script("test.ps1", "-ProjectRoot", empty),
    }
    if HAS_VENV and (ROOT / ".env").exists():
        jobs["setup-real"] = lambda: run_script("setup.ps1", "-CheckOnly")
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {name: pool.submit(job) for name, job in jobs.items()}
        for name, future in futures.items():
            RESULTS[name] = future.result()
    RESULTS["_listing_before"] = before_listing  # type: ignore[assignment]
    RESULTS["_listing_after"] = sorted(p.name for p in Path(with_example).iterdir())  # type: ignore[assignment]


def tearDownModule() -> None:
    for folder in _temp_folders:
        folder.cleanup()


def out(name: str) -> str:
    done = RESULTS[name]
    return done.stdout + done.stderr


class FileHygieneTests(unittest.TestCase):
    def test_scripts_are_plain_ascii(self) -> None:
        # Windows PowerShell 5.1 reads a file without a byte-order mark as ANSI, so non-ASCII text gets mangled.
        for path in [*SCRIPTS.glob("*.ps1"), *ROOT.glob("MotionPlay-*.cmd")]:
            with self.subTest(path.name):
                path.read_bytes().decode("ascii")

    def test_the_expected_scripts_exist(self) -> None:
        for name in ("setup.ps1", "start.ps1", "test.ps1"):
            self.assertTrue((SCRIPTS / name).is_file(), name)

    def test_double_click_launchers_run_their_script_with_arguments_passed_on(self) -> None:
        for launcher, script in (("MotionPlay-Setup.cmd", "setup.ps1"), ("MotionPlay-Start.cmd", "start.ps1"),
                                 ("MotionPlay-Test.cmd", "test.ps1")):
            raw = (ROOT / launcher).read_bytes()
            text = raw.decode("ascii")
            with self.subTest(launcher):
                self.assertNotIn(b"\t", raw)  # a mangled "\t" in a path once turned into a real tab
                self.assertIn(f"scripts\\{script}", text)
                self.assertIn("-ExecutionPolicy Bypass", text)  # works even where scripts are restricted
                self.assertIn("%*", text)
                self.assertIn("%~dp0", text)  # relative to the launcher, not the current folder
                self.assertIn("\r\n", text)  # batch files want Windows line endings


@WINDOWS_ONLY
class SyntaxTests(unittest.TestCase):
    def test_every_script_parses(self) -> None:
        self.assertEqual(0, RESULTS["parse"].returncode, out("parse"))


@WINDOWS_ONLY
class StartScriptTests(unittest.TestCase):
    def test_dry_run_shows_both_windows_and_starts_nothing(self) -> None:
        self.assertEqual(0, RESULTS["dry"].returncode, out("dry"))
        self.assertIn("backend.result_receiver --store sqlite --user steve", out("dry"))
        self.assertIn("cv_engine.controller --no-preview", out("dry"))
        self.assertIn("Dry run", out("dry"))

    def test_options_change_what_is_started(self) -> None:
        self.assertEqual(0, RESULTS["options"].returncode, out("options"))
        self.assertNotIn("--user", out("options"))
        self.assertNotIn("--no-preview", out("options"))  # the preview window was asked for
        self.assertIn("app.dashboard", out("options"))

    def test_unsafe_or_invalid_player_names_are_refused_before_anything_runs(self) -> None:
        for name in ("badname-chars", "badname-short", "badname-subst"):
            with self.subTest(name):
                self.assertEqual(1, RESULTS[name].returncode)
                self.assertIn("3 to 32 letters", out(name))
                self.assertNotIn("result_receiver", out(name))

    def test_conflicting_or_missing_player_choice_is_refused(self) -> None:
        self.assertEqual(1, RESULTS["both"].returncode)
        self.assertIn("not both", out("both"))
        self.assertEqual(1, RESULTS["neither"].returncode)
        self.assertIn("-User <name>, or -NoPlayer", out("neither"))

    def test_a_folder_that_is_not_set_up_points_to_setup(self) -> None:
        self.assertEqual(1, RESULTS["start-not-set-up"].returncode)
        self.assertIn("setup.ps1", out("start-not-set-up"))

    def test_a_missing_env_file_is_reported(self) -> None:
        self.assertEqual(1, RESULTS["start-no-env"].returncode)
        self.assertIn(".env", out("start-no-env"))


@WINDOWS_ONLY
class SetupScriptTests(unittest.TestCase):
    def test_check_only_on_an_empty_folder_reports_what_is_missing_and_creates_nothing(self) -> None:
        self.assertEqual(1, RESULTS["setup-empty"].returncode)
        self.assertIn(".venv does not exist", out("setup-empty"))
        self.assertIn(".env does not exist", out("setup-empty"))
        self.assertIn("Setup is NOT complete", out("setup-empty"))
        self.assertEqual(RESULTS["_listing_before"], RESULTS["_listing_after"], "-CheckOnly must not change anything")

    @unittest.skipUnless(HAS_VENV and (ROOT / ".env").exists(), "needs the project's own environment")
    def test_check_only_on_this_project_passes_when_it_is_set_up(self) -> None:
        self.assertEqual(0, RESULTS["setup-real"].returncode, out("setup-real"))
        self.assertIn("Everything is ready", out("setup-real"))
        self.assertIn("Health check passed", out("setup-real"))


@WINDOWS_ONLY
class TestScriptTests(unittest.TestCase):
    def test_a_folder_that_is_not_set_up_is_refused(self) -> None:
        self.assertEqual(1, RESULTS["test-not-set-up"].returncode)
        self.assertIn("not set up", out("test-not-set-up"))


if __name__ == "__main__":
    unittest.main()
