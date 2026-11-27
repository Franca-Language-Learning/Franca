# Tests for the parts of the Windows installer that do not need Windows (story E01-011). Run with Pester 5:
#   pwsh -c "Invoke-Pester installer/windows/tests"
BeforeAll {
    . (Join-Path $PSScriptRoot '..' 'Install-Franca.ps1')
}

Describe 'ConvertTo-LinuxBackupPath' {
    It 'gives the backup folder on the drive as the Franca system sees it' {
        ConvertTo-LinuxBackupPath -DriveLetter 'J' | Should -Be '/mnt/j/franca-backups'
    }
    It 'refuses something that is not a drive letter' {
        { ConvertTo-LinuxBackupPath -DriveLetter 'J:\' } | Should -Throw
    }
}

Describe 'New-AnswersJson' {
    It 'gives one line of JSON with the names the Linux part reads' {
        $json = New-AnswersJson -OwnerEmail ' owner@example.org ' -GoogleClientId '1-a.apps.googleusercontent.com' `
            -GoogleClientSecret 'GOCSPX-x' -TailscaleAuthKey 'tskey-auth-test' -BackupDir '/mnt/j/franca-backups'
        $json | Should -Not -Match "`n"
        $answers = $json | ConvertFrom-Json
        $answers.owner_email | Should -Be 'owner@example.org'
        $answers.google_client_id | Should -Be '1-a.apps.googleusercontent.com'
        $answers.google_client_secret | Should -Be 'GOCSPX-x'
        $answers.tailscale_authkey | Should -Be 'tskey-auth-test'
        $answers.backup_dir | Should -Be '/mnt/j/franca-backups'
    }
    It 'gives an empty heartbeat address when none is given' {
        $json = New-AnswersJson -OwnerEmail 'a@b.c' -GoogleClientId 'x' -GoogleClientSecret 's' -TailscaleAuthKey 'k' -BackupDir '/mnt/j/x'
        ($json | ConvertFrom-Json).healthchecks_ping_url | Should -Be ''
    }
    It 'passes the heartbeat address on without spaces around it' {
        $json = New-AnswersJson -OwnerEmail 'a@b.c' -GoogleClientId 'x' -GoogleClientSecret 's' -TailscaleAuthKey 'k' `
            -BackupDir '/mnt/j/x' -HealthchecksPingUrl ' https://hc-ping.com/abc '
        ($json | ConvertFrom-Json).healthchecks_ping_url | Should -Be 'https://hc-ping.com/abc'
    }
    It 'keeps quotes and backslashes in a secret intact' {
        $json = New-AnswersJson -OwnerEmail 'a@b.c' -GoogleClientId 'x' -GoogleClientSecret 'a"b\c' -TailscaleAuthKey 'k' -BackupDir '/mnt/j/x'
        ($json | ConvertFrom-Json).google_client_secret | Should -Be 'a"b\c'
    }
}

Describe 'The wsl.conf of the Franca system' {
    It 'switches on systemd, so Docker runs as a service' {
        $WslConf | Should -Match '(?m)^\[boot\]\s*\r?\nsystemd = true'
    }
    It 'lets files on Windows drives have Linux owners, for the backup folder' {
        $WslConf | Should -Match 'options = "metadata'
    }
}

Describe 'The files copied into the Franca system' {
    It 'are all in the installer package' {
        $LinuxFiles | Should -Be @('franca_install.py', 'franca_updater.py', 'compose.yaml')
    }
}

Describe 'Commands in the Franca system' {
    BeforeAll {
        $script:Text = Get-Content -Raw (Join-Path $PSScriptRoot '..' 'Install-Franca.ps1')
    }
    It 'are started with -e, so that no shell changes the backslashes in Windows paths' {
        $script:Text | Should -Not -Match "'-u', 'root', '--'"
        $script:Text | Should -Match "-u root -e sleep infinity"
    }
    It 'write wsl.conf without the carriage returns that PowerShell adds' {
        $script:Text | Should -Match "tr -d '\\r' > /etc/wsl.conf"
    }
}
