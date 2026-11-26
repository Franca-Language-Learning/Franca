# Settings for PSScriptAnalyzer, which checks the Windows installer in the pipeline (story E01-011).
@{
    Severity     = @('Error', 'Warning')
    ExcludeRules = @(
        # The installer talks to the owner in the console, so Write-Host is the right command for its messages.
        'PSAvoidUsingWriteHost',
        # The installer is run once by the owner, with no -WhatIf; the functions that change the PC are its steps.
        'PSUseShouldProcessForStateChangingFunctions'
    )
}
