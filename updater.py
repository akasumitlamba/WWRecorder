import json
import urllib.request
import ssl
from PyQt6.QtCore import QThread, pyqtSignal

class UpdateChecker(QThread):
    """
    Background worker to check for latest version on GitHub.
    Emits result via 'finished' signal.
    """
    # (is_available, latest_version, website_url)
    finished = pyqtSignal(bool, str, str)

    def __init__(self, current_version: str):
        super().__init__()
        self.current_version = current_version.lower().lstrip('v')
        self.repo_url = "https://api.github.com/repos/akasumitlamba/WWRecorder/releases/latest"
        self.website_url = "https://akasumitlamba.github.io/WWRecorder/"

    def run(self):
        try:
            # Create a context that ignores SSL cert issues (common in bundled apps)
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

            headers = {'User-Agent': 'WWRecorder-Update-Checker'}
            req = urllib.request.Request(self.repo_url, headers=headers)
            
            with urllib.request.urlopen(req, context=ctx, timeout=10) as response:
                data = json.loads(response.read().decode())
                
                # GitHub tags are expected as 'vX.Y' per user instructions
                tag_name = data.get("tag_name", "").lower().lstrip('v')
                
                if not tag_name:
                    self.finished.emit(False, "", "")
                    return

                # Compare version strings. 
                # Simple prefix/equality since user said tags follow vX.Y
                is_available = self._is_newer(tag_name)
                self.finished.emit(is_available, f"v{tag_name}", self.website_url)

        except Exception as e:
            print(f"[Updater] Check failed: {e}")
            self.finished.emit(False, "", "")

    def _is_newer(self, latest: str) -> bool:
        """Helper to compare version strings like '1.2' vs '1.2.0'"""
        try:
            # Split by dots and compare as integer tuples
            def to_tuple(v):
                return tuple(int(x) for x in v.split('.') if x.isdigit())
            
            curr_t = to_tuple(self.current_version)
            late_t = to_tuple(latest)
            
            return late_t > curr_t
        except:
            # Fallback to direct string comparison if parsing fails
            return latest > self.current_version
