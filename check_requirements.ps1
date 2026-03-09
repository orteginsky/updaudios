# check_requirements.ps1
# Valida que el entorno Windows tenga todo lo necesario para correr updaudios
# Ejecutar en PowerShell como Administrador

$pass = 0
$fail = 0
$warn = 0

function OK   ($msg) { Write-Host "  [OK]   $msg" -ForegroundColor Green;  $global:pass++ }
function FAIL ($msg) { Write-Host "  [FAIL] $msg" -ForegroundColor Red;    $global:fail++ }
function WARN ($msg) { Write-Host "  [WARN] $msg" -ForegroundColor Yellow; $global:warn++ }
function HEAD ($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }

# ─── 1. Sistema operativo ──────────────────────────────────────────────────────
HEAD "Sistema Operativo"

$os = Get-CimInstance Win32_OperatingSystem
$build = [int]$os.BuildNumber
Write-Host "  Windows: $($os.Caption) (Build $build)"

if ($build -ge 19041) {
    OK "Build $build soporta WSL 2 (minimo requerido: 19041)"
} else {
    FAIL "Build $build demasiado antiguo. Actualiza Windows 10 a version 2004+ o usa Windows 11."
}

# ─── 2. Virtualizacion ────────────────────────────────────────────────────────
HEAD "Virtualizacion"

$cpu = Get-CimInstance Win32_Processor
if ($cpu.VirtualizationFirmwareEnabled) {
    OK "Virtualizacion habilitada en BIOS/UEFI"
} else {
    FAIL "Virtualizacion deshabilitada en BIOS/UEFI. Habilita Intel VT-x o AMD-V en el BIOS."
}

$hyperv = Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All -ErrorAction SilentlyContinue
if ($hyperv -and $hyperv.State -eq "Enabled") {
    OK "Hyper-V habilitado"
} else {
    WARN "Hyper-V no detectado (requerido para Docker Desktop en modo Hyper-V, opcional si usas WSL 2)"
}

# ─── 3. WSL 2 ─────────────────────────────────────────────────────────────────
HEAD "WSL 2"

$wslFeature = Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux -ErrorAction SilentlyContinue
if ($wslFeature -and $wslFeature.State -eq "Enabled") {
    OK "Caracteristica WSL habilitada"
} else {
    FAIL "WSL no esta habilitado. Ejecuta: wsl --install"
}

$vmPlatform = Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform -ErrorAction SilentlyContinue
if ($vmPlatform -and $vmPlatform.State -eq "Enabled") {
    OK "Virtual Machine Platform habilitada"
} else {
    FAIL "Virtual Machine Platform no esta habilitada. Ejecuta: dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart"
}

try {
    $wslOutput = wsl --status 2>&1
    $wslVersion = wsl --list --verbose 2>&1
    if ($LASTEXITCODE -eq 0) {
        OK "WSL responde correctamente"
        # Verificar que alguna distro use WSL 2
        if ($wslVersion -match "2\s*$") {
            OK "Al menos una distribucion WSL usa version 2"
        } else {
            WARN "No se detecto ninguna distribucion en WSL 2. Ejecuta: wsl --set-default-version 2"
        }
    } else {
        FAIL "WSL no responde. Puede necesitar reinicio o el kernel de WSL 2 no esta instalado."
    }
} catch {
    FAIL "No se pudo ejecutar wsl. Verifica la instalacion."
}

# ─── 4. Docker Desktop ────────────────────────────────────────────────────────
HEAD "Docker Desktop"

$dockerDesktopPath = @(
    "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe",
    "${env:ProgramFiles(x86)}\Docker\Docker\Docker Desktop.exe"
)

$dockerInstalled = $false
foreach ($p in $dockerDesktopPath) {
    if (Test-Path $p) {
        $dockerInstalled = $true
        $version = (Get-Item $p).VersionInfo.ProductVersion
        OK "Docker Desktop instalado: $p (v$version)"
        break
    }
}
if (-not $dockerInstalled) {
    FAIL "Docker Desktop no encontrado. Descargalo desde: https://www.docker.com/products/docker-desktop/"
}

# Verificar proceso de Docker Desktop
$dockerProcess = Get-Process "Docker Desktop" -ErrorAction SilentlyContinue
if ($dockerProcess) {
    OK "Proceso 'Docker Desktop' esta corriendo"
} else {
    FAIL "Docker Desktop NO esta corriendo. Abrelo desde el menu Inicio y espera a que el icono en la barra de tareas quede en verde."
}

# ─── 5. Docker CLI y daemon ───────────────────────────────────────────────────
HEAD "Docker CLI y Daemon"

$dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
if ($dockerCmd) {
    $dockerVersion = docker --version 2>&1
    OK "docker CLI disponible: $dockerVersion"
} else {
    FAIL "Comando 'docker' no encontrado en PATH. Reinstala Docker Desktop."
}

try {
    $dockerInfo = docker info 2>&1
    if ($LASTEXITCODE -eq 0) {
        OK "Docker daemon responde correctamente (docker info exitoso)"
    } else {
        FAIL "Docker daemon NO responde. Error:`n$dockerInfo`n  --> Abre Docker Desktop y espera que este en estado 'Running'."
    }
} catch {
    FAIL "No se pudo ejecutar 'docker info'."
}

# ─── 6. Docker Compose ────────────────────────────────────────────────────────
HEAD "Docker Compose"

try {
    $composeVersion = docker compose version 2>&1
    if ($LASTEXITCODE -eq 0) {
        OK "docker compose (plugin): $composeVersion"
    } else {
        FAIL "docker compose plugin no disponible."
    }
} catch {
    FAIL "No se pudo verificar docker compose."
}

try {
    $composeLegacy = docker-compose --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        OK "docker-compose (standalone): $composeLegacy"
    } else {
        WARN "docker-compose standalone no disponible (no es problema si el plugin funciona)"
    }
} catch {
    WARN "docker-compose standalone no encontrado"
}

# ─── 7. Recursos del sistema ──────────────────────────────────────────────────
HEAD "Recursos del sistema"

$ram = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
if ($ram -ge 8) {
    OK "RAM: ${ram} GB (recomendado >= 8 GB)"
} else {
    WARN "RAM: ${ram} GB. Docker Desktop puede ser lento con menos de 8 GB."
}

$disk = Get-PSDrive C | Select-Object -ExpandProperty Free
$diskGB = [math]::Round($disk / 1GB, 1)
if ($diskGB -ge 10) {
    OK "Espacio libre en C:\: ${diskGB} GB"
} else {
    WARN "Espacio libre en C:\: ${diskGB} GB. Se recomienda al menos 10 GB libres para imagenes Docker."
}

# ─── 8. Resumen ───────────────────────────────────────────────────────────────
HEAD "Resumen"
Write-Host ""
Write-Host "  Checks pasados : $pass" -ForegroundColor Green
Write-Host "  Advertencias   : $warn" -ForegroundColor Yellow
Write-Host "  Checks fallidos: $fail" -ForegroundColor Red
Write-Host ""

if ($fail -eq 0) {
    Write-Host "  Todo listo. Puedes ejecutar: docker-compose up -d --build" -ForegroundColor Green
} else {
    Write-Host "  Corrige los items [FAIL] antes de continuar." -ForegroundColor Red
}
Write-Host ""
