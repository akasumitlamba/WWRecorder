"""GitHub release checks and EXE installer download/launch.

Distribution contract (2026-10-28)
----------------------------------
* **EXE:** Query GitHub Releases for the latest stable tag, silently download
  the official Setup EXE, then launch Inno Setup. Never open a browser as the
  primary update path when a download URL is available.
* **MSIX:** Microsoft Store alone establishes update availability. Never query
  the EXE release feed, claim a Store update from an EXE version, or download
  or launch an EXE installer.

Workers never touch Qt widgets. Progress and errors are signals only.
"""
from __future__ import annotations

import json
import os
import re
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from distribution import is_packaged, update_url, store_url, RELEASES_URL

GITHUB_LATEST = "https://api.github.com/repos/akasumitlamba/WWRecorder/releases/latest"
USER_AGENT = "WWRecorder-Update-Checker"


def _make_ssl_context() -> ssl.SSLContext:
    """Create a verified SSL context (system CAs, then certifi fallback)."""
    try:
        return ssl.create_default_context()
    except Exception:
        pass
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass
    raise ssl.SSLError("No trusted certificate bundle is available for update checks.")


def is_newer_version(current: str, latest: str) -> bool:
    """Compare semantic versions without offering prerelease builds as upgrades."""
    pattern = re.compile(
        r"^v?(?P<num>\d+(?:\.\d+)*)(?:[-+](?P<label>[0-9A-Za-z.-]+))?$",
        re.IGNORECASE,
    )

    def parse(value):
        match = pattern.fullmatch(str(value).strip())
        if not match:
            return None
        numbers = tuple(int(part) for part in match.group("num").split("."))
        return numbers, bool(match.group("label"))

    current_parsed = parse(current)
    candidate = parse(latest)
    if current_parsed is None or candidate is None:
        return False
    current_numbers, current_prerelease = current_parsed
    latest_numbers, latest_prerelease = candidate
    length = max(len(current_numbers), len(latest_numbers))
    current_numbers += (0,) * (length - len(current_numbers))
    latest_numbers += (0,) * (length - len(latest_numbers))
    if latest_numbers != current_numbers:
        return latest_numbers > current_numbers and not latest_prerelease
    return current_prerelease and not latest_prerelease


def select_installer_asset(assets) -> str | None:
    """Pick the official WWRecorder Setup EXE download URL from GitHub assets.

    Prefers ``WWRecorder_Setup_*.exe`` and deprioritizes ``local-test`` builds.
    Returns None when no suitable asset exists (caller must surface a clear error).
    """
    ranked = []
    for asset in assets or []:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "")
        url = str(asset.get("browser_download_url") or "").strip()
        lower = name.lower()
        if not url or not lower.endswith(".exe"):
            continue
        if "wwrecorder" not in lower:
            continue
        score = 0
        if "wwrecorder_setup" in lower:
            score += 20
        if "setup" in lower:
            score += 5
        if "local-test" in lower or "local_test" in lower:
            score -= 10
        ranked.append((score, lower, url))
    if not ranked:
        return None
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return ranked[0][2]


def parse_github_release(data: dict, current_version: str, *, packaged: bool) -> tuple[bool, str, str, str]:
    """Return (available, version_tag, action_url, download_url) from a release JSON object.

    ``action_url`` is the Store page for MSIX and the GitHub releases page for EXE.
    ``download_url`` is only set for EXE when a Setup asset is present.
    """
    if packaged:
        return False, "", store_url() or update_url(), ""
    raw_tag = data.get("tag_name") or ""
    tag_name = str(raw_tag).lstrip("v")
    if not tag_name:
        raise ValueError("incomplete release tag")
    available = is_newer_version(current_version, tag_name)
    version = f"v{tag_name}"
    download = select_installer_asset(data.get("assets") or [])
    return available, version, RELEASES_URL, download or ""


def update_staging_directory() -> Path:
    """Isolated temp folder for installer downloads (never the user's media folder)."""
    root = Path(tempfile.gettempdir()) / "WWRecorder_updates"
    root.mkdir(parents=True, exist_ok=True)
    return root


def launch_inno_installer(installer_path: str) -> None:
    """Launch a downloaded Inno Setup installer.

    Uses ``/SILENT /NORESTART`` so the user is not sent through a browser, while
    still getting a real installer process. Caller must ensure capture is idle and
    typically quit the app afterward so Inno can replace files (installer mutex).
    """
    path = Path(installer_path)
    if not path.is_file() or path.suffix.lower() != ".exe":
        raise FileNotFoundError(f"Installer not found: {installer_path}")
    # Only launch files we staged under our update directory (path-safety).
    staged = update_staging_directory().resolve()
    resolved = path.resolve()
    if staged not in resolved.parents and resolved.parent != staged:
        raise PermissionError("Refusing to launch an installer outside the WWRecorder update staging folder.")
    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    # Inno recognizes /SILENT and /NORESTART. CLOSEAPPLICATIONS is controlled by the .iss.
    subprocess.Popen(
        [str(resolved), "/SILENT", "/NORESTART"],
        close_fds=True,
        creationflags=creationflags,
    )


