"""Check tracked/new text files for credential leaks without printing values."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
# Fingerprints of removed, publicly exposed demo credentials.
REMOVED_CREDENTIAL_HASHES = {
    "887b7d3665c967f0dff09eac8c7c08efb0a3c264cf5c3cfb73230b3f446b9cd6",
    "b83e3e191f2acfe2c3c27f2079c5c13ea8409e9abbf31b671d421d80bbc847c9",
}
KEY_PATTERN = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)"
)
URL_PATTERN = re.compile(r"https?://[^\s<>\"'`]+")
RUNTIME_CONFIGS = {
    "java/src/main/resources/application.yml",
    "java/src/main/resources/application-dev.yml",
    "java/src/main/resources/application-mysql.yml",
    "java/src/main/resources/application-prod.yml",
}


def scan_text(name: str, text: str) -> list[tuple[int, str]]:
    issues = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if KEY_PATTERN.search(line):
            issues.append((line_number, "possible private key or provider token"))
        if any(hashlib.sha256(word.encode()).hexdigest() in REMOVED_CREDENTIAL_HASHES
               for word in re.findall(r"[A-Za-z0-9_-]{12,}", line)):
            issues.append((line_number, "removed credential literal"))
        for candidate in URL_PATTERN.findall(line):
            try:
                url = urlsplit(candidate)
            except ValueError:
                continue
            # Deliberately fake rejection cases, never actual service credentials.
            synthetic_test = ("test" in Path(name).parts or "tests" in Path(name).parts) and (
                (url.hostname or "").endswith(".example") and "private-value" in candidate)
            if not synthetic_test and (
                url.username is not None or url.password is not None
                or re.search(r"(?i)[?&](?:api[_-]?key|token|secret|password)=", candidate)
            ):
                issues.append((line_number, "credential-bearing URL"))
        if name in RUNTIME_CONFIGS and re.search(
            r"\$\{(?:APP_HMAC_SECRET|APP_AGENT_TOKEN|DB_PASSWORD):[^}]+\}", line
        ):
            issues.append((line_number, "nonempty credential fallback in runtime config"))
    return issues


def main() -> int:
    raw = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT
    )
    failures = []
    for name in sorted(set(raw.decode("utf-8").split("\0")) - {""}):
        try:
            text = (ROOT / name).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError):
            continue
        failures.extend((name, line, reason) for line, reason in scan_text(name, text))
    for name, line, reason in failures:
        print(f"FAIL {name}:{line}: {reason}")
    print(f"Sensitive configuration audit: {'FAIL' if failures else 'PASS'} ({len(failures)} findings)")
    return bool(failures)


if __name__ == "__main__":
    raise SystemExit(main())
