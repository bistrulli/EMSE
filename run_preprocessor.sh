#!/bin/sh

# Verifica che tutti i parametri richiesti siano stati forniti
if [ $# -ne 5 ]; then
    echo "Usage: $0 <output_dir> <log_file> <kernel_source> <project_dir> <arch>"
    echo "Example: $0 processed preproc.log kernel_sources/linux-5.9.9_arm64 projects/dummy_project arm64"
    exit 1
fi

# Parametri di input
OUTPUT_DIR="$1"
LOG_FILE="$2"
KERNEL_SOURCE="$3"
PROJECT_DIR="$4"
ARCH="$5"

# Verifica che le directory esistano
if [ ! -d "$KERNEL_SOURCE" ]; then
    echo "ERROR: Kernel source directory not found: $KERNEL_SOURCE"
    exit 1
fi

if [ ! -d "$PROJECT_DIR" ]; then
    echo "ERROR: Project directory not found: $PROJECT_DIR"
    exit 1
fi

# Crea la directory di output se non esiste
mkdir -p "$OUTPUT_DIR"

# Costruisci la stringa dei path di include verificando che esistano
INCLUDE_PATHS=""

# Verifica e aggiungi ogni directory di include
for dir in \
    "$KERNEL_SOURCE/include" \
    "$KERNEL_SOURCE/arch/$ARCH/include" \
    "$KERNEL_SOURCE/arch/$ARCH/include/generated" \
    "$KERNEL_SOURCE/include/generated" \
    "$KERNEL_SOURCE/arch/$ARCH/include/uapi" \
    "$KERNEL_SOURCE/include/asm-generic" \
    "$PROJECT_DIR"
do
    if [ -d "$dir" ]; then
        # Converti il path in assoluto
        abs_dir=$(realpath "$dir")
        INCLUDE_PATHS="$INCLUDE_PATHS $abs_dir"
    else
        echo "WARNING: Include directory not found: $dir"
    fi
done

# Esegui il preprocessore
echo "Starting preprocessing..."
echo "Project directory: $PROJECT_DIR"
echo "Output directory: $OUTPUT_DIR"
echo "Include paths:"
for path in $INCLUDE_PATHS; do
    echo "  - $path"
done

python3 preprocessor.py \
    --project-path "$PROJECT_DIR" \
    --output-dir "$OUTPUT_DIR" \
    --include-paths $INCLUDE_PATHS > "$LOG_FILE" 2>&1

# Controlla il risultato
if [ $? -eq 0 ]; then
    echo "Preprocessing completed successfully!"
    # Mostra il resoconto dal log
    grep "Successfully processed:" "$LOG_FILE"
    grep "Skipped:" "$LOG_FILE"
else
    echo "ERROR: Preprocessing failed. Check $LOG_FILE for details."
    exit 1
fi 