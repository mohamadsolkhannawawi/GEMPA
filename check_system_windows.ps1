# =============================================================================
# SCRIPT PENGECEKAN SPESIFIKASI SISTEM - WINDOWS (PowerShell)
# Jalankan dengan: powershell -ExecutionPolicy Bypass -File check_system_windows.ps1
# =============================================================================

$OutputFile = "system_info_windows.txt"
$Separator = "=" * 60

function Write-Section($title) {
    $line = "`n$Separator`n  $title`n$Separator"
    Write-Host $line -ForegroundColor Cyan
    Add-Content $OutputFile $line
}

function Write-Info($label, $value) {
    $line = "  {0,-35} : {1}" -f $label, $value
    Write-Host $line
    Add-Content $OutputFile $line
}

function Write-Raw($text) {
    Write-Host $text
    Add-Content $OutputFile $text
}

# Bersihkan file output lama
if (Test-Path $OutputFile) { Remove-Item $OutputFile }
$header = "LAPORAN SPESIFIKASI SISTEM`nWaktu     : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')`nKomputer  : $env:COMPUTERNAME`nUser      : $env:USERNAME"
Write-Raw $header

# =============================================================================
# 1. CPU
# =============================================================================
Write-Section "1. CPU (Central Processing Unit)"
$cpu = Get-WmiObject Win32_Processor
foreach ($c in $cpu) {
    Write-Info "Nama CPU"               $c.Name.Trim()
    Write-Info "Manufacturer"           $c.Manufacturer
    Write-Info "Max Clock Speed"        "$($c.MaxClockSpeed) MHz"
    Write-Info "Jumlah Physical Core"   $c.NumberOfCores
    Write-Info "Jumlah Logical CPU"     $c.NumberOfLogicalProcessors
    Write-Info "Architecture"           $(switch ($c.Architecture) {
        0 {"x86"} 5 {"ARM"} 9 {"x64"} default {"Unknown ($_)"}
    })
    Write-Info "Socket"                 $c.SocketDesignation
}

# =============================================================================
# 2. RAM
# =============================================================================
Write-Section "2. RAM (Memory)"
$ramModules = Get-WmiObject Win32_PhysicalMemory
$totalRamGB = [math]::Round(($ramModules | Measure-Object -Property Capacity -Sum).Sum / 1GB, 2)
Write-Info "Total RAM" "$totalRamGB GB"

$idx = 1
foreach ($ram in $ramModules) {
    $capacityGB = [math]::Round($ram.Capacity / 1GB, 2)
    $memType = switch ($ram.SMBIOSMemoryType) {
        20 {"DDR"} 21 {"DDR2"} 22 {"DDR2 FB-DIMM"} 24 {"DDR3"} 26 {"DDR4"} 34 {"DDR5"} default {"Unknown ($($ram.SMBIOSMemoryType))"}
    }
    Write-Info "Slot $idx - Kapasitas"  "$capacityGB GB"
    Write-Info "Slot $idx - Tipe"       $memType
    Write-Info "Slot $idx - Kecepatan"  "$($ram.Speed) MHz"
    Write-Info "Slot $idx - Manufacturer" $ram.Manufacturer
    Write-Info "Slot $idx - Part Number"  $ram.PartNumber.Trim()
    $idx++
}

# =============================================================================
# 3. GPU
# =============================================================================
Write-Section "3. GPU (Graphics Processing Unit)"
$gpus = Get-WmiObject Win32_VideoController
foreach ($gpu in $gpus) {
    Write-Info "Nama GPU"               $gpu.Name
    # AdapterRAM via WMI terbatas 32-bit, hanya akurat untuk GPU <= 4GB
    $vramRaw = $gpu.AdapterRAM
    if ($vramRaw -and $vramRaw -gt 0) {
        $vramGB = [math]::Round($vramRaw / 1GB, 2)
        Write-Info "VRAM (WMI, maks 4GB)" "$vramGB GB  *lihat catatan"
    } else {
        Write-Info "VRAM (WMI)"           "Tidak terbaca (cek manual via NVIDIA Control Panel)"
    }
    Write-Info "Driver Version"         $gpu.DriverVersion
    Write-Info "Driver Date"            $gpu.DriverDate
    Write-Info "Video Mode Deskripsi"   $gpu.VideoModeDescription
    Write-Info "Processor"              $gpu.VideoProcessor
    Write-Raw  ""
}
Write-Raw "  [!] CATATAN VRAM: WMI membatasi field AdapterRAM pada 32-bit (maks ~4 GB)."
Write-Raw "      Untuk VRAM akurat (mis. RTX 5090 = 32 GB), cek via:"
Write-Raw "      - NVIDIA Control Panel -> System Information"
Write-Raw "      - GPU-Z (https://www.techpowerup.com/gpuz/)"
Write-Raw "      - nvidia-smi (jika CUDA terinstal)"

