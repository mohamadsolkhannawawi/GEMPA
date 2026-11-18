#!/bin/bash
# =============================================================================
# SCRIPT PENGECEKAN SPESIFIKASI SISTEM - WSL/LINUX (Bash)
# Jalankan di dalam terminal WSL: bash check_system_wsl.sh
# =============================================================================

OUTPUT_FILE="system_info_wsl.txt"
SEP="============================================================"

write_section() {
    local title="$1"
    local text="\n$SEP\n  $title\n$SEP"
    echo -e "$text"
    echo -e "$text" >> "$OUTPUT_FILE"
}

write_info() {
    local label="$1"
    local value="$2"
    local line
    line=$(printf "  %-35s : %s" "$label" "$value")
    echo "$line"
    echo "$line" >> "$OUTPUT_FILE"
}

write_raw() {
    echo "$1"
    echo "$1" >> "$OUTPUT_FILE"
}

# Bersihkan output lama
> "$OUTPUT_FILE"

HEADER="LAPORAN SPESIFIKASI SISTEM (WSL/Linux)
Waktu    : $(date '+%Y-%m-%d %H:%M:%S')
Hostname : $(hostname)
User     : $(whoami)"
write_raw "$HEADER"

# =============================================================================
# 1. CPU yang dialokasikan ke WSL
# =============================================================================
write_section "1. CPU yang Dialokasikan ke WSL"

TOTAL_CPU=$(nproc)
write_info "Jumlah CPU (nproc)" "$TOTAL_CPU"

if [ -f /proc/cpuinfo ]; then
    MODEL=$(grep "model name" /proc/cpuinfo | head -1 | cut -d: -f2 | xargs)
    CORES=$(grep "^processor" /proc/cpuinfo | wc -l)
    CPU_FREQ=$(grep "cpu MHz" /proc/cpuinfo | head -1 | cut -d: -f2 | xargs)
    CACHE=$(grep "cache size" /proc/cpuinfo | head -1 | cut -d: -f2 | xargs)
    write_info "Model CPU" "$MODEL"
    write_info "Logical Processors" "$CORES"
    write_info "Frekuensi saat ini" "$CPU_FREQ MHz"
    write_info "Cache Size" "$CACHE"
fi

write_raw ""
write_raw "  Detail lscpu:"
if command -v lscpu &>/dev/null; then
    lscpu | grep -E "^Architecture|^CPU\(s\)|^Thread|^Core|^Socket|^Model name|^CPU max MHz|^CPU min MHz|^Vendor|^Virtualization" | \
    while IFS=: read -r key val; do
        write_info "  $(echo "$key" | xargs)" "$(echo "$val" | xargs)"
    done
else
    write_raw "  lscpu tidak tersedia"
fi

# =============================================================================
# 2. RAM yang dialokasikan ke WSL
# =============================================================================
write_section "2. RAM yang Dialokasikan ke WSL"

if [ -f /proc/meminfo ]; then
    MEM_TOTAL=$(grep "^MemTotal" /proc/meminfo | awk '{printf "%.2f GB", $2/1024/1024}')
    MEM_FREE=$(grep "^MemFree" /proc/meminfo | awk '{printf "%.2f GB", $2/1024/1024}')
    MEM_AVAIL=$(grep "^MemAvailable" /proc/meminfo | awk '{printf "%.2f GB", $2/1024/1024}')
    MEM_USED=$(grep -E "^MemTotal|^MemAvailable" /proc/meminfo | awk 'NR==1{t=$2} NR==2{a=$2} END{printf "%.2f GB", (t-a)/1024/1024}')
    SWAP_TOTAL=$(grep "^SwapTotal" /proc/meminfo | awk '{printf "%.2f GB", $2/1024/1024}')
    SWAP_FREE=$(grep "^SwapFree" /proc/meminfo | awk '{printf "%.2f GB", $2/1024/1024}')

    write_info "Total RAM"          "$MEM_TOTAL"
    write_info "RAM Tersedia"       "$MEM_AVAIL"
    write_info "RAM Digunakan"      "$MEM_USED"
    write_info "RAM Bebas (strict)" "$MEM_FREE"
    write_info "Total Swap"         "$SWAP_TOTAL"
    write_info "Swap Bebas"         "$SWAP_FREE"
fi

write_raw ""
write_raw "  Output 'free -h':"
free -h 2>/dev/null | while IFS= read -r line; do write_raw "    $line"; done

# =============================================================================
# 3. Kernel & WSL Info
# =============================================================================
write_section "3. Kernel & WSL Info"
write_info "Kernel Version"     "$(uname -r)"
write_info "Kernel Full"        "$(uname -a)"
write_info "OS Release"         "$(cat /etc/os-release 2>/dev/null | grep PRETTY_NAME | cut -d= -f2 | tr -d '\"')"

