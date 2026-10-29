# Enterprise deployment and data handling

## Approved delivery

Use the production Microsoft Store product **9PBS5VDWFXND**, identity
`akasumitlamba.WWRecorder`, after IT validates its availability, version and
publisher trust. The direct-download EXE is unsigned. `WWRecorder.LocalTest`
and its certificate-import kit are testing artifacts, not enterprise publisher
assurance. Store certification/publication cannot be inferred from a test MSIX.
Run the application as the ordinary user; no capture feature requires launching
WWRecorder as administrator. EXE/MSIX share recording and editing behavior.

## Optional managed restrictions

Create DWORD values under the **64-bit** machine key
`HKLM\SOFTWARE\Policies\WWRecorder`:

| Name | Value 1 | Absent / zero |
|---|---|---|
| DisableKeycast | Blocks Keycast activation; also checked before starting hooks | Existing user-controlled Keycast |
| DisableAutomaticClipboard | Stops automatic copying after captures and player frame screenshots | Existing user preference/behavior |

Deploy through the organization's approved registry/MDM mechanism and restart
the app. Ordinary users should not have write access to that machine policy key.
Manual Copy is a distinct explicit user action. Endpoint clipboard/history/sync,
remote-desktop redirection and DLP policy must cover manual use as appropriate.
Keycast's consent is disclosure, not automatic password detection or masking.

## Files and confidentiality

Default media destination is the user's Videos/WWRecorder directory. Users can
select a different destination. Captures are ordinary PNG/MKV files. Recording
recovery media is in `.wwr_temp` on the selected output drive; hiding that folder
does not encrypt it or create an access-control boundary. Apply approved Windows
user/share ACLs and disk encryption to both completed and recovery files. Decide
whether synchronized folders and network shares are appropriate before allowing
them. The application is full-trust and is not an AppContainer sandbox.

Finished recordings remain until explicitly deleted or storage policy removes
them. Failed finalization retains recoverable media. Existing prefix-scoped
cleanup covers eligible recorder temporary media older than seven days in the
temp roots scanned; it is not an inventory of every historical output location.
Do not promise secure erasure from SSDs, backups, snapshots or cloud providers.
Do not shorten recovery retention without an approved recovery/privacy decision.

EXE settings/logs: `%APPDATA%\WWRecorder`. MSIX uses its package-private
LocalState/WWRecorder directory. Python exception logs rotate at 2 MiB with
three backups. Native crash diagnostics rotate on the next launch at 2 MiB
with one backup. Logs can contain paths/usernames/error context; restrict access
and remove sensitive details before forwarding them outside the organization.
Keycast does not add a separate file of typed input. Its visible pixels can be
part of a recording, including input into windows outside the selected area.

## Network and updates

EXE update checks use official GitHub HTTPS endpoints; EXE installer downloads
validate official release asset size/digest and staging integrity. MSIX never
uses that EXE updater; Windows Store is its update authority. Browser links,
clipboard consumers and user-selected cloud/share destinations have their own
network behavior. No claim is made that all workflows are network-free.

## Validation and operations

Keep the submitted installer hashes, security-evidence folder and exact source
revision with the approval record. Evaluate native/static components as well as
Python package advisories. Maintain a patch owner and review new advisories
before release; the automated build gate blocks known PyPI findings and native
hash drift but does not replace vendor/native analysis.

Before broad deployment, test standard-user installation/upgrade/uninstall,
file/config/temp/log permissions and reparse points, decoder loading, physical
capture/audio, proxy/denied-egress behavior, clipboard/DLP, disk-full/crash
recovery and Store signing/delivery. Save or discard work and quit before
uninstalling; uninstall must not force-kill an active recording. Retain both
installed-edition QA even when the enterprise chooses Store delivery only.
