#!/bin/bash

# Verifica che il file esista
if [ ! -f "../misc/empty-preprocessed.txt" ]; then
    echo "Errore: il file ../misc/empty-preprocessed.txt non esiste"
    exit 1
fi

# Legge il file riga per riga e esegue lo script per ogni progetto
while IFS= read -r project; do
    # Salta le righe vuote
    [ -z "$project" ] && continue
    
    echo "Elaborazione del progetto: $project"
    python3 genPreproc_fix.py "../repos/$project"
    
    # Aggiunge una pausa tra i progetti per leggibilità
    echo "----------------------------------------"
done < "../misc/empty-preprocessed.txt" 