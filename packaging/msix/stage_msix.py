"""Stage a frozen desktop payload; never package the Inno installer itself."""
import argparse
import json
import re
import shutil
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr
from PIL import Image
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shared"))
from build_icon_assets import render_icon, TARGET_SIZES


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--identity", type=Path, required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    identity = json.loads(args.identity.read_text(encoding="utf-8-sig"))
    if not re.fullmatch(r"[A-Za-z0-9.-]{3,50}", identity["name"]):
        raise ValueError("Invalid MSIX package name")
    if identity["channel"] not in ("store", "local-test"):
        raise ValueError("Unknown distribution channel")
    if identity["channel"] == "store" and any(
        not identity.get(k) or "REPLACE" in identity[k]
        for k in ("name", "publisher", "store_product_id")
    ):
        raise ValueError("Store packaging requires confirmed MSIX Partner Center identity")
    if not re.fullmatch(r"[1-9]\d*\.\d+\.\d+\.\d+", args.version) or any(int(v) > 65535 for v in args.version.split(".")):
        raise ValueError("Use a valid four-part package version")
    if identity["channel"] == "store" and args.version.split(".")[-1] != "0":
        raise ValueError("Store package versions must end in .0; revisions are for local testing only")
    if not (args.payload / "WWRecorder.exe").is_file():
        raise FileNotFoundError("Build the shared PyInstaller payload first")
    # The caller supplies a fresh unique directory: stale files never leak in.
    shutil.copytree(args.payload, args.stage)
    (args.stage / "distribution.json").write_text(json.dumps(identity, indent=2), encoding="utf-8")
    assets = args.stage / "Assets"
    assets.mkdir()
    icon = Image.open(Path(__file__).resolve().parents[1] / "shared" / "icon-source.png").convert("RGBA")
    for name, size in (("StoreLogo", 50), ("Square44x44Logo", 44), ("Square150x150Logo", 150)):
        render_icon(icon, size).save(assets / f"{name}.png")
    for size in TARGET_SIZES:
        for suffix in ("", "_altform-unplated", "_altform-lightunplated"):
            render_icon(icon, size).save(assets / f"Square44x44Logo.targetsize-{size}{suffix}.png")
    manifest = f'''<?xml version="1.0" encoding="utf-8"?>
<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
 xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10"
 xmlns:desktop="http://schemas.microsoft.com/appx/manifest/desktop/windows10"
 xmlns:rescap="http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"
 IgnorableNamespaces="uap desktop rescap">
 <Identity Name={quoteattr(identity['name'])} Publisher={quoteattr(identity['publisher'])}
  Version={quoteattr(args.version)} ProcessorArchitecture="x64"/>
 <Properties>
  <DisplayName>{escape(identity['display_name'])}</DisplayName>
  <PublisherDisplayName>{escape(identity['publisher_display_name'])}</PublisherDisplayName>
  <Logo>Assets\\StoreLogo.png</Logo>
 </Properties>
 <Resources><Resource Language="en-us"/></Resources>
 <Dependencies><TargetDeviceFamily Name="Windows.Desktop" MinVersion="10.0.19041.0" MaxVersionTested="10.0.26100.0"/></Dependencies>
 <Applications>
  <Application Id="WWRecorder" Executable="WWRecorder.exe" EntryPoint="Windows.FullTrustApplication">
   <uap:VisualElements DisplayName={quoteattr(identity['display_name'])}
    Description="Screen recording, screenshots and annotation"
    BackgroundColor="transparent" Square150x150Logo="Assets\\Square150x150Logo.png"
    Square44x44Logo="Assets\\Square44x44Logo.png"/>
   <Extensions>
    <desktop:Extension Category="windows.startupTask" Executable="WWRecorder.exe" EntryPoint="Windows.FullTrustApplication">
     <desktop:StartupTask TaskId="WWRecorderStartup" Enabled="false" DisplayName={quoteattr(identity['display_name'])}/>
    </desktop:Extension>
   </Extensions>
  </Application>
 </Applications>
 <Capabilities><rescap:Capability Name="runFullTrust"/></Capabilities>
</Package>
'''
    (args.stage / "AppxManifest.xml").write_text(manifest, encoding="utf-8")


if __name__ == "__main__":
    main()
