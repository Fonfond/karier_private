# Smoke-тест Спринта 1: доступ, роли, аудит.
# Запуск (сервер поднят на 8001):
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\smoke.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\smoke.ps1 -TotpSecret <секрет из seed.py>

param(
    [string]$BaseUrl = 'http://127.0.0.1:8001',
    [string]$TotpSecret = 'VIKFSSCEEHU4M2CQCPAQYCZAMMUYCZIH',
    [string]$Python = 'C:\karier\backend-v2\venv\Scripts\python.exe'
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$script:passed = 0
$script:failed = 0
$script:lines = New-Object System.Collections.Generic.List[string]

function Step($name, $ok, $extra = '') {
    $mark = if ($ok) { '[OK]  ' } else { '[FAIL]' }
    if ($ok) { $script:passed++ } else { $script:failed++ }
    $line = "  $mark $name $extra"
    $script:lines.Add($line)
    Write-Output $line
}

function Section($title) {
    $line = "`n=== $title ==="
    $script:lines.Add($line)
    Write-Output $line
}

function PostJson($url, $body, $session, $token) {
    $headers = @{}
    if ($token) { $headers['Authorization'] = "Bearer $token" }
    $params = @{
        Uri         = "$BaseUrl$url"
        Method      = 'Post'
        ContentType = 'application/json; charset=utf-8'
        Body        = ($body | ConvertTo-Json -Depth 6)
        Headers     = $headers
    }
    if ($session) { $params['WebSession'] = $session }
    Invoke-RestMethod @params
}

function GetJson($url, $token, $session) {
    $params = @{ Uri = "$BaseUrl$url"; Method = 'Get' }
    if ($token) { $params['Headers'] = @{ Authorization = "Bearer $token" } }
    if ($session) { $params['WebSession'] = $session }
    Invoke-RestMethod @params
}

function ExpectStatus($name, [int]$expected, [scriptblock]$action, $extra = '') {
    try {
        $null = & $action
        Step $name ($expected -lt 400) "код $expected $extra"
    } catch {
        $code = 0
        if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode }
        Step $name ($code -eq $expected) "ожидали $expected, получили $code $extra"
    }
}

function ResetFixtures {
    # Приводим тестовые данные к исходному состоянию, чтобы скрипт можно
    # было запускать многократно: 000003 перерегистрируется, 000004 создаётся заново
    $env:PGPASSWORD = 'Df492357816'
    $sql = @"
delete from auth.credentials where employee_id in (select id from auth.employees where tab_no = '000003');
delete from auth.mfa_factors where employee_id in (select id from auth.employees where tab_no = '000003');
delete from auth.employees where tab_no = '000004';
update auth.mfa_factors set last_counter = null
 where employee_id in (select id from auth.employees where tab_no = '000002');
select 'reset' as status;
"@
    $out = & psql -h 127.0.0.1 -U karier_user -d karier_db -tAc $sql 2>&1
    Step 'тестовые данные сброшены' (($out | Out-String) -match 'reset')
}

Section '0. Подготовка тестовых данных'
ResetFixtures

