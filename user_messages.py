"""Plain-language explanations for common user-visible failures."""
import errno


def friendly_error(error) -> str:
    text = str(error or "").strip()
    winerror = getattr(error, "winerror", None)
    err_no = getattr(error, "errno", None)
    low = text.lower()
    if isinstance(error, FileExistsError) or err_no == errno.EEXIST or "already exists" in low:
        return "A file with that name already exists. Choose a different name and try again."
    if isinstance(error, PermissionError) or winerror in (5, 32, 33) or "winerror 32" in low:
        return "Windows is using this file. Close any player or app that has it open, then try again."
    if err_no == errno.ENOSPC or "no space left" in low or "disk full" in low:
        return "The selected drive is full. Free some space or choose another save folder."
    if "ffmpeg" in low or "exit code" in low:
        return "The video could not be processed. Your original recording is kept safe; try again after restarting the app."
    if "audio" in low or "wav" in low or "microphone" in low:
        return "The audio device stopped working. Reconnect it or choose another device before recording again."
    return text or "The operation could not be completed. Please try again."
