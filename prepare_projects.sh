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

# Verifica che BASE_DIR e DEST_DIR siano directory diverse
if [ "$(realpath "$BASE_DIR")" = "$(realpath "$DEST_DIR")" ]; then
    echo "ERROR: Base directory and destination directory cannot be the same"
    exit 1
fi

# Verifica che DEST_DIR non sia una sottodirectory di BASE_DIR
if [[ "$(realpath "$DEST_DIR")" == "$(realpath "$BASE_DIR")"/* ]]; then
    echo "ERROR: Destination directory cannot be a subdirectory of base directory"
    exit 1
fi

# Crea la directory di destinazione se non esiste
mkdir -p "$DEST_DIR"

# Conta il numero totale di righe non vuote nel file di input
total_lines=$(grep -c '[^[:space:]]' "$INPUT_FILE")

# Contatori per le statistiche
current=0
copied=0
skipped=0
not_found=0

# Funzione per aggiornare la barra di progresso
update_progress() {
    local current=$1
    local total=$2
    local width=50
    local percentage=$((current * 100 / total))
    local completed=$((current * width / total))
    local remaining=$((width - completed))
    
    printf "\rProgress: [%${completed}s%${remaining}s] %d%%" "" "" "$percentage"
}

# Leggi il file riga per riga e copia ogni directory
while IFS= read -r line; do
    # Salta le righe vuote
    [ -z "$line" ] && continue
    
    # Incrementa il contatore corrente
    ((current++))
    
    # Aggiorna la barra di progresso
    update_progress "$current" "$total_lines"
    
    # Rimuovi eventuali spazi o caratteri speciali
    dir_name=$(echo "$line" | tr -d '\r' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    
    # Costruisci i percorsi completi
    full_path="$BASE_DIR/$dir_name"
    dest_path="$DEST_DIR/$dir_name"
    
    # Verifica che la directory sorgente esista
    if [ -d "$full_path" ]; then
        # Verifica se la directory di destinazione esiste già
        if [ -d "$dest_path" ]; then
            ((skipped++))
        else
            cp -rdp "$full_path" "$DEST_DIR/"
            ((copied++))
        fi
    else
        ((not_found++))
    fi
done < "$INPUT_FILE"

# Aggiungi una nuova linea dopo la barra di progresso
echo

echo "Copy completed!"
echo "Statistics:"
echo "- Total projects processed: $total_lines"
echo "- Successfully copied: $copied"
echo "- Skipped (already exist): $skipped"
echo "- Not found: $not_found" 