try {
Section '1. Сервис'
$health = GetJson '/api/health/ready'
Step 'health/ready' ($health.status -eq 'ok' -and $health.database -eq 'ok')

Section '2. Вход администратора (без 2FA)'
$sAdmin = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$admin = PostJson '/api/auth/login' @{ tab_no = '000001'; password = 'admin' } $sAdmin
Step 'вход 000001/admin' ([bool]$admin.access_token -and -not $admin.mfa_required)
Step 'пароль помечен временным' ($admin.user.must_change_password -eq $true)
$adminToken = $admin.access_token

$me = GetJson '/api/me' $adminToken
Step 'GET /api/me' ($me.role -eq 'admin' -and $me.tab_no -eq '000001') "роль=$($me.role), прав=$($me.permissions.Count)"

Section '3. Закрытая регистрация 000003'
$start = PostJson '/api/auth/register/start' @{ tab_no = '000003' }
Step 'код отправлен' ($start.next_step -eq 'code_sent')
Step 'код виден в dev-ответе' ([bool]$start.debug_code)

$verify = PostJson '/api/auth/register/verify' @{ tab_no = '000003'; code = $start.debug_code }
Step 'код принят' ([bool]$verify.setup_token)

$sReg = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$done = PostJson '/api/auth/register/complete' @{ setup_token = $verify.setup_token; password = 'Obhodchik-2026' } $sReg
Step 'пароль установлен, вход выполнен' ([bool]$done.access_token -and $done.user.tab_no -eq '000003')

$regMe = GetJson '/api/me' $done.access_token
Step 'роль зарегистрированного — operator' ($regMe.role -eq 'operator')

$sSecond = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$again = PostJson '/api/auth/register/start' @{ tab_no = '000003' } $sSecond
Step 'повторная регистрация не выдаёт код' ($again.next_step -eq 'already_registered')

Section '4. Вход оператора с 2FA'
$sOp = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$op = PostJson '/api/auth/login' @{ tab_no = '000002'; password = 'operator123' } $sOp
Step 'требуется второй фактор' ($op.mfa_required -eq $true -and [bool]$op.challenge_token)

$code = (& $Python -c "import pyotp; print(pyotp.TOTP('$TotpSecret').now())").Trim()
Step 'TOTP-код получен' ($code.Length -eq 6) "код=$code"

$opTokens = PostJson '/api/auth/mfa/verify' @{ challenge_token = $op.challenge_token; code = $code } $sOp
Step '2FA подтверждена, вход выполнен' ([bool]$opTokens.access_token)
$opMe = GetJson '/api/me' $opTokens.access_token
Step 'роль оператора, 2FA включена' ($opMe.role -eq 'operator' -and $opMe.mfa_enabled -eq $true)

Section '5. Разграничение прав (сервер, не UI)'
ExpectStatus 'оператору запрещён список сотрудников' 403 { GetJson '/api/employees' $opTokens.access_token }
ExpectStatus 'оператору запрещён журнал аудита' 403 { GetJson '/api/audit' $opTokens.access_token }

Section '6. Администрирование'
$created = PostJson '/api/employees' @{
    tab_no = '000004'; full_name = 'Тестов Тест Тестович'; position = 'Электромонтёр'
    role = 'operator'; otp_channel = 'telegram'; telegram_id = 100000004
} $null $adminToken
Step 'сотрудник 000004 создан' ($created.tab_no -eq '000004' -and $created.status -eq 'active')

ExpectStatus 'дубликат табельного отклонён' 409 {
    PostJson '/api/employees' @{ tab_no = '000004'; full_name = 'Дубль Дубль Дубльевич' } $null $adminToken
}

$reset = PostJson "/api/employees/$($created.id)/reset-password" @{} $null $adminToken
Step 'пароль сброшен (выдан временный)' ($reset.temp_password.Length -gt 8) "temp=$($reset.temp_password)"

Section '7. Блокировки и лимиты'
$sLock = New-Object Microsoft.PowerShell.Commands.WebRequestSession
for ($i = 1; $i -le 5; $i++) {
    try { $null = PostJson '/api/auth/login' @{ tab_no = '000004'; password = 'wrong-password' } $sLock } catch { }
}
ExpectStatus 'после 5 неудач — блокировка 423' 423 {
    PostJson '/api/auth/login' @{ tab_no = '000004'; password = 'wrong-password' } $sLock
}

Section '8. Обновление токена и выход'
$refreshed = PostJson '/api/auth/refresh' @{} $sAdmin
Step 'refresh по cookie выдал новый access' ([bool]$refreshed.access_token)
$null = PostJson '/api/auth/logout' @{} $sAdmin
ExpectStatus 'после выхода refresh отклонён' 401 { PostJson '/api/auth/refresh' @{} $sAdmin }

Section '9. Журнал аудита'
$audit = GetJson '/api/audit?limit=100' $adminToken
Step 'журнал доступен' ($audit.total -gt 0) "записей=$($audit.total)"
$actions = (($audit.items | Select-Object -ExpandProperty action -Unique) -join ', ')
Step 'есть отказы в доступе' (($audit.items | Where-Object { $_.result -eq 'denied' }).Count -gt 0)

Section '10. Защита журнала от изменения'
$env:PGPASSWORD = 'Df492357816'
$prevErrorAction = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
$tryUpdate = & psql -h 127.0.0.1 -U karier_user -d karier_db -tAc "update audit.audit_log set result='hacked' where id=(select max(id) from audit.audit_log);" 2>&1
$ErrorActionPreference = $prevErrorAction
Step 'UPDATE audit_log запрещён триггером' (($tryUpdate | Out-String) -match 'append-only')
} catch {
    Step "НЕОЖИДАННАЯ ОШИБКА: $($_.Exception.Message)" $false
}

$summary = @(
    '',
    '----------------------------------------',
    ("  Успешно: " + $script:passed + "   Провалов: " + $script:failed),
    ("  События: " + $actions),
    '----------------------------------------'
) -join "`n"
Write-Output $summary

$script:lines | Out-File -FilePath (Join-Path $PSScriptRoot 'smoke-result.txt') -Encoding UTF8