# Deteksi apakah ini WSL
if grep -qi microsoft /proc/version 2>/dev/null; then
    write_info "Lingkungan"     "WSL (Windows Subsystem for Linux)"
    WSL_VER=$(uname -r | grep -o "WSL2\|WSL1" || echo "WSL (versi tidak terdeteksi dari kernel string)")
    # Cek versi WSL dari string kernel
    if uname -r | grep -q "microsoft-standard-WSL2"; then
        write_info "Versi WSL"  "WSL 2"
    elif uname -r | grep -q "Microsoft"; then
        write_info "Versi WSL"  "WSL 1"
    else
        write_info "Versi WSL"  "WSL (cek dengan 'wsl --list --verbose' di PowerShell)"
    fi
else
    write_info "Lingkungan"     "Native Linux / Non-WSL"
fi

# =============================================================================
# 4. GPU via nvidia-smi (dalam WSL)
# =============================================================================
write_section "4. GPU via nvidia-smi (WSL)"
if command -v nvidia-smi &>/dev/null; then
    write_raw ""
    write_raw "  nvidia-smi output lengkap:"
    nvidia-smi 2>&1 | while IFS= read -r line; do write_raw "  $line"; done

    write_raw ""
    write_raw "  nvidia-smi query (nama, VRAM, driver, compute capability):"
    nvidia-smi --query-gpu=index,name,memory.total,memory.free,memory.used,driver_version,compute_cap,temperature.gpu,utilization.gpu \
        --format=csv,noheader,nounits 2>/dev/null | \
    while IFS=, read -r idx gname mem_total mem_free mem_used drv_ver comp_cap temp util; do
        write_info "  GPU Index"              "$(echo $idx | xargs)"
        write_info "  Nama GPU"               "$(echo $gname | xargs)"
        write_info "  VRAM Total"             "$(echo $mem_total | xargs) MiB ($(echo "scale=2; $mem_total/1024" | bc) GB)"
        write_info "  VRAM Bebas"             "$(echo $mem_free | xargs) MiB"
        write_info "  VRAM Digunakan"         "$(echo $mem_used | xargs) MiB"
        write_info "  Driver Version"         "$(echo $drv_ver | xargs)"
        write_info "  Compute Capability"     "$(echo $comp_cap | xargs)"
        write_info "  Temperatur GPU"         "$(echo $temp | xargs) C"
        write_info "  Utilisasi GPU"          "$(echo $util | xargs) %"
    done
else
    write_raw "  nvidia-smi tidak ditemukan di WSL."
    write_raw "  Pastikan NVIDIA driver WSL (CUDA on WSL) sudah terinstal."
    write_raw "  Referensi: https://docs.nvidia.com/cuda/wsl-user-guide/"
fi

# =============================================================================
# 5. Storage (dari perspektif WSL)
# =============================================================================
write_section "5. Storage (df dari WSL)"
write_raw ""
write_raw "  df -h (semua mount point):"
df -h 2>/dev/null | while IFS= read -r line; do write_raw "  $line"; done

write_raw ""
write_raw "  Mount point /mnt/* (drive Windows yang dimount ke WSL):"
df -h 2>/dev/null | grep "^/mnt/" | while IFS= read -r line; do write_raw "  $line"; done

# =============================================================================
# 6. Python & Node.js (dalam WSL)
# =============================================================================
write_section "6. Runtime: Python & Node.js (WSL)"

if command -v python3 &>/dev/null; then
    write_info "Python3" "$(python3 --version 2>&1)"
    write_info "Python3 Path" "$(which python3)"
    write_info "pip3" "$(pip3 --version 2>/dev/null | head -1 || echo 'tidak ditemukan')"
else
    write_info "Python3" "Tidak ditemukan"
fi

if command -v python &>/dev/null; then
    write_info "Python" "$(python --version 2>&1)"
fi

if command -v node &>/dev/null; then
    write_info "Node.js" "$(node --version 2>&1)"
    write_info "Node.js Path" "$(which node)"
else
    write_info "Node.js" "Tidak ditemukan"
fi

if command -v npm &>/dev/null; then
    write_info "npm" "$(npm --version 2>&1)"
fi

# =============================================================================
# 7. Docker (dari dalam WSL)
# =============================================================================
write_section "7. Docker (dari dalam WSL)"
if command -v docker &>/dev/null; then
    write_raw ""
    write_raw "  docker version:"
    docker version 2>&1 | while IFS= read -r line; do write_raw "    $line"; done

    write_raw ""
    write_raw "  Container yang berjalan:"
    docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}" 2>&1 | \
        while IFS= read -r line; do write_raw "  $line"; done

    write_raw ""
    write_raw "  Semua container:"
    docker ps -a --format "table {{.Names}}\t{{.Image}}\t{{.Status}}" 2>&1 | \
        while IFS= read -r line; do write_raw "  $line"; done
else
    write_raw "  Docker tidak ditemukan di WSL."
fi

