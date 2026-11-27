#Requires -Version 5.1
<#
.SYNOPSIS
    Installs Franca on this Windows PC (stories E01-011 and E01-012).

.DESCRIPTION
    The steps:
    1. WSL 2 is switched on, if it is not on yet. Windows may need a restart after this, and then the installer has to be run again.
    2. A Debian system called Franca is added to WSL, with systemd, so that Docker runs as a service in it.
    3. The Linux part of the installer (franca_install.py) is copied into it and given the owner's answers. It installs
       Docker Engine, writes the secrets and starts Franca.
    4. A scheduled task is added that starts the Franca system when the PC starts, before anyone signs in, and keeps it
       running. Sleep on mains power is switched off, so Franca stays reachable.
    5. The address, the backup password and the alert topic are shown once.

    Run it with Install-Franca.cmd, which asks for administrator rights. The answers are passed to the Linux part on
    its standard input, so that no secret appears in a command line.
#>
[CmdletBinding()]
param(
    [string] $DistroName = 'Franca',
    [string] $InstallRoot = $(if ($env:ProgramData) { Join-Path $env:ProgramData 'Franca' } else { 'Franca' })
)

Set-StrictMode -Version Latest
# The parameters are kept as script values, which the functions below use.
$FrancaDistro = $DistroName
$FrancaRoot = $InstallRoot
$ErrorActionPreference = 'Stop'

$LinuxInstallerFolder = '/opt/franca-installer'
$LinuxFiles = @('franca_install.py', 'franca_updater.py', 'compose.yaml')
$TaskName = 'Franca'

# The contents of /etc/wsl.conf in the Franca system. With systemd on, Docker runs as a service. The metadata option is
# needed so that the backup folder on disk J: can be given to the backup container's user. Windows programs are left out
# of the Linux path.
$WslConf = @'
[boot]
systemd = true

[automount]
options = "metadata,umask=022"

[interop]
appendWindowsPath = false

