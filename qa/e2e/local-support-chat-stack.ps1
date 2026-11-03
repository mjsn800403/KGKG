# Local, throwaway stack for qa/e2e/tests/support-chat.spec.js (Windows PowerShell).
#
# Nothing here touches a shared, staging or production database: it creates its
# own SQLite file under -StackDir, runs Django with DEBUG (so Turnstile
# verification is skipped server-side, the spec fakes the browser script), builds
# Next with the dev API proxy and serves both. The public chat is switched on
# only inside this stack (KG_SUPPORT_CHAT_ENABLED=1).
#
#   .\local-support-chat-stack.ps1 -StackDir C:\temp\scstack -NodeDir D:\programing\tools\node-v20.20.2-win-x64
#   $env:SUPPORT_E2E_FIXTURES = 'C:\temp\scstack\fixtures.json'
#   $env:QA_ORIGIN = 'http://127.0.0.1:3100'
#   $env:PLAYWRIGHT_BROWSERS_PATH = 'D:\programing\tools\playwright-browsers'
#   npx playwright test support-chat.spec.js --project=chromium
param(
  [Parameter(Mandatory)][string]$StackDir,
  [Parameter(Mandatory)][string]$NodeDir,
  [int]$ApiPort = 8000,
  [int]$WebPort = 3100
)
$ErrorActionPreference = 'Stop'
$repo = Resolve-Path (Join-Path $PSScriptRoot '..\..')
$backend = Join-Path $repo 'KG_backend'
$python = Join-Path $backend '.venv\Scripts\python.exe'
New-Item -ItemType Directory -Force $StackDir | Out-Null
$env:PATH = "$NodeDir;$env:PATH"
$env:KG_DB_PATH = Join-Path $StackDir 'e2e.sqlite3'
$env:KG_DATA_DIR = $StackDir
$env:DJANGO_DEBUG = 'true'
$env:KG_ADMIN_TOKEN = 'local-e2e-loopback'
$env:KG_SUPPORT_CHAT_ENABLED = '1'
$env:TURNSTILE_SECRET = ''
$env:KG_SC_CREATE_IP = '0/0'     # one browser IP starts many test chats
$env:KG_SC_BAD_TOKEN_IP = '0/0'
Remove-Item $env:KG_DB_PATH* -ErrorAction SilentlyContinue

Push-Location $backend
& $python manage.py migrate --noinput | Out-Null
$seed = @"
import json
from api.models import AdminAuthToken, PlatformAdmin
out = {}
for key, name in (('staff', 'e2e-staff'), ('staff2', 'e2e-staff-2')):
    a, _ = PlatformAdmin.objects.get_or_create(username=name, defaults={'password_hash': 'x', 'active': True})
    out[key] = {'id': a.id, 'username': a.username, 'token': AdminAuthToken.issue(a).key}
json.dump(out, open(r'$StackDir\fixtures.json', 'w'))
"@
& $python manage.py shell -c $seed
Start-Process -FilePath $python -ArgumentList "manage.py runserver 127.0.0.1:$ApiPort --noreload" `
  -WorkingDirectory $backend -RedirectStandardOutput (Join-Path $StackDir 'django.out.log') `
  -RedirectStandardError (Join-Path $StackDir 'django.err.log') -WindowStyle Hidden
Pop-Location

Push-Location (Join-Path $repo 'kg_frontend')
$env:KG_DEV_API_PROXY = "http://127.0.0.1:$ApiPort"
$env:API_BASE_INTERNAL = "http://127.0.0.1:$ApiPort"
npx next build | Out-Null
Start-Process -FilePath (Join-Path $NodeDir 'npx.cmd') -ArgumentList "next start -p $WebPort" `
  -WorkingDirectory (Get-Location) -RedirectStandardOutput (Join-Path $StackDir 'next.out.log') `
  -RedirectStandardError (Join-Path $StackDir 'next.err.log') -WindowStyle Hidden
Pop-Location
Write-Host "stack up: web http://127.0.0.1:$WebPort  api http://127.0.0.1:$ApiPort  fixtures $StackDir\fixtures.json"
