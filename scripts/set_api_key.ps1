$ErrorActionPreference = 'Stop'
$secretInput = Read-Host 'OpenAI API Key (hidden input)' -AsSecureString
$secretPointer = [IntPtr]::Zero
try {
    $secretPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secretInput)
    $apiSecret = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($secretPointer)
    if ([string]::IsNullOrWhiteSpace($apiSecret) -or $apiSecret -match '\s' -or -not $apiSecret.StartsWith('sk-') -or $apiSecret.Length -lt 24) {
        throw 'Input appears incomplete. Copy the complete key locally and try again.'
    }
    [Environment]::SetEnvironmentVariable('OPENAI_API_KEY', $apiSecret, 'User')
    Write-Host 'Saved to this Windows user environment. Reopen the terminal or Codex. Key not printed or written to project.'
} finally {
    if ($secretPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($secretPointer)
    }
    $apiSecret = $null
    if ($secretInput) { $secretInput.Dispose() }
}
