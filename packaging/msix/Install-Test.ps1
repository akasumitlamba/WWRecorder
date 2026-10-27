[CmdletBinding()]
param([switch]$TrustCertificateOnly)
$ErrorActionPreference = 'Stop'
try {
    $certPath = Join-Path $PSScriptRoot 'WWRecorder-Test.cer'
    $certificate = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($certPath)
    if ($certificate.Subject -ne 'CN=WWRecorder Local Testing') { throw 'Unexpected certificate subject.' }
    if ($TrustCertificateOnly) {
        Import-Certificate -FilePath $certPath -CertStoreLocation Cert:\LocalMachine\TrustedPeople | Out-Null
        exit 0
    }
    $packages = @(Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*_local-test.msix')
    if ($packages.Count -ne 1) { throw 'Keep exactly one local-test MSIX beside this installer script.' }
    $signature = Get-AuthenticodeSignature -LiteralPath $packages[0].FullName
    if (-not $signature.SignerCertificate -or $signature.SignerCertificate.Thumbprint -ne $certificate.Thumbprint) { throw 'The MSIX signature does not match the supplied test certificate.' }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::OpenRead($packages[0].FullName)
    try {
        $entry = $archive.GetEntry('AppxManifest.xml')
        if (-not $entry) { throw 'The package manifest is missing.' }
        $reader = [System.IO.StreamReader]::new($entry.Open())
        try { [xml]$manifest = $reader.ReadToEnd() } finally { $reader.Dispose() }
    } finally { $archive.Dispose() }
    $identity = $manifest.Package.Identity
    if ($identity.Name -ne 'WWRecorder.LocalTest' -or $identity.Publisher -ne $certificate.Subject) { throw 'Unexpected local-test package identity.' }
    $installed = Get-AppxPackage -Name $identity.Name | Where-Object { $_.Publisher -eq $identity.Publisher }
    $skipDeployment = $installed -and ([version]$installed.Version -ge [version]$identity.Version)
    if ($skipDeployment) {
        Write-Host "Version $($installed.Version) is already installed; keeping it instead of deploying $($identity.Version). Your settings and recordings are unchanged."
    }
    $trusted = Test-Path "Cert:\LocalMachine\TrustedPeople\$($certificate.Thumbprint)"
    if (-not $skipDeployment -and -not $trusted) {
        Write-Host 'Windows will ask permission to trust this local test certificate. The app itself installs for your current account.'
        $arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $PSCommandPath + '" -TrustCertificateOnly'
        $process = Start-Process powershell.exe -ArgumentList $arguments -Verb RunAs -WindowStyle Hidden -Wait -PassThru
        if ($process.ExitCode -ne 0) { throw 'Test certificate trust was not installed.' }
    }
    if (-not $skipDeployment) { Add-AppxPackage -Path $packages[0].FullName }
    $installed = Get-AppxPackage -Name 'WWRecorder.LocalTest'
    if (-not $installed) { throw 'Windows did not register the test package for this account.' }
    if (Get-Process WWRecorder -ErrorAction SilentlyContinue) {
        Write-Host 'Installed. WWRecorder is already running. Quit it from the tray, then open WWRecorder (MSIX Test) from Start.'
    } else {
        Write-Host 'Installed. Launching WWRecorder (MSIX Test)... Look for the edge dock and system-tray icon.'
        Start-Process explorer.exe -ArgumentList ('shell:AppsFolder\' + $installed.PackageFamilyName + '!WWRecorder') -WindowStyle Hidden
    }
    Write-Host "Test certificate thumbprint: $($certificate.Thumbprint)"
} catch {
    Write-Error $_
    exit 1
}
