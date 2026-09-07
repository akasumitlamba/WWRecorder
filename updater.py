import json
import urllib.request
import urllib.error
import re
import ssl
from PyQt6.QtCore import QThread, pyqtSignal


def _make_ssl_context() -> ssl.SSLContext:
    """Create a verified SSL context."""
    # 1. Try default system CA bundle
    try:
        ctx = ssl.create_default_context()
        return ctx
    except Exception:
        pass
    # 2. Fallback: use certifi bundle if available
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
        return ctx
    except Exception:
        pass
    raise ssl.SSLError("No trusted certificate bundle is available for update checks.")

class UpdateChecker(QThread):
    """
    Background worker to check for latest version on GitHub.
    Emits result via 'check_finished' signal.
    """
    # (is_available, latest_version, website_url, download_url)
    check_finished = pyqtSignal(bool, str, str, str)
    check_failed = pyqtSignal(str)

    def __init__(self, current_version: str):
        super().__init__()
        self.current_version = current_version.lower().lstrip('v')
        self.repo_url = "https://api.github.com/repos/akasumitlamba/WWRecorder/releases/latest"
        # Store builds never download or launch GitHub installers.  GitHub is
        # used only as a lightweight version feed; updates open the Store page.
        self.website_url = "https://aka.ms/AA1364bx"

    def run(self):
        try:
            ctx = _make_ssl_context()

            headers = {'User-Agent': 'WWRecorder-Update-Checker'}
            req = urllib.request.Request(self.repo_url, headers=headers)
            
            with urllib.request.urlopen(req, context=ctx, timeout=10) as response:
                data = json.loads(response.read().decode()) or {}
                
                # Extract version tag from response
                raw_tag = data.get("tag_name") or ""
                tag_name = raw_tag.lstrip('v')
                if not tag_name:
                    self.check_failed.emit("The update server returned an incomplete response. Please try again later.")
                    return

                is_available = self._is_newer(tag_name)
                self.check_finished.emit(is_available, f"v{tag_name}", self.website_url, "")

        except urllib.error.HTTPError as exc:
            if exc.code == 403:
                self.check_failed.emit("The update server is temporarily rate-limited. Please try again later.")
            else:
                self.check_failed.emit(f"The update server returned error {exc.code}. Please try again later.")
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            self.check_failed.emit("Could not reach the update server. Check your internet connection and try again.")
        except Exception as e:
            # For other unexpected issues, still log them
            print(f"[Updater] Unexpected check failure: {e}")
            self.check_failed.emit("Could not check for updates right now. Please try again later.")

    def _is_newer(self, latest: str) -> bool:
        """Compare semantic versions without offering prerelease builds."""
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

        current = parse(self.current_version)
        candidate = parse(latest)
        if current is None or candidate is None:
            return False
        current_numbers, current_prerelease = current
        latest_numbers, latest_prerelease = candidate
        length = max(len(current_numbers), len(latest_numbers))
        current_numbers += (0,) * (length - len(current_numbers))
        latest_numbers += (0,) * (length - len(latest_numbers))
        if latest_numbers != current_numbers:
            return latest_numbers > current_numbers and not latest_prerelease
        return current_prerelease and not latest_prerelease
