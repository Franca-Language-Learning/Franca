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
    It 'accepts an empty Tailscale auth key, for a later run' {
        $json = New-AnswersJson -OwnerEmail 'a@b.c' -GoogleClientId 'x' -GoogleClientSecret 's' -TailscaleAuthKey '' -BackupDir '/mnt/j/x'
        ($json | ConvertFrom-Json).tailscale_authkey | Should -Be ''
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

Describe 'Test-PingUrl' {
    It 'accepts the ping address of a check on healthchecks.io' {
        Test-PingUrl -Answer 'https://hc-ping.com/0f5a7c2e-1b3d-4e8f-9a6b-2c4d6e8f0a1b' | Should -BeTrue
    }
    It 'accepts an empty answer and off' {
        Test-PingUrl -Answer '' | Should -BeTrue
        Test-PingUrl -Answer 'off' | Should -BeTrue
    }
    It 'refuses another host' {
        Test-PingUrl -Answer 'https://example.org/0f5a7c2e-1b3d-4e8f-9a6b-2c4d6e8f0a1b' | Should -BeFalse
    }
    It 'refuses an address with a query' {
        Test-PingUrl -Answer 'https://hc-ping.com/0f5a7c2e-1b3d-4e8f-9a6b-2c4d6e8f0a1b?x=1' | Should -BeFalse
    }
}

Describe 'Read-InstallSetting' {
    BeforeAll {
        function script:New-TestSecureString([string] $Text) {
            $secure = [Security.SecureString]::new()
            foreach ($character in $Text.ToCharArray()) { $secure.AppendChar($character) }
            return $secure
        }
    }
    BeforeEach {
        $script:PingAnswers = [Collections.Generic.Queue[string]]::new()
        Mock Write-Host {}
        Mock Test-Path { $true }
        Mock Read-Host { 'owner@example.org' } -ParameterFilter { $Prompt -like '*e-mail*' }
        Mock Read-Host { '1-a.apps.googleusercontent.com' } -ParameterFilter { $Prompt -like '*client ID*' }
        Mock Read-Host { New-TestSecureString 'GOCSPX-x' } -ParameterFilter { $Prompt -like '*client secret*' }
        Mock Read-Host { New-TestSecureString 'tskey-auth-test' } -ParameterFilter { $Prompt -like '*Tailscale*' }
        Mock Read-Host { '' } -ParameterFilter { $Prompt -like '*backup disk*' }
        Mock Read-Host { New-TestSecureString $script:PingAnswers.Dequeue() } -ParameterFilter { $Prompt -like '*healthchecks.io*' }
    }
    It 'passes the ping address on' {
        $script:PingAnswers.Enqueue('https://hc-ping.com/0f5a7c2e-1b3d-4e8f-9a6b-2c4d6e8f0a1b')
        $answers = Read-InstallSetting | ConvertFrom-Json
        $answers.healthchecks_ping_url | Should -Be 'https://hc-ping.com/0f5a7c2e-1b3d-4e8f-9a6b-2c4d6e8f0a1b'
        $answers.backup_dir | Should -Be '/mnt/j/franca-backups'
    }
    It 'gives an empty ping address when the question is skipped' {
        $script:PingAnswers.Enqueue('')
        (Read-InstallSetting | ConvertFrom-Json).healthchecks_ping_url | Should -Be ''
    }
    It 'asks again after an answer that is not a ping address' {
        $script:PingAnswers.Enqueue('https://example.org/x')
        $script:PingAnswers.Enqueue('off')
        (Read-InstallSetting | ConvertFrom-Json).healthchecks_ping_url | Should -Be 'off'
        Should -Invoke Read-Host -Times 2 -Exactly -ParameterFilter { $Prompt -like '*healthchecks.io*' }
    }
}