[user]
default = root
'@

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    return ([Security.Principal.WindowsPrincipal] $identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Invoke-Wsl {
    <#
    Runs wsl.exe with the arguments given, and stops with a message when it fails. Commands in the Franca system are
    run with -e, so that they are started directly and not through a shell, which would change backslashes and quotes.
    #>
    param([Parameter(Mandatory)] [string[]] $Arguments, [string] $InputText)
    if ($PSBoundParameters.ContainsKey('InputText')) {
        $output = $InputText | & wsl.exe @Arguments
    } else {
        $output = & wsl.exe @Arguments
    }
    if ($LASTEXITCODE -ne 0) {
        throw "wsl.exe $($Arguments[0..2] -join ' ') failed (exit code $LASTEXITCODE): $($output -join ' ')"
    }
    return $output
}

function Get-WslDistroName {
    <# The names of the WSL systems on this PC. wsl.exe writes UTF-16, which PowerShell reads with null characters. #>
    # With no systems yet, wsl.exe writes a message on the error output. Windows PowerShell 5.1 would stop on it.
    $ErrorActionPreference = 'Continue'
    $names = & wsl.exe --list --quiet 2>$null
    if ($LASTEXITCODE -ne 0) { return @() }
    return @($names | ForEach-Object { ($_ -replace "`0", '').Trim() } | Where-Object { $_ })
}

function Test-WslReady {
    $ErrorActionPreference = 'Continue'
    & wsl.exe --status *> $null
    return ($LASTEXITCODE -eq 0)
}

function ConvertTo-LinuxBackupPath {
    <# The backup folder on a Windows drive, as the Franca system sees it: J: becomes /mnt/j/franca-backups. #>
    param([Parameter(Mandatory)] [ValidatePattern('^[A-Za-z]$')] [string] $DriveLetter)
    return "/mnt/$($DriveLetter.ToLowerInvariant())/franca-backups"
}

function ConvertFrom-SecureText {
    param([Parameter(Mandatory)] [Security.SecureString] $Secure)
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
}

function New-AnswersJson {
    <# The answers for the Linux part, as one line of JSON. #>
    param(
        [Parameter(Mandatory)] [string] $OwnerEmail,
        [Parameter(Mandatory)] [string] $GoogleClientId,
        [Parameter(Mandatory)] [string] $GoogleClientSecret,
        # Empty when Franca is installed already: the Linux part then uses the saved Tailscale state.
        [Parameter(Mandatory)] [AllowEmptyString()] [string] $TailscaleAuthKey,
        [Parameter(Mandatory)] [string] $BackupDir,
        # Optional: the ping address of the owner's check on healthchecks.io. Empty keeps the saved address, or means no
        # heartbeat on a first installation. off switches the heartbeat off.
        [string] $HealthchecksPingUrl = ''
    )
    $answers = [ordered] @{
        owner_email           = $OwnerEmail.Trim()
        google_client_id      = $GoogleClientId.Trim()
        google_client_secret  = $GoogleClientSecret.Trim()
        tailscale_authkey     = $TailscaleAuthKey.Trim()
        backup_dir            = $BackupDir
        healthchecks_ping_url = $HealthchecksPingUrl.Trim()
    }
    return ($answers | ConvertTo-Json -Compress)
}

function Test-PingUrl {
    <#
    Whether an answer to the question about the healthchecks.io ping address can be used: empty (keep the saved address,
    or no heartbeat), off (switch the heartbeat off), or https://hc-ping.com/ followed by a check's id. The Linux part
    checks the answer with the same pattern.
    #>
    param([AllowEmptyString()] [string] $Answer)
    $trimmed = $Answer.Trim()
    return ($trimmed -eq '') -or ($trimmed -eq 'off') -or
        ($trimmed -cmatch '^https://hc-ping\.com/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
}

function Read-InstallSetting {
    <# Asks the owner the installer's questions. The secrets are typed without being shown. #>
    Write-Host ''
    Write-Host 'Franca needs a few answers. See docs/installing-franca.md for where to find each one.'
    $email = Read-Host 'Your e-mail address (the Google account you sign in with)'
    $clientId = Read-Host 'The Google client ID (it ends in .apps.googleusercontent.com)'
    $clientSecret = ConvertFrom-SecureText (Read-Host 'The Google client secret (it is not shown as you type)' -AsSecureString)
    $authKey = ConvertFrom-SecureText (Read-Host 'The Tailscale auth key (it is not shown as you type; if Franca is installed already, press Enter)' -AsSecureString)
    do {
        $drive = Read-Host 'The letter of the backup disk (press Enter for J)'
        if (-not $drive) { $drive = 'J' }
        $drive = $drive.TrimEnd(':')
        $ok = ($drive -match '^[A-Za-z]$') -and (Test-Path "$($drive):\")
        if (-not $ok) { Write-Host "Disk $($drive): was not found. Connect it, or type another letter." }
    } until ($ok)
    do {
        $pingUrl = ConvertFrom-SecureText (Read-Host 'The healthchecks.io ping address, for an alert when the PC is off (it is not shown as you type; press Enter to skip or to keep the saved one, or type off)' -AsSecureString)
        $ok = Test-PingUrl -Answer $pingUrl
        if (-not $ok) { Write-Host 'That is not a healthchecks.io ping address. Copy it again from the check''s page, or press Enter to skip.' }
    } until ($ok)
    return New-AnswersJson -OwnerEmail $email -GoogleClientId $clientId -GoogleClientSecret $clientSecret `
        -TailscaleAuthKey $authKey -BackupDir (ConvertTo-LinuxBackupPath -DriveLetter $drive) -HealthchecksPingUrl $pingUrl
}

function Install-FrancaDistro {
    <# Adds the Debian system called Franca to WSL, unless it is there already. #>
    if ((Get-WslDistroName) -contains $FrancaDistro) { return }
    Write-Host "Adding the $FrancaDistro system to WSL. Debian is downloaded, which takes a few minutes."
    New-Item -ItemType Directory -Force -Path (Join-Path $FrancaRoot 'wsl') | Out-Null
    Invoke-Wsl -Arguments @('--set-default-version', '2') | Out-Null
    Invoke-Wsl -Arguments @('--install', 'Debian', '--name', $FrancaDistro, '--location', (Join-Path $FrancaRoot 'wsl'), '--no-launch', '--web-download') | Out-Null
}

function Initialize-FrancaDistro {
    <# Writes /etc/wsl.conf, restarts the system so systemd runs, and installs Python, which the Linux part needs. #>
    # PowerShell ends each line it pipes to a program with a carriage return, which tr removes.
    Invoke-Wsl -Arguments @('-d', $FrancaDistro, '-u', 'root', '-e', 'sh', '-c', "tr -d '\r' > /etc/wsl.conf") -InputText $WslConf | Out-Null
    Invoke-Wsl -Arguments @('--terminate', $FrancaDistro) | Out-Null
    Invoke-Wsl -Arguments @('-d', $FrancaDistro, '-u', 'root', '-e', 'sh', '-c', 'apt-get update && apt-get install -y python3 ca-certificates curl') | Out-Null
}

function Copy-LinuxInstaller {
    <# Copies the Linux part of the installer, the updater and compose.yaml into the Franca system. #>
    $here = (Invoke-Wsl -Arguments @('-d', $FrancaDistro, '-u', 'root', '-e', 'wslpath', '-a', $PSScriptRoot)) | Select-Object -First 1
    Invoke-Wsl -Arguments @('-d', $FrancaDistro, '-u', 'root', '-e', 'install', '-d', '-m', '0700', $LinuxInstallerFolder) | Out-Null
    foreach ($file in $LinuxFiles) {
        Invoke-Wsl -Arguments @('-d', $FrancaDistro, '-u', 'root', '-e', 'install', '-m', '0600', "$here/$file", "$LinuxInstallerFolder/$file") | Out-Null
    }
}

function Register-FrancaStartup {
    <#
    Adds the scheduled task that starts the Franca system when the PC starts, before anyone signs in. The task keeps
    the system running. systemd in it starts Docker, and Docker starts Franca's containers. The task runs as the owner,
    because WSL systems belong to a Windows user, and with S4U, so that no password is stored.
    #>
    $user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $action = New-ScheduledTaskAction -Execute 'wsl.exe' -Argument "-d $FrancaDistro -u root -e sleep infinity"
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType S4U -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings `
        -Description 'Starts Franca when the PC starts, and keeps it running.' -Force | Out-Null
    Start-ScheduledTask -TaskName $TaskName
}

function Disable-SleepOnMainsPower {
    <# Franca has to be reachable at any time, so the PC does not sleep or hibernate while it is on mains power. #>
    & powercfg.exe /change standby-timeout-ac 0
    & powercfg.exe /change hibernate-timeout-ac 0
}

function Show-Result {
    param([Parameter(Mandatory)] [string] $ResultJson)
    $result = $ResultJson | ConvertFrom-Json
    Write-Host ''
    Write-Host 'Franca is installed.' -ForegroundColor Green
    Write-Host ''
    Write-Host "Address: $($result.address)"
    Write-Host 'Open it on your phone or laptop with Tailscale connected.'
    if ($result.PSObject.Properties.Name -contains 'backup_password') {
        Write-Host ''
        Write-Host "Backup password: $($result.backup_password)" -ForegroundColor Yellow
        Write-Host 'Save it in your password manager now. It is not shown again, and without it the backups cannot be read.'
    }
    if ($result.PSObject.Properties.Name -contains 'ntfy_topic') {
        Write-Host ''
        Write-Host "Alert topic: $($result.ntfy_topic)" -ForegroundColor Yellow
        Write-Host 'In the ntfy app on your phone, subscribe to this topic. A test alert has been sent to it.'
    }
    Write-Host ''
    Write-Host 'Next: add the address to your Google sign-in client, as described in step 13 of docs/installing-franca.md.'
}

function Install-Franca {
    if (-not (Test-Administrator)) { throw 'Start the installer with Install-Franca.cmd, so that it has administrator rights.' }
    if (-not (Test-WslReady)) {
        Write-Host 'Switching on WSL. When the installer has finished, restart the PC and run it again.'
        Invoke-Wsl -Arguments @('--install', '--no-distribution') | Out-Null
        return
    }
    Invoke-Wsl -Arguments @('--update') | Out-Null
    Install-FrancaDistro
    Initialize-FrancaDistro
    Copy-LinuxInstaller
    $answers = Read-InstallSetting
    Write-Host ''
    Write-Host 'Installing Docker and starting Franca. This takes 10 to 20 minutes.'
    $previousEncoding = $OutputEncoding
    $OutputEncoding = [Text.UTF8Encoding]::new($false)
    try {
        $output = Invoke-Wsl -Arguments @('-d', $FrancaDistro, '-u', 'root', '-e', 'python3', "$LinuxInstallerFolder/franca_install.py") -InputText $answers
    } finally {
        $OutputEncoding = $previousEncoding
        $answers = $null
    }
    Register-FrancaStartup
    Disable-SleepOnMainsPower
    Show-Result -ResultJson (@($output) | Select-Object -Last 1)
}

if ($MyInvocation.InvocationName -ne '.') {
    try {
        Install-Franca
    } catch {
        Write-Host ''
        Write-Host "The installation stopped: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host 'Nothing on the PC was removed. Fix the problem and run the installer again.'
        exit 1
    }
}
