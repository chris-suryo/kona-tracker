# Why won't the robot connect? Run this and it tells you.
#
# The Robot tab says one thing ("ROBOT OFF") for four different faults, and
# the only honest fix is to check the layers in order. The first FAIL is the
# answer; everything below it is noise.
#
#   powershell -ExecutionPolicy Bypass -File scripts\robot_check.ps1
#
# Optional: -Address 192.0.2.42 if the Pi has moved.

param(
    [string]$Address,
    [int]$CameraPort = 8080,
    [int]$GatewayPort = 9031
)

# Without -Address, check the robot the app itself is configured to reach:
# the host in KONA_ROBOT_CONTROL_URL in .env. The point of this script is
# to explain why the Robot tab says ROBOT OFF, and that tab uses this
# address, not a default written into a script. `turbopi.local` is the
# fallback when there is no .env yet.
if (-not $Address) {
    $envFile = Join-Path (Split-Path -Parent $PSScriptRoot) ".env"
    if (Test-Path $envFile) {
        $line = Get-Content $envFile | Where-Object { $_ -match '^\s*KONA_ROBOT_CONTROL_URL\s*=' } | Select-Object -First 1
        if ($line -and $line -match '://([^:/\s]+)') { $Address = $Matches[1] }
    }
    if (-not $Address) { $Address = "turbopi.local" }
}

$ErrorActionPreference = "Continue"
$failed = $false

function Step($name, [scriptblock]$check, $meaning) {
    Write-Host -NoNewline ("  {0,-34}" -f $name)
    $ok = $false
    try { $ok = & $check } catch { $ok = $false }
    if ($ok) {
        Write-Host "OK" -ForegroundColor Green
    } else {
        Write-Host "FAIL" -ForegroundColor Red
        Write-Host "      $meaning" -ForegroundColor Yellow
        $script:failed = $true
    }
    return $ok
}

Write-Host ""
Write-Host "Robot at $Address" -ForegroundColor Cyan
Write-Host ""

# 1. On the network at all. After a reboot this is the usual culprit, because
#    without a DHCP reservation the router is free to hand out a new address.
$up = Step "1. Answers a ping" {
    Test-Connection -ComputerName $Address -Count 2 -Quiet -ErrorAction SilentlyContinue
} "Not on the network, or the address moved. Reserve it in the router. To find it:  arp -a | Select-String '10.0.0'   -- or try  http://turbopi.local:$CameraPort/?action=snapshot"

if (-not $up) {
    Write-Host ""
    Write-Host "Nothing below this can pass. Fix the address first." -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

# 2. The camera server. Independent of the gateway: the Robot tab can show a
#    picture while driving is dead, and vice versa.
Step "2. Camera server (port $CameraPort)" {
    (Test-NetConnection -ComputerName $Address -Port $CameraPort -WarningAction SilentlyContinue).TcpTestSucceeded
} "The Pi is up but its camera is not. On the Pi:  sudo systemctl restart turbopi" | Out-Null

# 3. The drive gateway. A different service, and the one the Drive page needs.
$gate = Step "3. Drive gateway (port $GatewayPort)" {
    (Test-NetConnection -ComputerName $Address -Port $GatewayPort -WarningAction SilentlyContinue).TcpTestSucceeded
} "Gateway not listening. On the Pi:  sudo systemctl restart turbopi-gateway"

# 4. /health needs no token, so it answers even when KONA_ROBOT_TOKEN is
#    wrong -- which is exactly how you tell those two faults apart.
if ($gate) {
    Step "4. Gateway answers /health" {
        $r = Invoke-WebRequest -Uri "http://${Address}:${GatewayPort}/health" -TimeoutSec 5 -UseBasicParsing
        $r.StatusCode -eq 200
    } "The port is open but the gateway is not answering. Check its log:  sudo journalctl -u turbopi-gateway -n 50" | Out-Null

    # 5. The robot's own software, underneath the gateway. This is the gap
    #    nothing else covers: if TurboPi.py dies the gateway stays up and
    #    healthy-looking while nothing can actually move the wheels.
    try {
        $health = (Invoke-WebRequest -Uri "http://${Address}:${GatewayPort}/health" -TimeoutSec 5 -UseBasicParsing).Content
        Write-Host ""
        Write-Host "  /health says: $health" -ForegroundColor DarkGray
        if ($health -match "turbopi_unreachable") {
            Write-Host "      The gateway is fine but TurboPi.py is not answering it." -ForegroundColor Yellow
            Write-Host "      On the Pi:  sudo systemctl restart turbopi" -ForegroundColor Yellow
            $script:failed = $true
        }
    } catch { }
}

Write-Host ""
if ($failed) {
    Write-Host "Something above is down. The first FAIL is the one to fix." -ForegroundColor Yellow
} else {
    Write-Host "All clear. Open the Robot tab." -ForegroundColor Green
}
Write-Host ""

# Powering the Pi ON is not on this list, and cannot be: a Raspberry Pi with
# no power draws no power, so nothing on the network can wake it. Wake-on-LAN
# does not apply -- it needs a NIC that stays energised, which the Pi's does
# not. If you want the robot startable while you are out, the answer is a
# smart plug on its charger, not software. See docs/robot-runbook.md.
