"""Plain-language explanations for typed filesystem failures.

Free-text diagnostics are preserved: file names, stream descriptions and encoder
logs cannot establish whether an audio endpoint failed.
"""
import errno
import re


def friendly_error(error) -> str:
    text = str(error or '').strip()
    winerror = getattr(error, 'winerror', None)
    err_no = getattr(error, 'errno', None)
    # A serialized OSError can retain only its stable Windows error code.
    if winerror is None and isinstance(error, OSError):
        match = re.search(r'\[WinError (\d+)\]', text)
        winerror = int(match.group(1)) if match else None
    if isinstance(error, FileExistsError) or err_no == errno.EEXIST or winerror == 183:
        return 'A file with that name already exists. Choose a different name and try again.'
    if winerror in (32, 33):
        return 'Windows is using this file. Close any player or app that has it open, then try again.'
    if isinstance(error, PermissionError) or winerror == 5:
        return 'Access to this file was denied. Check folder permissions in Windows or close any app using the file, then try again.'
    if err_no == errno.ENOSPC or winerror == 112:
        return 'The selected drive is full. Free some space or choose another save folder.'
    return text or 'The operation could not be completed. Please try again.'