# Coba nvidia-smi jika tersedia
Write-Raw ""
Write-Raw "  [*] Mencoba nvidia-smi..."
$nvidiaSmi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($nvidiaSmi) {
    $nvOut = nvidia-smi --query-gpu=name,memory.total,driver_version,compute_cap --format=csv,noheader 2>&1
    Write-Raw "  nvidia-smi output:"
    foreach ($line in $nvOut) { Write-Raw "    $line" }
} else {
    Write-Raw "  nvidia-smi tidak ditemukan di PATH Windows."
    Write-Raw "  Coba jalankan dari WSL: wsl nvidia-smi"
}

# =============================================================================
# 4. STORAGE
# =============================================================================
Write-Section "4. Storage (Media Penyimpanan)"
try {
    $disks = Get-PhysicalDisk | Select-Object FriendlyName, MediaType, `
        @{N="Size_GB";E={[math]::Round($_.Size/1GB,2)}}, BusType, Model
    foreach ($d in $disks) {
        Write-Info "Nama"       $d.FriendlyName
        Write-Info "Model"      $d.Model
        Write-Info "Tipe Media" $d.MediaType
        Write-Info "Bus Type"   $d.BusType
        Write-Info "Ukuran"     "$($d.Size_GB) GB"
        Write-Raw ""
    }
} catch {
    Write-Raw "  Gagal membaca info disk via Get-PhysicalDisk: $_"
}

Write-Raw ""
Write-Raw "  Partisi / Volume:"
Get-WmiObject Win32_LogicalDisk | Where-Object {$_.DriveType -eq 3} | ForEach-Object {
    $sizeGB  = [math]::Round($_.Size/1GB, 2)
    $freeGB  = [math]::Round($_.FreeSpace/1GB, 2)
    $usedGB  = [math]::Round(($_.Size - $_.FreeSpace)/1GB, 2)
    Write-Info "  Drive $($_.DeviceID)" "$usedGB GB used / $sizeGB GB total ($freeGB GB free) - $($_.VolumeName)"
}

# =============================================================================
# 5. SISTEM OPERASI
# =============================================================================
Write-Section "5. Sistem Operasi"
$os = Get-WmiObject Win32_OperatingSystem
Write-Info "Nama OS"            $os.Caption
Write-Info "Versi"              $os.Version
Write-Info "Build Number"       $os.BuildNumber
Write-Info "Arsitektur"         $os.OSArchitecture
Write-Info "Service Pack"       $os.ServicePackMajorVersion
Write-Info "Install Date"       ([Management.ManagementDateTimeConverter]::ToDateTime($os.InstallDate)).ToString("yyyy-MM-dd")
Write-Info "Last Boot"          ([Management.ManagementDateTimeConverter]::ToDateTime($os.LastBootUpTime)).ToString("yyyy-MM-dd HH:mm:ss")

# Windows Update Build Revision (UBR)
try {
    $ubr = (Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion").UBR
    $build = $os.BuildNumber
    Write-Info "Build Lengkap"      "$build.$ubr"
} catch {}

# =============================================================================
# 6. WSL
# =============================================================================
Write-Section "6. WSL (Windows Subsystem for Linux)"
$wslCmd = Get-Command wsl -ErrorAction SilentlyContinue
if ($wslCmd) {
    Write-Raw ""
    Write-Raw "  Distribusi WSL yang terdaftar:"
    $wslList = wsl --list --verbose 2>&1
    foreach ($line in $wslList) { Write-Raw "    $line" }

    $wslConfigPath = "$env:USERPROFILE\.wslconfig"
    Write-Raw ""
    if (Test-Path $wslConfigPath) {
        Write-Raw "  File .wslconfig ditemukan di: $wslConfigPath"
        Write-Raw "  Isi .wslconfig:"
        Get-Content $wslConfigPath | ForEach-Object { Write-Raw "    $_" }
    } else {
        Write-Raw "  File .wslconfig TIDAK ditemukan."
        Write-Raw "  Alokasi WSL menggunakan nilai default Windows."
        Write-Raw "  Default: 50% RAM, semua CPU core"
    }
} else {
    Write-Raw "  WSL tidak terinstal atau tidak ditemukan di PATH."
}

# =============================================================================
# 7. DOCKER
# =============================================================================
Write-Section "7. Docker"
$dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
if ($dockerCmd) {
    Write-Raw ""
    Write-Raw "  docker version:"
    docker version 2>&1 | ForEach-Object { Write-Raw "    $_" }
    Write-Raw ""
    Write-Raw "  docker info (ringkasan):"
    $dockerInfo = docker info 2>&1
    $dockerInfo | Where-Object { $_ -match "Server Version|Operating System|OSType|Architecture|CPUs|Total Memory|Docker Root Dir|Storage Driver|Kernel Version|Backend" } | ForEach-Object { Write-Raw "    $_" }
} else {
    Write-Raw "  Docker tidak ditemukan di PATH."
}

# =============================================================================
# 8. PYTHON & NODE.JS (Windows)
# =============================================================================
Write-Section "8. Runtime: Python & Node.js (Windows)"
$pyCmd = Get-Command python -ErrorAction SilentlyContinue
if ($pyCmd) {
    $pyVer = python --version 2>&1
    Write-Info "Python (Windows)" $pyVer
    Write-Info "Path"             $pyCmd.Source
} else {
    Write-Info "Python (Windows)" "Tidak ditemukan"
}

$py3Cmd = Get-Command python3 -ErrorAction SilentlyContinue
if ($py3Cmd) {
    $py3Ver = python3 --version 2>&1
    Write-Info "Python3 (Windows)" $py3Ver
}

$nodeCmd = Get-Command node -ErrorAction SilentlyContinue
if ($nodeCmd) {
    $nodeVer = node --version 2>&1
    Write-Info "Node.js (Windows)" $nodeVer
    Write-Info "Path"              $nodeCmd.Source
} else {
    Write-Info "Node.js (Windows)" "Tidak ditemukan"
}

$npmCmd = Get-Command npm -ErrorAction SilentlyContinue
if ($npmCmd) {
    $npmVer = npm --version 2>&1
    Write-Info "npm (Windows)" $npmVer
}

# =============================================================================
# 9. CONTAINER SERVICES (via Docker)
# =============================================================================
Write-Section "9. Container yang Berjalan (Docker)"
$dockerCmd2 = Get-Command docker -ErrorAction SilentlyContinue
if ($dockerCmd2) {
    Write-Raw ""
    Write-Raw "  Container aktif:"
    docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}" 2>&1 | ForEach-Object { Write-Raw "  $_" }
    Write-Raw ""
    Write-Raw "  Semua container (termasuk stopped):"
    docker ps -a --format "table {{.Names}}\t{{.Image}}\t{{.Status}}" 2>&1 | ForEach-Object { Write-Raw "  $_" }
}

# =============================================================================
# SELESAI
# =============================================================================
$footer = "`n$Separator`nSELESAI. Output disimpan ke: $OutputFile`n$Separator"
Write-Host $footer -ForegroundColor Green
Add-Content $OutputFile $footer
Write-Host "`n[INFO] Untuk info WSL (alokasi core/RAM di dalam WSL), jalankan:" -ForegroundColor Yellow
Write-Host "       bash check_system_wsl.sh   (di dalam terminal WSL)" -ForegroundColor Yellow