# =============================================================================
# 8. Kafka (cek via Docker)
# =============================================================================
write_section "8. Apache Kafka (via Docker)"
if command -v docker &>/dev/null; then
    KAFKA_CONTAINERS=$(docker ps --format "{{.Names}}\t{{.Image}}" 2>/dev/null | grep -i kafka)
    if [ -n "$KAFKA_CONTAINERS" ]; then
        write_raw "  Container Kafka yang berjalan:"
        echo "$KAFKA_CONTAINERS" | while IFS= read -r line; do write_raw "    $line"; done

        # Coba ambil versi Kafka
        KAFKA_CTR=$(docker ps --format "{{.Names}}" 2>/dev/null | grep -i kafka | grep -v zookeeper | head -1)
        if [ -n "$KAFKA_CTR" ]; then
            write_raw ""
            write_raw "  Versi Kafka dari container '$KAFKA_CTR':"
            KAFKA_VER=$(docker exec "$KAFKA_CTR" kafka-topics.sh --version 2>/dev/null || \
                        docker exec "$KAFKA_CTR" /opt/kafka/bin/kafka-topics.sh --version 2>/dev/null || \
                        docker exec "$KAFKA_CTR" bash -c "find / -name 'kafka-*.jar' 2>/dev/null | head -1" 2>/dev/null || \
                        echo "Tidak dapat membaca versi Kafka dari container")
            write_raw "    $KAFKA_VER"
        fi
    else
        write_raw "  Tidak ada container Kafka yang berjalan saat ini."
    fi

    # Cek Zookeeper
    ZK_CTR=$(docker ps --format "{{.Names}}\t{{.Image}}" 2>/dev/null | grep -i zookeeper)
    if [ -n "$ZK_CTR" ]; then
        write_raw ""
        write_raw "  Container Zookeeper:"
        echo "$ZK_CTR" | while IFS= read -r line; do write_raw "    $line"; done
    fi
else
    write_raw "  Docker tidak tersedia, tidak dapat cek Kafka."
fi

# =============================================================================
# 9. MongoDB
# =============================================================================
write_section "9. MongoDB (via Docker)"
if command -v docker &>/dev/null; then
    MONGO_CTR=$(docker ps --format "{{.Names}}" 2>/dev/null | grep -i mongo | grep -iv express | head -1)
    if [ -n "$MONGO_CTR" ]; then
        write_raw "  Container MongoDB: $MONGO_CTR"
        MONGO_VER=$(docker exec "$MONGO_CTR" mongod --version 2>/dev/null || \
                    docker exec "$MONGO_CTR" mongosh --version 2>/dev/null || \
                    echo "Tidak dapat membaca versi")
        write_raw "  Versi MongoDB: $MONGO_VER"
    else
        write_raw "  Tidak ada container MongoDB yang berjalan."
    fi

    MONGOEX_CTR=$(docker ps --format "{{.Names}}\t{{.Image}}" 2>/dev/null | grep -i "mongo-express\|mongoexpress")
    if [ -n "$MONGOEX_CTR" ]; then
        write_raw "  Container Mongo Express: $MONGOEX_CTR"
    fi
fi

# =============================================================================
# 10. Observabilitas: Prometheus, Grafana, InfluxDB, Telegraf, Node Exporter
# =============================================================================
write_section "10. Stack Observabilitas (via Docker)"
if command -v docker &>/dev/null; then
    for SERVICE in prometheus grafana influxdb telegraf "node-exporter\|nodeexporter"; do
        CTR=$(docker ps --format "{{.Names}}\t{{.Image}}\t{{.Status}}" 2>/dev/null | grep -i "$SERVICE" | head -1)
        DISPLAY_NAME=$(echo "$SERVICE" | sed 's/\\|.*//')
        if [ -n "$CTR" ]; then
            write_raw "  [$DISPLAY_NAME] BERJALAN : $CTR"
        else
            # Cek apakah ada tapi stopped
            CTR_STOPPED=$(docker ps -a --format "{{.Names}}\t{{.Image}}\t{{.Status}}" 2>/dev/null | grep -i "$SERVICE" | head -1)
            if [ -n "$CTR_STOPPED" ]; then
                write_raw "  [$DISPLAY_NAME] STOPPED  : $CTR_STOPPED"
            else
                write_raw "  [$DISPLAY_NAME] Tidak ditemukan"
            fi
        fi
    done
fi

# =============================================================================
# SELESAI
# =============================================================================
FOOTER="\n$SEP\nSELESAI. Output disimpan ke: $OUTPUT_FILE\n$SEP"
write_raw "$FOOTER"
echo ""
echo "[INFO] Informasi yang HARUS dicek manual:"
echo "       1. VRAM GPU akurat -> NVIDIA Control Panel atau GPU-Z di Windows"
echo "       2. Tipe & kecepatan RAM fisik (DDR5, 4800 MHz) -> CPU-Z atau BIOS"
echo "       3. Model SSD fisik (MSI M470 PRO) -> CrystalDiskInfo atau BIOS"
