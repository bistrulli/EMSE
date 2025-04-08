#!/bin/sh

# Verifica che tutti i parametri richiesti siano stati forniti
if [ $# -lt 4 ] || [ $# -gt 5 ]; then
    echo "Usage: $0 <log_file> <kernel_source> <project_dir> <arch> [<single_file>]"
    echo "  <single_file> is optional. If provided, only this file will be processed."
    echo "Example (all project): $0 preproc.log kernel_sources/linux-5.9.9_arm64 projects/dummy_project arm64"
    echo "Example (single file): $0 preproc.log kernel_sources/linux-5.9.9_arm64 projects/dummy_project arm64 src/main.c"
    exit 1
fi

# Parametri di input
LOG_FILE="$1"
KERNEL_SOURCE="$2"
PROJECT_DIR="$3"
ARCH="$4"
SINGLE_FILE=""
if [ $# -eq 5 ]; then
    SINGLE_FILE="$5"
fi

# Livello di log per il preprocessore (10=DEBUG, 20=INFO, ...)
PREPROCESSOR_LOG_LEVEL=20

# Verifica che le directory esistano
if [ ! -d "$KERNEL_SOURCE" ]; then
    echo "ERROR: Kernel source directory not found: $KERNEL_SOURCE"
    exit 1
fi

if [ ! -d "$PROJECT_DIR" ]; then
    echo "ERROR: Project directory not found: $PROJECT_DIR"
    exit 1
fi

# Se è specificato un single_file, verifica che esista
if [ -n "$SINGLE_FILE" ] && [ ! -f "$SINGLE_FILE" ]; then
    echo "ERROR: Single file specified but not found: $SINGLE_FILE"
    exit 1
fi

# Costruisci la stringa dei path di include verificando che esistano
INCLUDE_PATHS_ARGS=""

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
        # Aggiungi il path alla lista per l'argomento --include-paths
        INCLUDE_PATHS_ARGS="$INCLUDE_PATHS_ARGS $abs_dir"
    else
        echo "WARNING: Include directory not found: $dir"
    fi
done

# Esegui il preprocessore
echo "Starting preprocessing..."
echo "Project directory: $PROJECT_DIR"
if [ -n "$SINGLE_FILE" ]; then
    echo "Processing single file: $SINGLE_FILE"
else
    echo "Processing all .c files in project."
fi
echo "Log level: $PREPROCESSOR_LOG_LEVEL"
echo "Include paths passed to preprocessor:"
# Stampa i path che verranno effettivamente passati
for path in $INCLUDE_PATHS_ARGS; do
    echo "  - $path"
done

# Rimuovi il file di log precedente se esiste
rm -f "$LOG_FILE"

# Esegui lo script Python, aggiungendo --single-file se necessario
if [ -n "$SINGLE_FILE" ]; then
    python3 preprocessor_working.py \
        --project-path "$PROJECT_DIR" \
        --log-level "$PREPROCESSOR_LOG_LEVEL" \
        --single-file "$SINGLE_FILE" \
        --include-paths $INCLUDE_PATHS_ARGS >> "$LOG_FILE" 2>&1
else
    python3 preprocessor_working.py \
        --project-path "$PROJECT_DIR" \
        --log-level "$PREPROCESSOR_LOG_LEVEL" \
        --include-paths $INCLUDE_PATHS_ARGS >> "$LOG_FILE" 2>&1
fi

# Controlla il risultato
EXIT_CODE=$?
if [ $EXIT_CODE -eq 0 ]; then
    echo "Preprocessing completed successfully!"
    # Mostra il resoconto dal log (INFO level)
    echo "Summary:"
    grep "Successfully processed:" "$LOG_FILE"
    grep "Skipped:" "$LOG_FILE"
else
    echo "ERROR: Preprocessing failed with exit code $EXIT_CODE. Check $LOG_FILE for details."
    # Mostra le ultime righe del log in caso di errore
    echo "Last lines from log ($LOG_FILE):"
    tail -n 20 "$LOG_FILE"
    exit 1
fi 