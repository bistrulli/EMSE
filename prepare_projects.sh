#!/bin/bash

# Verifica che siano stati forniti tutti i parametri
if [ $# -ne 3 ]; then
    echo "Usage: $0 <base_dir> <input_file> <dest_dir>"
    echo "Example: $0 /path/to/projects projects.txt /path/to/destination"
    exit 1
fi

BASE_DIR="$1"
INPUT_FILE="$2"
DEST_DIR="$3"

# Verifica che la directory base esista
if [ ! -d "$BASE_DIR" ]; then
    echo "ERROR: Base directory not found: $BASE_DIR"
    exit 1
fi

# Verifica che il file di input esista
if [ ! -f "$INPUT_FILE" ]; then
    echo "ERROR: Input file not found: $INPUT_FILE"
    exit 1
fi

# Crea la directory di destinazione se non esiste
mkdir -p "$DEST_DIR"

# Leggi il file riga per riga e copia ogni directory
while IFS= read -r line; do
    # Salta le righe vuote
    [ -z "$line" ] && continue
    
    # Rimuovi eventuali spazi o caratteri speciali
    dir_name=$(echo "$line" | tr -d '\r' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    
    # Costruisci il percorso completo
    full_path="$BASE_DIR/$dir_name"
    
    # Verifica che la directory sorgente esista
    if [ -d "$full_path" ]; then
        echo "Copying $full_path to $DEST_DIR/"
        cp -ar "$full_path" "$DEST_DIR/"
    else
        echo "WARNING: Directory not found: $full_path"
    fi
done < "$INPUT_FILE"

echo "Copy completed!" 