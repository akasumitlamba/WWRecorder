# WWRecorder public website

This folder contains the static GitHub Pages website for WWRecorder. It is deliberately independent of the desktop application's source and build system.

## Pages

- `index.html` — product overview and feature tour
- `download.html` — Microsoft Store and latest stable installer choices
- `install-help.html` — Windows download and installation troubleshooting
- `specs.html` — detailed platform, capture, audio, editing and storage specifications
- `privacy-policy.html` — application and website privacy details
- `legal.html` — distribution, ownership and third-party notices

## Static release handling

The installer chooser requests:

```text
https://api.github.com/repos/akasumitlamba/WWRecorder/releases?per_page=30
```

The script filters out draft and prerelease entries, accepts only `.exe` assets hosted below the official WWRecorder GitHub Releases path, starts the newest stable installer from `download.html`, and exposes older stable installers in a version selector. If lookup fails, it links to the GitHub release page for manual review.

## Publishing installer fingerprints

After publishing an installer, copy its release name, asset filename, and GitHub-provided SHA-256 digest into `OFFICIAL_INSTALLER_RELEASES` near the top of `script.js`:

```javascript
const OFFICIAL_INSTALLER_RELEASES = Object.freeze([
  Object.freeze({
    releaseName: 'WWRecorder 1.6.3',
    filename: 'WWRecorder_Setup_1.6.3.exe',
    sha256: 'paste-the-64-character-lowercase-sha256-here'
  })
]);
```

Generate the value on Windows with `Get-FileHash -Algorithm SHA256 "C:\path\to\WWRecorder_Setup.exe"`. The installation-help page compares visitor input locally; it does not upload either the installer or the fingerprint.

## Local preview

You can double-click this folder's `index.html` for a basic local preview. This `site` folder is the complete website root: its HTML, CSS and JavaScript are at the top level, with referenced artwork under `icons/` and `media/`.

For the complete download/release behavior, preview through a local server because browsers may limit GitHub API requests from `file:` pages.

From this folder:

```powershell
python -m http.server 8765 --bind 127.0.0.1
```

Then open `http://127.0.0.1:8765/`. A local server is preferable to opening the HTML as a `file:` URL because browsers may limit the GitHub API request from local files.

## Feature artwork

The feature tour uses five static PNGs from `media/features/`. Each image is built from the real WWRecorder interface rather than invented UI. The shared `backdrop.png` supplies consistent red-and-black framing while the desktop layout reserves 40% of every story for text and 60% for its image.

## Deployment

Upload or publish the contents of this `site` folder as the GitHub Pages repository root. No files from the parent `Supporting\Website` folder are required. No server runtime, package installation, database, secret or build command is required.

## Maintenance checklist

1. Keep application feature claims consistent with the current stable build.
2. Keep the Microsoft Store URL in `index.html` and `download.html` current.
3. Do not hard-code a prerelease installer into the primary download buttons.
4. Test all internal links, the release API fallback and responsive layouts before publishing.
5. Update the privacy and legal pages when application data handling or distribution changes.
6. Add the exact published release name, installer filename, and SHA-256 to `OFFICIAL_INSTALLER_RELEASES`, then test both a matching and non-matching value.
7. Keep the engineering page grounded in the current implementation. In particular, confirm capture source, timing filters, audio constants, recovery retention, and build inputs before changing technical claims.
8. Keep the home-page narrative in this order: purpose, workflow, product fit and boundaries, reliability, then download. Do not reintroduce duplicate feature grids or unrelated project promotion into the main page flow.

## Source and rights

The original WWRecorder application source is published at `https://github.com/akasumitlamba/WWRecorder` under the MIT License. Keep source links and license wording aligned with the repository's root `LICENSE`, `legal.html`, and this folder's `LICENSE` notice.

The application-source license does not grant rights to third-party components or permission to present an unofficial build as endorsed by WWRecorder.
