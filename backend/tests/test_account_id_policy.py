"""Only example account ids appear in the fixture generator and the tests.

Any twelve-digit number in these files reads as an AWS account id, and one copied
from a live run (an AccessDenied message, an ARN from the console) is a real
account's. So every twelve-digit run here has to be one of EXAMPLE_ACCOUNT_IDS,
the stand-ins the suite already uses. That is all this can show: that nothing
else appears beside them, not that none of them is anyone's account.

The scan covers what pytest and vitest run, so it pins where they look. If either
starts looking somewhere else, the pins fail until the scan follows; if the tests
it expects are gone, the scan fails instead of passing over nothing.

The demo fixtures answer to a narrower set in test_demo_fixtures.py, which also
keeps moto's default account out of their ARNs.
"""

import configparser
import re
from pathlib import Path

from tests.conftest import REPO_ROOT

EXAMPLE_ACCOUNT_IDS = {
    "000000000000",
    "111111111111",
    "111122223333",
    "123456789012",  # moto's default account
    "222222222222",
    "333333333333",
    "444455556666",
    "777788889999",
    "999999999999",
}

# `[0-9]`, not `\d`: `\d` matches every Unicode decimal digit.
TWELVE_DIGITS = re.compile(r"(?<![0-9])[0-9]{12}(?![0-9])")

THIS_FILE = Path(__file__).resolve()
GENERATOR = REPO_ROOT / "backend" / "scripts" / "generate_demo_fixtures.py"
BACKEND_TESTS = REPO_ROOT / "backend" / "tests"
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"

# Where the runners look, as their configs say it. The scan reads the same places:
# every .py under backend/tests, and every src/**/*.test.{js,jsx} plus the setup
# file under frontend/.
PYTEST_TESTPATHS = "tests"
PYTEST_PYTHON_FILES = "test_*.py"
VITEST_INCLUDE = '["src/**/*.test.{js,jsx}"]'
VITEST_SETUP_FILES = '["./src/test/setup.js"]'


def vitest_option(name):
    """Every `name: [...]` in vite.config.js, as written."""
    text = (REPO_ROOT / "frontend" / "vite.config.js").read_text(encoding="utf-8")
    return re.findall(rf"^\s*{name}:\s*(\[[^\]]*\])", text, re.MULTILINE)


def governed_files():
    """The generator and every test file, or an assertion if the tests are gone."""
    backend = sorted(BACKEND_TESTS.rglob("*.py"))
    frontend = sorted({*FRONTEND_SRC.rglob("*.test.js"), *FRONTEND_SRC.rglob("*.test.jsx")})
    # This file and the setup file are always there, so neither counts as finding tests.
    assert any(p.name.startswith("test_") and p != THIS_FILE for p in backend), "no backend tests"
    assert frontend, "no frontend tests"
    return [GENERATOR, *backend, *frontend, FRONTEND_SRC / "test" / "setup.js"]


def unexpected_ids(text):
    return [m.group() for m in TWELVE_DIGITS.finditer(text) if m.group() not in EXAMPLE_ACCOUNT_IDS]


def test_the_scan_looks_where_pytest_and_vitest_do():
    pytest_ini = configparser.ConfigParser()
    pytest_ini.read(REPO_ROOT / "backend" / "pytest.ini")
    assert pytest_ini["pytest"]["testpaths"] == PYTEST_TESTPATHS
    assert pytest_ini["pytest"]["python_files"] == PYTEST_PYTHON_FILES
    assert vitest_option("include") == [VITEST_INCLUDE]
    assert vitest_option("setupFiles") == [VITEST_SETUP_FILES]


def test_only_example_account_ids_appear_in_the_generator_and_the_tests():
    found = []
    for path in governed_files():
        lines = path.read_text(encoding="utf-8").splitlines()
        for number, line in enumerate(lines, start=1):
            for account_id in unexpected_ids(line):
                found.append(f"{path.relative_to(REPO_ROOT)}:{number}: {account_id}")
    assert not found, "Twelve-digit ids outside EXAMPLE_ACCOUNT_IDS:\n" + "\n".join(found)


def test_the_check_reports_an_id_outside_the_set():
    # Assembled at runtime: written out whole, it would fail the check above.
    unknown = "56" * 6
    assert unexpected_ids(f"arn:aws:iam::{unknown}:role/R") == [unknown]
    assert unexpected_ids("arn:aws:iam::111122223333:role/R") == []
    assert unexpected_ids("7" * 13) == []  # a longer run is not an account id
