# Dot-source this in each local terminal: . ./scripts/dev-env.ps1
# Generates machine-local credentials once; never prints credential values.
$afterSaleRoot = Split-Path -Parent $PSScriptRoot
$afterSaleEnvFile = Join-Path $afterSaleRoot '.env'
if (-not (Test-Path -LiteralPath $afterSaleEnvFile)) {
    $afterSaleRng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $afterSaleHmacBytes = New-Object byte[] 32
        $afterSaleAgentBytes = New-Object byte[] 32
        $afterSaleRng.GetBytes($afterSaleHmacBytes)
        $afterSaleRng.GetBytes($afterSaleAgentBytes)
        $afterSaleHmac = [Convert]::ToBase64String($afterSaleHmacBytes)
        $afterSaleAgent = [Convert]::ToBase64String($afterSaleAgentBytes)
        $afterSaleLines = @(
            '# Machine-local settings; ignored by Git. Do not share this file.'
            "APP_HMAC_SECRET=$afterSaleHmac"
            "APP_AGENT_TOKEN=$afterSaleAgent"
            "AFTERSALE_HMAC_SECRET=$afterSaleHmac"
            'APP_AGENT_BASE_URL=http://127.0.0.1:8000'
            'AFTERSALE_JAVA_BASE_URL=http://127.0.0.1:8080'
            'JAVA_PROXY_TARGET=http://127.0.0.1:8080'
        )
        # CreateNew preserves a file created concurrently in another terminal.
        $afterSaleStream = [IO.File]::Open($afterSaleEnvFile, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
        try {
            $afterSaleBytes = [Text.Encoding]::UTF8.GetBytes(($afterSaleLines -join "`n") + "`n")
            $afterSaleStream.Write($afterSaleBytes, 0, $afterSaleBytes.Length)
        } finally { $afterSaleStream.Dispose() }
    } finally {
        $afterSaleRng.Dispose()
        Remove-Variable afterSaleHmac,afterSaleAgent,afterSaleHmacBytes,afterSaleAgentBytes,afterSaleLines,afterSaleBytes -ErrorAction SilentlyContinue
    }
}
foreach ($afterSaleLine in [IO.File]::ReadAllLines($afterSaleEnvFile)) {
    if ($afterSaleLine -match '^\s*(APP_HMAC_SECRET|APP_AGENT_TOKEN|AFTERSALE_HMAC_SECRET|APP_AGENT_BASE_URL|AFTERSALE_JAVA_BASE_URL|JAVA_PROXY_TARGET|DB_HOST|DB_PORT|DB_NAME|DB_USER|DB_PASSWORD)=(.*)$') {
        [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], 'Process')
    }
}
Remove-Variable afterSaleLine -ErrorAction SilentlyContinue
Write-Host 'Local development settings loaded. Credential values are hidden.'