class UpdateChecker(QThread):
    """EXE release check; packaged installs delegate exclusively to Microsoft Store."""

    # (is_available, latest_version, action_url, download_url)
    check_finished = pyqtSignal(bool, str, str, str)
    check_failed = pyqtSignal(str)

    def __init__(self, current_version: str):
        super().__init__()
        self.current_version = current_version.lower().lstrip("v")
        self.repo_url = GITHUB_LATEST
        self.website_url = update_url()
        self._packaged = is_packaged()

    def run(self):
        if self._packaged:
            self.check_finished.emit(False, "", store_url() or update_url(), "")
            return
        try:
            ctx = _make_ssl_context()
            req = urllib.request.Request(self.repo_url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, context=ctx, timeout=10) as response:
                data = json.loads(response.read().decode()) or {}
            if not isinstance(data, dict):
                self.check_failed.emit("The update server returned an incomplete response. Please try again later.")
                return
            available, version, action_url, download_url = parse_github_release(
                data, self.current_version, packaged=self._packaged
            )
            if available and not self._packaged and not download_url:
                # Newer tag exists but no Setup asset — still notify; UI can open the release page.
                pass
            self.check_finished.emit(available, version, action_url, download_url)
        except urllib.error.HTTPError as exc:
            if exc.code == 403:
                self.check_failed.emit("The update server is temporarily rate-limited. Please try again later.")
            else:
                self.check_failed.emit(f"The update server returned error {exc.code}. Please try again later.")
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            self.check_failed.emit("Could not reach the update server. Check your internet connection and try again.")
        except ValueError:
            self.check_failed.emit("The update server returned an incomplete response. Please try again later.")
        except Exception as exc:
            print(f"[Updater] Unexpected check failure: {exc}")
            self.check_failed.emit("Could not check for updates right now. Please try again later.")

    def _is_newer(self, latest: str) -> bool:
        """Compatibility wrapper used by existing unit tests."""
        return is_newer_version(self.current_version, latest)


class InstallerDownloader(QThread):
    """EXE-only: download the Setup EXE with progress, never used by MSIX."""

    progress = pyqtSignal(int)          # 0–100
    download_finished = pyqtSignal(str)  # local path
    download_failed = pyqtSignal(str)

    def __init__(self, download_url: str, version_label: str = ""):
        super().__init__()
        self.download_url = (download_url or "").strip()
        self.version_label = version_label or "update"
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        if is_packaged():
            self.download_failed.emit("This Microsoft Store installation cannot download EXE installers.")
            return
        if not self.download_url.startswith("https://"):
            self.download_failed.emit("The update download link is missing or invalid.")
            return
        # Defence: only accept GitHub release asset hosts.
        try:
            parsed = urlsplit(self.download_url)
            host_ok = (parsed.hostname == 'github.com' and parsed.username is None
                       and parsed.password is None and parsed.port in (None,443)
                       and parsed.path.startswith('/akasumitlamba/WWRecorder/releases/download/'))
        except ValueError:
            host_ok = False
        if not host_ok:
            self.download_failed.emit("The update download link is not from the official GitHub release.")
            return
        try:
            ctx = _make_ssl_context()
            req = urllib.request.Request(self.download_url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, context=ctx, timeout=60) as response:
                total = int(response.headers.get("Content-Length") or 0)
                safe_version = re.sub(r"[^0-9A-Za-z._-]+", "_", self.version_label).strip("_") or "update"
                destination = update_staging_directory() / f"WWRecorder_Setup_{safe_version}.exe"
                temporary = destination.with_suffix(".partial")
                received = 0
                self.progress.emit(0)
                with temporary.open("wb") as handle:
                    while True:
                        if self._cancel:
                            handle.close()
                            temporary.unlink(missing_ok=True)
                            self.download_failed.emit("Update download was cancelled.")
                            return
                        chunk = response.read(64 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
                        received += len(chunk)
                        if total > 0:
                            self.progress.emit(min(99, int(received * 100 / total)))
                os.replace(temporary, destination)
                if destination.stat().st_size <= 0:
                    destination.unlink(missing_ok=True)
                    self.download_failed.emit("The downloaded installer was empty. Nothing was installed.")
                    return
                self.progress.emit(100)
                self.download_finished.emit(str(destination))
        except urllib.error.HTTPError as exc:
            self.download_failed.emit(f"Download failed (HTTP {exc.code}). Your recordings were not changed.")
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as exc:
            self.download_failed.emit(
                f"Could not download the update ({exc}). Your recordings were not changed. Try again later."
            )
        except Exception as exc:
            print(f"[Updater] Download failure: {exc}")
            self.download_failed.emit("Could not download the update. Your recordings were not changed.")
