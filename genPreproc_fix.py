#!/usr/bin/env python3
"""
Script di preprocessing per file C.

Data una directory di progetto (contenente file .c e .h), lo script:
  - Verifica gli argomenti in input (directory principale e, opzionalmente, file o sottocartella)
  - Cerca ricorsivamente i file .c (escludendo eventuali symlink)
  - Copia l'intero progetto in una directory di destinazione
  - Raccoglie tutte le directory che contengono file header (*.h) (inclusi alcuni path di sistema)
  - Per ciascun file .c esegue il preprocessing tramite il comando "cpp" aggiungendo i percorsi di include
  - Salva l'output preprocessato e logga eventuali errori o avvisi
"""

import sys
import os
import subprocess
import shutil
import glob
import time
import re
import argparse
from pathlib import Path

# Impostazioni globali
VERBOSE = True
SAVE_LOGS = True
PRINT_LOGS = True
LOG_FILENAME = 'preproc.log'
PREPROC_DIR = 'preprocessed_bug'
HOME_DIR = '/workspace/EMSE'

# ------------------------------------------------------------------------------
# Funzione per stampare una barra di avanzamento sulla console
# ------------------------------------------------------------------------------
def print_progress_bar(iteration, total, prefix='', suffix='', length=50, fill='█'):
    """
    Stampa una barra di avanzamento nel terminale.

    :param iteration: iterazione corrente
    :param total: numero totale di iterazioni
    :param prefix: testo da visualizzare prima della barra
    :param suffix: testo da visualizzare dopo la barra
    :param length: lunghezza della barra in caratteri
    :param fill: carattere usato per la parte "riempita" della barra
    """
    ratio = f"{iteration}/{total}"
    filled_length = int(length * iteration // total)
    bar = fill * filled_length + '-' * (length - filled_length)
    print(f'\r{prefix} |{bar}| {ratio} {suffix}', end='\r')
    if iteration == total:
        print()


# ------------------------------------------------------------------------------
# Funzione per scrivere messaggi di log sia su file che a video
# ------------------------------------------------------------------------------
def log_message(message: str, dest_folder: str):
    log_file = Path(dest_folder) / LOG_FILENAME
    if SAVE_LOGS:
        with open(log_file, 'a') as f:
            f.write(message + '\n')
    if PRINT_LOGS:
        print(message)


# ------------------------------------------------------------------------------
# Funzione per raccogliere le directory degli header presenti nel progetto
# ------------------------------------------------------------------------------
def get_all_project_headers(project_path: str):
    """
    Raccoglie le directory che contengono file header (*.h) all'interno del progetto.
    Aggiunge inoltre alcune directory di sistema standard.

    :param project_path: percorso principale del progetto
    :return: lista di directory da usare come include per il preprocessing
    """
    # Eseguiamo il comando "find" per cercare i file .h
    try:
        result = subprocess.check_output(
            ["find", project_path, "-type", "f", "-name", "*.h"],
            universal_newlines=True
        )
    except subprocess.CalledProcessError:
        result = ""
    # Otteniamo i percorsi delle directory in cui si trovano gli header
    header_dirs = {str(Path(header).parent) for header in result.splitlines() if header}
    
    # Directory di header di sistema (aggiunte manualmente)
    system_headers = {
        "/usr/include",
        "/usr/local/include",
        "/opt/include",
        "/usr/include/X11",
        "/usr/include/asm",
        "/usr/include/linux",
        "usr/include/ncurses"
    }
    
    # Directory specifiche per ESP32 e LVGL
    esp32_headers = {
        # Aggiungi qui i percorsi delle directory che contengono gli header di LVGL
        # Per esempio:
        # "/path/to/lvgl/include",
        # "/path/to/esp32/include"
    }
    
    # Unisci tutte le directory
    header_dirs = header_dirs.union(system_headers).union(esp32_headers)
    return list(header_dirs)


# ------------------------------------------------------------------------------
# Funzione per preprocessare un file C utilizzando cpp
# ------------------------------------------------------------------------------
def preprocess_file(c_file: str, include_dirs: list, dest_folder: str, include_id: int) -> bool:
    """
    Preprocessa il file C usando il comando "cpp" e scrive l'output preprocessato
    e eventuali errori in file separati.

    :param c_file: percorso del file C da preprocessare
    :param include_dirs: lista di directory da includere (opzione -I)
    :param dest_folder: cartella di destinazione per i file preprocessati
    :param include_id: identificatore progressivo per generare nomi univoci dei file
    :return: True se il preprocessing è andato a buon fine, False altrimenti
    """
    # Costruiamo i nomi dei file di output nella cartella del progetto
    base_name = Path(c_file).with_suffix('').name
    out_file = Path(dest_folder) / f"{base_name}_{include_id}.i"
    err_file = Path(dest_folder) / f"{base_name}_{include_id}.err"
    resp_file = Path(dest_folder) / f"{base_name}_{include_id}.resp"

    # Creiamo il file di risposta con le directory di include
    with open(resp_file, 'w') as f:
        for inc in include_dirs:
            f.write(f"-I{inc}\n")

    # Costruiamo il comando cpp usando il file di risposta
    cmd = ['cpp', f'@{resp_file}', c_file]
    
    # Aggiungiamo flag di debug per cpp
    cmd.extend(['-v', '-dD'])
    
    start_time = time.time()
    
    # Eseguiamo il comando e catturiamo l'output
    try:
        result = subprocess.run(cmd, 
                              stdout=subprocess.PIPE, 
                              stderr=subprocess.PIPE,
                              text=True)
        
        # Rimuoviamo il file di risposta
        resp_file.unlink(missing_ok=True)
        
        # Scriviamo l'output e gli errori nei file
        with open(out_file, 'w') as fout:
            fout.write(result.stdout)
        with open(err_file, 'w') as ferr:
            ferr.write(result.stderr)
            
        duration = time.time() - start_time

        # Se ci sono errori, scriviamoli nel file di log
        if result.stderr:
            log_message(f"\nErrori dettagliati per {c_file}:", dest_folder)
            log_message("-" * 80, dest_folder)
            log_message(result.stderr, dest_folder)
            log_message("-" * 80, dest_folder)
            
        # Se il file di errori contiene messaggi di include mancanti, consideriamo il preprocessing fallito
        if err_file.stat().st_size > 0:
            with open(err_file, 'r') as f:
                error_content = f.read()
            if '#include' in error_content:
                # Rimuoviamo i file generati se ci sono errori critici
                out_file.unlink(missing_ok=True)
                err_file.unlink(missing_ok=True)
                log_message(f"ERROR: Preprocessing di {c_file} fallito.\nComando: {' '.join(cmd)}\nDurata: {duration:.2f} sec", dest_folder)
                return False
            else:
                log_message(f"WARNING: Preprocessing di {c_file} completato con avvisi.\nComando: {' '.join(cmd)}\nDurata: {duration:.2f} sec", dest_folder)
                return True
        else:
            log_message(f"COMPLETED: Preprocessing di {c_file} riuscito.\nComando: {' '.join(cmd)}\nDurata: {duration:.2f} sec", dest_folder)
            err_file.unlink(missing_ok=True)  # rimuoviamo il file degli errori se vuoto
            return True
            
    except subprocess.CalledProcessError as e:
        # Rimuoviamo il file di risposta in caso di errore
        resp_file.unlink(missing_ok=True)
        
        log_message(f"\nErrore nell'esecuzione del comando per {c_file}:", dest_folder)
        log_message(f"Exit code: {e.returncode}", dest_folder)
        log_message(f"Output: {e.output}", dest_folder)
        log_message(f"Error: {e.stderr}", dest_folder)
        log_message("-" * 80, dest_folder)
        return False


# ------------------------------------------------------------------------------
# Funzione principale
# ------------------------------------------------------------------------------
def main():
    # Configurazione del parser degli argomenti
    parser = argparse.ArgumentParser(
        description='Script di preprocessing per file C',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument('project_dir', 
                       type=str,
                       help='La directory principale contenente i file C e header')
    
    parser.add_argument('target', 
                       type=str,
                       nargs='?',
                       help='[Opzionale] La sottocartella o un file C specifico da preprocessare')
    
    parser.add_argument('-v', '--verbose',
                       action='store_true',
                       help='Abilita la modalità verbose per log più dettagliati')
    
    args = parser.parse_args()

    # Verifica che il primo parametro sia una directory esistente
    project_dir = Path(args.project_dir).resolve()
    if not project_dir.is_dir():
        print("Il primo parametro deve essere una directory esistente.")
        sys.exit(-1)

    # Se è fornito un secondo parametro, può essere un file C o una directory
    if args.target:
        second_param = Path(args.target).resolve()
        if second_param.is_file():
            if second_param.suffix != '.c':
                print("Se il secondo parametro è un file, deve essere un file C (.c).")
                sys.exit(-1)
            c_files = [str(second_param)]
        elif second_param.is_dir():
            # Cerchiamo ricorsivamente i file .c nella sottocartella
            c_files = [str(p) for p in second_param.rglob('*.c')]
        else:
            print("Il secondo parametro deve essere una directory o un file esistente.")
            sys.exit(-1)
    else:
        # Se non viene fornito un secondo parametro, cerchiamo i file .c nella directory principale
        c_files = [str(p) for p in project_dir.rglob('*.c')]

    # Impostiamo la modalità verbose se richiesta
    global PRINT_LOGS
    PRINT_LOGS = args.verbose

    # Rimuoviamo eventuali symlink dai file trovati
    c_files = [f for f in c_files if not os.path.islink(f)]
    total_files = len(c_files)
    if total_files == 0:
        print("Nessun file C trovato.")
        sys.exit(0)

    # Prepariamo la cartella di destinazione copiando l'intero progetto
    dest_folder = Path(HOME_DIR) / PREPROC_DIR / project_dir.name
    if dest_folder.exists():
        print(f"La cartella {dest_folder} esiste già. Eliminala o rinominala.")
        sys.exit(-1)
    shutil.copytree(str(project_dir), str(dest_folder), symlinks=True,
                    # Ignoriamo i file (lasciamo le directory) per preservare la struttura
                    ignore=lambda d, files: [f for f in files if Path(d, f).is_file()])
    # Modifichiamo i permessi della cartella di destinazione
    os.system(f"chmod -R 777 {dest_folder}")

    # Raccogliamo tutte le directory degli header dal progetto e di sistema
    header_dirs = get_all_project_headers(str(project_dir))

    print(f"Trovati {total_files} file C. Avvio del preprocessing...")
    start_time = time.time()
    # Elaborazione di ogni file C
    for idx, c_file in enumerate(c_files, start=1):
        print_progress_bar(idx, total_files, prefix="Preprocessing:", suffix=project_dir.name)
        preprocess_file(c_file, header_dirs, str(dest_folder), idx)
    # Log finale con il tempo totale impiegato
    end_time = time.time()
    log_message("-------------", str(dest_folder))
    log_message(f"Tempo totale: {end_time - start_time:.2f} secondi", str(dest_folder))


if __name__ == '__main__':
    main()
