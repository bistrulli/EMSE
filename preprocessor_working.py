#!/usr/bin/env python3
import os
import shutil
import subprocess
import re
import argparse
import tempfile
import logging
from pathlib import Path
from typing import List, Optional, Tuple, Dict
import uuid
import cProfile
import pstats
import sys
import gc
import time

def setup_logger(log_level=logging.INFO):
    """
    Configura e restituisce un logger globale per l'applicazione.
    
    Args:
        log_level: Il livello di logging (default: INFO)
    
    Returns:
        Un logger configurato
    """
    # Crea il logger
    logger = logging.getLogger("preprocessor")
    logger.setLevel(log_level)
    
    # Crea un handler per lo stdout
    handler = logging.StreamHandler()
    handler.setLevel(log_level)
    
    # Crea un formatter per i messaggi
    formatter = logging.Formatter('%(levelname)s: %(message)s')
    handler.setFormatter(formatter)
    
    # Aggiungi l'handler al logger
    logger.addHandler(handler)
    
    return logger

def parse_arguments():
    parser = argparse.ArgumentParser(description='Preprocess C files in a project')
    parser.add_argument('--project-path', '-p', help='Path to the C project')
    parser.add_argument('--single-file', '-f', help='Path to a single C file to preprocess (can be used with --project-path)')
    parser.add_argument('--include-paths', '-i', nargs='+', default=['/usr/include'], help='System include paths')
    parser.add_argument('--clean-temp', action='store_true', help='Clean temporary directory after each file')
    parser.add_argument('--log-level', '-l', type=int, default=20, 
                        help='Logging level (0-50): 0=NOTSET, 10=DEBUG, 20=INFO, 30=WARNING, 40=ERROR, 50=CRITICAL')
    return parser.parse_args()

def setup_directories(project_path: str) -> Path:
    """
    Crea una directory temporanea.
    Ritorna temp_dir
    """
    logger = logging.getLogger("preprocessor")
    
    # Crea una directory temporanea con il nome del progetto
    temp_base = Path('/dev/shm')
    temp_dir = None
    max_attempts = 10
    attempt = 0
    
    while attempt < max_attempts:
        try:
            # Usa il nome del progetto nella directory temporanea
            project_name = Path(project_path).name
            temp_name = f'preprocessor_{project_name}'
            temp_dir = temp_base / temp_name
            
            # Prova a creare la directory
            temp_dir.mkdir(exist_ok=False)
            
            # Imposta i permessi corretti
            temp_dir.chmod(0o777)
            
            break
        except (PermissionError, OSError) as e:
            logger.warning(f"Could not create temporary directory in /dev/shm: {e}")
            # Fallback su una directory temporanea nel filesystem normale
            temp_dir = Path(tempfile.mkdtemp(prefix=f"preprocessor_{project_name}_"))
            break
        except Exception as e:
            logger.warning(f"Unexpected error creating temporary directory: {e}")
            attempt += 1
    
    if temp_dir is None:
        raise RuntimeError("Failed to create temporary directory after multiple attempts")
    
    return temp_dir

def find_c_files(project_path: str) -> List[Path]:
    """Trova tutti i file .c nel progetto usando find."""
    # Questa funzione non è più necessaria, sostituita da find_source_files_and_build_map
    pass # O rimuoverla completamente

def extract_missing_info(error_message: str, debug: bool = False) -> Optional[Tuple[str, bool, Optional[str]]]:
    """Estrae il nome del file mancante, se è di sistema, e il file che lo includeva dall'output di errore di cpp.
    
    Returns:
        Tuple: (nome_file_mancante, is_system, includer_file_path) o None se non trovato.
        includer_file_path può essere None se non è stato possibile estrarlo.
    """
    logger = logging.getLogger("preprocessor")
    
    if not error_message:
        return None

    # Pattern principale per estrarre il nome del file mancante
    # Nota: nel messaggio di errore il nome del file appare SENZA virgolette
    # es: "fatal error: itoa.h: No such file or directory"
    missing_file_pattern = re.compile(r'fatal error: ([^:]+): No such file or directory')
    
    # Pattern per distinguere tra include di sistema e di progetto
    # es: #include "file.h" vs #include <file.h>
    include_line_pattern = re.compile(r'#include\s+([<"])(.*?)[>"]')
    
    missing_file = None
    is_system = False
    includer_file_path = None

    # 1. Trova il nome del file mancante dalla riga "fatal error"
    match = missing_file_pattern.search(error_message)
    if not match:
        logger.debug(f"""Could not find missing file pattern in error message:
{error_message[:500]}...""")
        return None
        
    # Estrai il nome del file mancante
    missing_file = match.group(1).strip()
    
    # 2. Determina se è un include di sistema cercando la riga effettiva dell'include
    # Cerca righe come: '#include "file.h"' o '#include <file.h>'
    include_match = include_line_pattern.search(error_message)
    if include_match:
        delimiter, include_path = include_match.groups()
        # Se il delimitatore è '<', allora è un include di sistema
        is_system = (delimiter == '<')
        
        # Verifica che il nome del file estratto corrisponda al path dell'include
        # Il path nell'include potrebbe essere più completo (es. "dir/file.h")
        if include_path.endswith(missing_file):
            # Il nome estratto corrisponde alla fine del path, tutto ok
            pass
        elif Path(include_path).name == missing_file:
            # I nomi base corrispondono, tutto ok
            pass
        else:
            logger.debug(f"Warning: Extracted file name '{missing_file}' doesn't match include path '{include_path}'")
    else:
        # Non abbiamo trovato la riga dell'include, assumiamo che non sia di sistema
        logger.debug(f"Could not find include line pattern, assuming it's a project dependency")
    
    # 3. Trova il file che include quello mancante
    # Cerca il pattern '/path/to/file.c:line:col: fatal error:'
    includer_line_pattern = re.compile(r'^([^:]+):\d+:\d+: fatal error:')
    lines = error_message.splitlines()
    found_includer = False
    
    for line in lines:
        if 'fatal error:' in line and missing_file in line:
            match = includer_line_pattern.match(line)
            if match:
                includer_file_path = match.group(1).strip()
                found_includer = True
                logger.debug(f"Found includer: '{includer_file_path}' from line: '{line.strip()}'")
                break
    
    if not found_includer:
        logger.debug(f"Could not determine the includer file path for '{missing_file}'")
    
    logger.debug(f"Final extracted -> Missing: '{missing_file}', System: {is_system}, Includer: '{includer_file_path}'")
    
    return missing_file, is_system, includer_file_path

def debug_print(message: str, debug: bool = False) -> None:
    """Print a debug message if debug mode is enabled."""
    if debug:
        logger = logging.getLogger("preprocessor")
        logger.debug(message)

def find_file(filename: str, from_file: str, include_paths: List[Path], project_path: Path, debug: bool = False) -> Optional[Path]:
    # Questa funzione non è più necessaria, sostituita da find_file_from_map
    pass

def search_file_in_project(filename: str, project_path: Path, debug: bool = False) -> Optional[Path]:
    # Questa funzione non è più necessaria, incorporata in find_source_files_and_build_map e find_file_from_map
    pass

def read_file_with_fallback_encoding(file_path: Path) -> str:
    """Legge un file provando diverse codifiche comuni."""
    logger = logging.getLogger("preprocessor")
    encodings = ['utf-8', 'latin-1', 'cp1252']
    for enc in encodings:
        try:
            return file_path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
        except Exception as e:
            # Gestisci altri possibili errori di lettura
            logger.warning(f"Error reading {file_path} with {enc}: {e}")
            break # Interrompi se c'è un errore diverso dalla decodifica
    # Se tutte le codifiche falliscono, solleva un errore o restituisci una stringa vuota
    logger.error(f"Could not decode file {file_path} with any known encoding.")
    # Potresti voler sollevare un'eccezione qui invece di restituire una stringa vuota
    # raise IOError(f"Could not decode file {file_path}")
    return "" # O restituisci una stringa vuota per provare a continuare

def update_includes(file_to_update: Path, missing_file_base_name: str, debug: bool = False) -> bool:
    """Aggiorna gli include nel file specificato per usare il nome base del file mancante.
    Si ferma dopo aver trovato e modificato la prima corrispondenza.
    
    Args:
        file_to_update: Path del file da modificare (nella directory temporanea).
        missing_file_base_name: Nome base del file mancante (es. 'lv_conf.h').
        debug: Se True, mostra informazioni di debug dettagliate.
        
    Returns:
        True se il file è stato modificato, False altrimenti.
    """
    logger = logging.getLogger("preprocessor")
    
    if not file_to_update or not file_to_update.exists():
        logger.debug(f"update_includes - File to update does not exist: {file_to_update}")
        return False
        
    logger.debug(f"Updating includes in {file_to_update.name} for base name: {missing_file_base_name}")
    
    try:
        content_lines = read_file_with_fallback_encoding(file_to_update).splitlines()
    except Exception as e:
        logger.debug(f"Error reading file {file_to_update} for update: {e}")
        return False
        
    new_content_lines = []
    updated = False
    # Match #include "..." - cattura solo il path interno alle virgolette
    include_pattern = re.compile(r'^(\s*#include\s+")([^>]+)(")') 

    for line_num, line in enumerate(content_lines):
        match = include_pattern.match(line)
        original_line = line
        
        if match:
            prefix, included_path, suffix = match.groups()
            # Prendiamo il nome base del path trovato nell'include
            included_base_name = Path(included_path).name 
            
            logger.debug(f"Line {line_num+1}: Checking include: '{original_line.strip()}'")
            logger.debug(f"  Extracted path: '{included_path}' -> Base name: '{included_base_name}'")
            logger.debug(f"  Comparing with missing base name: '{missing_file_base_name}'")

            # Confronta SOLO il nome base
            if included_base_name == missing_file_base_name:
                logger.debug(f"  Base names match!")
                # Ricostruisci la linea con il nome base appiattito    
                modified_line = f'{prefix}{missing_file_base_name}{suffix}'
                if original_line.strip() != modified_line.strip():
                    logger.debug(f"  Updating line: '{original_line.strip()}' -> '{modified_line.strip()}'")
                    updated = True
                    new_content_lines.append(modified_line) # Aggiungi la linea modificata
                    # *** MODIFICA: Esci dal loop dopo la prima modifica ***
                    # Aggiungi le righe rimanenti non modificate
                    new_content_lines.extend(content_lines[line_num+1:])
                    break # Esce dal for loop
                else:
                    logger.debug(f"  Include already flattened: '{original_line.strip()}'")
                    new_content_lines.append(original_line) # Aggiungi la linea originale (non modificata)
            else:
                logger.debug(f"  Base names DO NOT match.")
                new_content_lines.append(original_line) # Aggiungi la linea originale (non corrispondente)
        else:
             new_content_lines.append(original_line) # Aggiungi la linea non-include

    if updated:
        try:
            # Nota: ora new_content_lines contiene già tutto il necessario
            # grazie all'extend() prima del break
            new_content = '\n'.join(new_content_lines) + '\n' 
            file_to_update.write_text(new_content, encoding='utf-8')
            logger.debug(f"Successfully updated {file_to_update.name} (stopped after first match)")
            return True # Indica che il file è stato modificato
        except Exception as e:
            logger.debug(f"Error writing updated file {file_to_update}: {e}")
            return False # Fallito l'aggiornamento
    else:
        logger.debug(f"No includes needed updating for '{missing_file_base_name}' in {file_to_update.name}")
        
    # Se siamo arrivati qui senza 'updated' True, significa che il loop è terminato
    # normalmente senza trovare un match modificabile, oppure non ci sono stati match.
    # Non è necessaria alcuna scrittura in questo caso.
    return False # Nessuna modifica effettuata o necessaria

def run_cpp_m(file_path: Path, include_paths: List[Path], debug: bool = False) -> Tuple[bool, Optional[str]]:
    """
    Esegue cpp -M sul file e ritorna (success, error_message).
    """
    logger = logging.getLogger("preprocessor")
    start_time = time.time()
    cmd = ['cpp', '-M'] + [f'-I{p}' for p in include_paths] + [str(file_path)]
    
    logger.debug(f"Running cpp -M command: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        end_time = time.time()
        
        logger.debug(f"cpp -M command completed in {end_time - start_time:.6f} seconds")
        logger.debug(f"cpp -M return code: {result.returncode}")
        
        if result.stderr:
            logger.debug(f"cpp -M stderr: {result.stderr[:500]}...")  # Mostra primi 500 caratteri
        
        return result.returncode == 0, result.stderr if result.stderr else None
    except subprocess.SubprocessError as e:
        logger.debug(f"cpp -M exception: {str(e)}")
        return False, str(e)

def run_cpp_e(file_path: Path, include_paths: List[Path], debug: bool = False) -> Tuple[bool, str, Optional[str]]:
    """
    Esegue cpp -E sul file e ritorna (success, stdout_content, error_message).
    """
    logger = logging.getLogger("preprocessor")
    start_time = time.time()
    cmd = ['cpp', '-E'] + [f'-I{p}' for p in include_paths] + [str(file_path)]
    
    logger.debug(f"Running cpp -E command: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        end_time = time.time()
        
        logger.debug(f"cpp -E command completed in {end_time - start_time:.6f} seconds")
        logger.debug(f"cpp -E return code: {result.returncode}")
        
        if result.stderr:
            logger.debug(f"cpp -E stderr: {result.stderr[:500]}...")  # Mostra primi 500 caratteri
        
        stdout_size = len(result.stdout) if result.stdout else 0
        logger.debug(f"cpp -E stdout size: {stdout_size} bytes")
        
        return (
            result.returncode == 0,
            result.stdout if result.stdout else "",
            result.stderr if result.stderr else None
        )
    except subprocess.SubprocessError as e:
        logger.debug(f"cpp -E exception: {str(e)}")
        return False, "", str(e)

def replace_temp_paths_in_output(content: str, temp_to_original_map: Dict[str, str], logger) -> str:
    """
    Sostituisce i percorsi temporanei nelle direttive #line con i percorsi originali.

    Args:
        content: Il contenuto del file preprocessato (output di cpp -E).
        temp_to_original_map: Dizionario che mappa i percorsi temporanei ai percorsi originali assoluti.
        logger: L'oggetto logger per registrare informazioni.

    Returns:
        Il contenuto con i percorsi sostituiti.
    """
    logger.debug("Replacing temporary paths in #line directives...")
    # Pattern per catturare #line direttive comuni:
    # Es: #line 1 "/tmp/..." ...
    # Es: # 1 "/tmp/..." ...
    line_directive_pattern = re.compile(r'^(#line\s+\d+\s+"|\#\s+\d+\s+")([^"]+)(".*)$')

    new_lines = []
    lines_changed = 0

    for line in content.splitlines():
        match = line_directive_pattern.match(line)
        if match:
            prefix, temp_path, suffix = match.groups()
            if temp_path in temp_to_original_map:
                original_path = temp_to_original_map[temp_path]
                # Ricostruisci la linea con il path originale
                # Assicurati che i backslash in Windows siano escapati per C
                escaped_original_path = original_path.replace('\\', '\\\\')
                new_line = f'{prefix}{escaped_original_path}{suffix}'
                if line != new_line:
                    logger.debug(f"  Replaced: '{temp_path}' -> '{original_path}'")
                    lines_changed += 1
                new_lines.append(new_line)
            else:
                # Path non trovato nella mappa, lascia la linea com'è
                logger.debug(f"  Skipped (not in map): '{temp_path}'")
                new_lines.append(line)
        else:
            # Linea non corrispondente al pattern, lasciala com'è
            new_lines.append(line)

    logger.debug(f"Path replacement complete. {lines_changed} lines modified.")
    # Ricostruisci il contenuto aggiungendo un newline alla fine se c'era nell'originale
    # (splitlines() lo rimuove)
    return '\n'.join(new_lines) + ('\n' if content.endswith('\n') else '')

def clean_temp_directory(temp_dir: Path, debug: bool = False) -> None:
    """
    Pulisce completamente la directory temporanea eliminando tutti i file.
    
    Args:
        temp_dir: Path della directory temporanea
        debug: Se True, usa logging livello debug
    """
    logger = logging.getLogger("preprocessor")
    
    logger.debug(f"Cleaning temporary directory {temp_dir}")
    file_count = sum(1 for _ in temp_dir.iterdir() if _.is_file())
    logger.debug(f"Found {file_count} files to clean")
    
    try:
        # Elimina tutti i file nella directory temporanea
        for file_path in temp_dir.iterdir():
            if file_path.is_file():
                logger.debug(f"Removing file: {file_path.name}")
                file_path.unlink()
                
        # Forza la garbage collection per liberare memoria
        logger.debug(f"Running garbage collection")
        gc.collect()
        
        logger.debug(f"Temporary directory cleaned successfully")
    except Exception as e:
        logger.warning(f"Failed to clean temporary directory: {e}")

def preprocess_file(c_file: Path, project_path: Path, include_paths: List[Path], 
                   temp_dir: Path, file_map: Dict[str, List[Path]], debug: bool = False) -> bool:
    """
    Preprocessa un singolo file C risolvendo le dipendenze mancanti.
    I file .i e .err vengono salvati nella stessa directory del file .c originale.
    Args:
        c_file: Path del file C da processare.
        project_path: Path del progetto (usato meno ora).
        include_paths: Percorsi di include standard (meno usati per lookup).
        temp_dir: Directory temporanea.
        file_map: Mappa precalcolata {nome_base: [lista_path]}.
        debug: Flag per logging di debug.
    Returns:
        True se successo, False altrimenti.
    """
    logger = logging.getLogger("preprocessor")
    total_start_time = time.time()
    
    logger.info(f"\nProcessing {c_file.name}")
    logger.debug(f"Full path: {c_file}")
    logger.debug(f"Project path: {project_path}") # Mantenuto per info
    logger.debug(f"Temporary directory: {temp_dir}")
    logger.debug(f"Include paths: {include_paths}") # Mantenuto per info
    
    # Setup dei path di output nella stessa directory del file .c
    out_path = c_file.with_suffix('.i')
    err_path = c_file.with_suffix('.err')
    
    logger.debug(f"Output paths:")
    logger.debug(f"  .i file: {out_path}")
    logger.debug(f"  .err file: {err_path}")
    
    # Dizionario per mappare i path temporanei ai path originali assoluti
    temp_to_original_map: Dict[str, str] = {}

    # Copia il file .c nella directory temporanea
    copy_start_time = time.time()
    try:
        temp_file = temp_dir / c_file.name
        shutil.copy2(c_file, temp_file)
        temp_file.chmod(0o666)
        # Aggiungi la mappatura per il file sorgente principale
        temp_to_original_map[str(temp_file)] = str(c_file.resolve()) # Usa resolve() per path assoluto
    except Exception as e:
        logger.error(f"Failed: Error copying {c_file.name} to temp directory: {e}")
        return False
    copy_end_time = time.time()
    
    logger.debug(f"Copied source file to temp directory in {copy_end_time - copy_start_time:.6f} seconds")
    logger.debug(f"Temp file: {temp_file}")

    dependency_count = 0
    max_iterations = 5000
    files_updated_in_iteration = set()

    while dependency_count < max_iterations:
        dependency_count += 1
        files_updated_in_iteration.clear()
        
        logger.debug(f"\n=== Dependency resolution iteration {dependency_count} ===")
        
        # Esegui cpp -M sul file .c principale nella directory temporanea
        # Ora passiamo solo la temp_dir come include path per cpp
        success, err_msg = run_cpp_m(temp_file, [temp_dir], debug)
        if success:
            logger.debug(f"cpp -M succeeded, all dependencies resolved for {temp_file.name}")
            break
        
        logger.debug(f"cpp -M failed for {temp_file.name}, trying to extract missing info")
            
        missing_info = extract_missing_info(err_msg, debug)
        if missing_info is None:
            logger.error(f"Failed: preprocessing error (could not extract missing info)")
            if err_msg: err_path.write_text(err_msg)
            return False
        
        missing_file, is_system, includer_file_path_str = missing_info
        missing_file_base_name = Path(missing_file).name
        
        logger.debug(f"Extracted missing: '{missing_file}' (Base: '{missing_file_base_name}'), System: {is_system}, Includer: '{includer_file_path_str}'")
        
        # Non gestiamo più gli include di sistema in questo modo, potrebbero richiedere -I forniti
        if is_system:
            logger.error(f"Failed: missing system dependency <{missing_file}>. Ensure correct system include paths are provided via -I to cpp eventually.")
            if err_msg: err_path.write_text(err_msg)
            return False
        
        # 1. Trova il file sorgente originale per il file mancante USANDO LA MAPPA
        logger.debug(f"Searching map for source of project dependency: {missing_file}")
        search_start_time = time.time()
        
        # Determina il path del file che ha causato l'errore (per dare priorità)
        # Questo file *deve* essere in temp_dir
        includer_in_temp_path = None
        if includer_file_path_str:
             includer_base = Path(includer_file_path_str).name
             potential_path = temp_dir / includer_base
             if potential_path.exists():
                 includer_in_temp_path = potential_path
             else: # Errore grave se non troviamo l'includer che cpp ha menzionato
                 logger.error(f"Logic error: Includer base name '{includer_base}' mentioned by cpp not found in temp dir '{temp_dir}'")
                 # Potremmo fallire qui, ma proviamo a usare il file principale come fallback per la ricerca
                 includer_in_temp_path = temp_file # Fallback rischioso per la ricerca
        else: # Se cpp non dice chi include, usiamo il file principale
             includer_in_temp_path = temp_file
             
        # Cerca usando la mappa
        found_source_file = find_file_from_map(missing_file, includer_in_temp_path, file_map)
        search_end_time = time.time()
        
        logger.debug(f"Map search completed in {search_end_time - search_start_time:.6f} seconds")
            
        if not found_source_file:
            logger.error(f'Failed: missing project dependency "{missing_file}" not found in pre-built map.')
            if err_msg: err_path.write_text(err_msg)
            return False
            
        # 2. Copia il file trovato nella directory temporanea (logica invariata)
        # ... (stesso codice di prima per copiare found_source_file in temp_dir) ...
        temp_dependency_path = temp_dir / missing_file_base_name # Usiamo il nome base qui
        copy_needed = True
        if temp_dependency_path.exists():
            try:
                source_stat = found_source_file.stat()
                temp_stat = temp_dependency_path.stat()
                if temp_stat.st_mtime >= source_stat.st_mtime and temp_stat.st_size == source_stat.st_size:
                    copy_needed = False
                    logger.debug(f"Dependency {missing_file_base_name} already up-to-date in temp dir.")
            except OSError as e:
                logger.debug(f"Error stating files for comparison: {e}")

        if copy_needed:
            copy_dep_start = time.time()
            try:
                shutil.copy2(found_source_file, temp_dependency_path)
                temp_dependency_path.chmod(0o666)
                # *** AGGIUNTA: Mappa il path temporaneo a quello originale assoluto ***
                temp_to_original_map[str(temp_dependency_path)] = str(found_source_file.resolve())
                logger.debug(f"Copied dependency '{found_source_file.name}' to '{temp_dependency_path}'")
                logger.debug(f"  Mapped temp '{temp_dependency_path}' to original '{found_source_file.resolve()}'")
            except Exception as e:
                logger.error(f"Failed: Error copying dependency {found_source_file.name} to temp dir: {e}")
                if err_msg: err_path.write_text(err_msg + f"\nError copying dependency: {e}")
                return False
            copy_dep_end = time.time()
            logger.debug(f"Dependency copy took {copy_dep_end - copy_dep_start:.6f} seconds")

        # 3. Identifica il file da aggiornare nella directory TEMP (logica semplificata da prima)
        file_to_update_in_temp = None
        if includer_file_path_str: 
            includer_basename = Path(includer_file_path_str).name
            potential_includer_in_temp = temp_dir / includer_basename
            if potential_includer_in_temp.exists():
                file_to_update_in_temp = potential_includer_in_temp
            # else: Il controllo sotto fallirà
                           
        if not file_to_update_in_temp: # Manca l'includer o non l'abbiamo trovato
             error_msg = (
                 f"Failed: Could not locate the includer file corresponding to '{includer_file_path_str or 'UNKNOWN'}' "
                 f"within the temporary directory '{temp_dir}' to update include for '{missing_file_base_name}'."
             )
             logger.error(error_msg)
             if err_msg: err_path.write_text(err_msg + "\n" + error_msg)
             return False
        
        # 4. Aggiorna gli include nel file identificato (logica invariata)
        # ... (stesso codice di prima per chiamare update_includes) ...
        logger.debug(f"Attempting to update includes in TEMP file: {file_to_update_in_temp}")
        updated = update_includes(file_to_update_in_temp, missing_file_base_name, debug)
        if updated:
            files_updated_in_iteration.add(file_to_update_in_temp)

    # Fine del loop while (logica invariata)
    if dependency_count >= max_iterations:
        logger.error(f"Failed: Maximum dependency resolution iterations ({max_iterations}) reached.")
        if err_msg: err_path.write_text(err_msg + f"\nMaximum iterations reached.")
        return False

    # Se siamo usciti dal loop con successo, esegui cpp -E finale
    # Ora passiamo solo la temp_dir come include path per cpp
    final_success, final_out, final_err = run_cpp_e(temp_file, [temp_dir], debug)
    
    total_end_time = time.time()
    total_duration = total_end_time - total_start_time
    
    # ... (logica finale invariata: successo/fallimento, scrittura output) ...
    if final_success:
        # *** AGGIUNTA: Sostituisci i path temporanei prima di scrivere ***
        logger.debug("Post-processing successful cpp -E output to replace temporary paths.")
        modified_out = replace_temp_paths_in_output(final_out, temp_to_original_map, logger)

        logger.info(f"Success (resolved {dependency_count-1} dependencies in {total_duration:.2f} seconds)")
        # Scrivi l'output MODIFICATO
        try:
            out_path.write_text(modified_out, encoding='utf-8') # Usa encoding esplicito
            logger.debug(f"Successfully wrote modified .i file to {out_path}")
        except Exception as e:
             logger.error(f"Failed: Error writing final .i file {out_path}: {e}")
             # Anche se la scrittura fallisce, consideriamo il preprocessing riuscito
             # ma logghiamo l'errore. Potremmo voler restituire False qui?
             # Per ora, manteniamo True ma logghiamo.

        if err_path.exists(): err_path.unlink()
        return True
    else:
        logger.error(f"Failed: final preprocessing step (cpp -E) failed after {total_duration:.2f} seconds")
        if final_err: err_path.write_text(final_err)
        return False

def get_project_path(args):
    """Determina il percorso del progetto in base agli argomenti forniti."""
    if args.project_path:
        return Path(args.project_path)
    else:
        # Se solo single-file è specificato, usa la directory del file come project_path
        return Path(args.single_file).parent

def get_files_to_process(args, project_path, debug=False):
    # Questa funzione non è più necessaria per trovare i file .c,
    # ma la manteniamo per gestire il caso --single-file
    logger = logging.getLogger("preprocessor")
    if args.single_file:
        c_file = Path(args.single_file)
        if not c_file.exists() or not c_file.is_file() or c_file.suffix.lower() != '.c':
            logger.error(f"Invalid C file: {args.single_file}")
            sys.exit(1)
        # ... (logica di verifica appartenenza al progetto invariata) ...
        if args.project_path:
            abs_project_path = project_path.resolve()
            abs_c_file = c_file.resolve()
            try:
                rel_path = abs_c_file.relative_to(abs_project_path)
                c_file = abs_c_file
                logger.debug(f"File is inside project at relative path: {rel_path}")
            except ValueError:
                logger.warning(f"Il file {args.single_file} non sembra essere all'interno del progetto {args.project_path}")
                logger.warning("Procedo comunque con l'elaborazione.")
                logger.debug(f"File is not inside project path")
        return [c_file]
    else:
        # Se non è specificato single_file, la lista dei file .c verrà dalla mappa
        return None # Indicherà a main di usare la lista dalla mappa

def log_files_to_process(files_to_process, debug=False):
    """Registra informazioni sui file da processare."""
    logger = logging.getLogger("preprocessor")
    
    logger.debug(f"Found {len(files_to_process)} files to process")

def maybe_clean_temp_directory(temp_dir, clean_temp, file_count, debug=False):
    """Gestisce la pulizia della directory temporanea in base alle condizioni.
    
    Args:
        temp_dir: Directory temporanea da pulire
        clean_temp: Se True, pulisce dopo ogni file
        file_count: Numero totale di file processati (usato per pulizia periodica)
        debug: Flag per il livello di debug
    """
    logger = logging.getLogger("preprocessor")
    
    # Caso 1: Pulizia esplicita richiesta per ogni file
    if clean_temp and temp_dir.exists():
        clean_temp_directory(temp_dir, debug)
        return
        
    # Caso 2: Pulizia periodica ogni 200 file processati
    if temp_dir.exists() and file_count > 0 and file_count % 200 == 0:
        logger.debug("Cleaning temporary directory (periodic cleanup)")
        for file in temp_dir.iterdir():
            if file.is_file():
                file.unlink()

def process_file_with_logging(index, total, c_file, project_path, include_paths, temp_dir, file_map, debug):
    # Aggiunto file_map come argomento
    """Processa un singolo file con gestione appropriata del logging.
    
    Args:
        index: Indice del file corrente (per logging)
        total: Numero totale di file
        c_file: Path del file da processare
        project_path: Path del progetto
        include_paths: Lista dei percorsi per include
        temp_dir: Directory temporanea
        file_map: Mappa pre-calcolata {nome_base: [lista_path]}.
        debug: Flag per il livello di debug
        
    Returns:
        True se il preprocessing è avvenuto con successo, False altrimenti
    """
    logger = logging.getLogger("preprocessor")
    logger.debug(f"\n=== Processing file {index+1}/{total} ===")
    
    try:
        # Passa file_map a preprocess_file
        return preprocess_file(c_file, project_path, include_paths, temp_dir, file_map, debug)
    except Exception as e:
        logger.error(f"Error processing file: {e}")
        if debug:
            import traceback
            logger.debug("Exception traceback:")
            logger.debug(traceback.format_exc())
        return False

def process_files(files_to_process, project_path, include_paths, temp_dir, file_map, clean_temp=False, debug=False):
    # Aggiunto file_map come argomento
    """Esegue il preprocessing di tutti i file nella lista.
    
    Args:
        files_to_process: Lista dei file da processare
        project_path: Path del progetto
        include_paths: Lista dei percorsi per include (meno usati ora)
        temp_dir: Directory temporanea
        file_map: Mappa pre-calcolata {nome_base: [lista_path]}.
        clean_temp: Se True, pulisce la directory temp dopo ogni file
        debug: Flag per attivare output di debug dettagliato
        
    Returns:
        Tuple con (file processati con successo, file saltati)
    """
    logger = logging.getLogger("preprocessor")
    
    # Inizializza contatori
    successful = 0
    failed = 0
    total_files = len(files_to_process)
    
    logger.info(f"Processing {total_files} files...")
    
    # Processa ogni file
    for i, c_file in enumerate(files_to_process):
        # Passa file_map a process_file_with_logging
        success = process_file_with_logging(
            i, total_files, c_file, project_path, include_paths, temp_dir, file_map, debug
        )
        
        # Aggiorna contatori
        if success:
            successful += 1
        else:
            failed += 1
            
        # Gestisci pulizia temporanea
        maybe_clean_temp_directory(temp_dir, clean_temp, successful + failed, debug)
    
    return successful, failed

def find_source_files_and_build_map(project_path: Path) -> Tuple[List[Path], Dict[str, List[Path]]]:
    """Trova tutti i file .c e .h nel progetto e costruisce una mappa.

    Args:
        project_path: Path radice del progetto.

    Returns:
        Una tupla contenente:
        - Lista dei file .c trovati (per il processing).
        - Dizionario mappa: {nome_base_file: [lista_di_path_completi]}.
    """
    logger = logging.getLogger("preprocessor")
    logger.debug(f"Scanning project '{project_path}' for .c and .h files...")
    file_map: Dict[str, List[Path]] = {}
    c_files_list: List[Path] = []
    
    # Usiamo find per efficienza su progetti grandi
    # Trova sia .c che .h, escludendo directory nascoste come .git
    cmd = [
        'find', str(project_path),
        '(', '-name', '.git', '-o', '-name', '.svn', '-o', '-name', '.hg', ')', '-prune',
        '-o', 
        '(', '-name', '*.c', '-o', '-name', '*.h', ')', '-print'
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        all_files = [Path(p) for p in result.stdout.strip().split('\n') if p]
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logger.error(f"Error running find command: {e}")
        # Potremmo voler uscire qui o restituire valori vuoti
        return [], {}
        
    logger.debug(f"Found {len(all_files)} total source files (.c/.h). Building map...")

    for file_path in all_files:
        base_name = file_path.name
        if base_name not in file_map:
            file_map[base_name] = []
        file_map[base_name].append(file_path)
        
        if file_path.suffix.lower() == '.c':
            c_files_list.append(file_path)
            
    logger.debug(f"Map built with {len(file_map)} unique filenames.")
    return c_files_list, file_map

def find_file_from_map(filename_to_find: str, 
                       from_file_path: Path, 
                       file_map: Dict[str, List[Path]]) -> Optional[Path]:
    """Trova un file usando la mappa pre-calcolata, dando priorità alla vicinanza.

    Args:
        filename_to_find: Nome del file da cercare (può contenere path relativo).
        from_file_path: Path del file che contiene l'include (per priorità).
        file_map: La mappa {nome_base: [lista_path]} pre-calcolata.

    Returns:
        Il Path del file trovato più probabile, o None se non trovato.
    """
    logger = logging.getLogger("preprocessor")
    source_dir = from_file_path.parent
    base_filename = Path(filename_to_find).name

    # 1. Tentativo con path relativo (se fornito)
    if '/' in filename_to_find or '\\' in filename_to_find:
        try:
            relative_path_attempt = (source_dir / filename_to_find).resolve()
            if relative_path_attempt.exists():
                 # Verifichiamo se questo path risolto è effettivamente nella mappa?
                 # Potrebbe essere un file generato o non tracciato? Per ora, se esiste, lo usiamo.
                 logger.debug(f"Found dependency '{filename_to_find}' via relative path: {relative_path_attempt}")
                 return relative_path_attempt
        except Exception as e: # Es. per resolve() su path non validi
             logger.debug(f"Could not resolve relative path '{filename_to_find}' from '{source_dir}': {e}")

    # 2. Ricerca del nome base nella mappa
    if base_filename not in file_map:
        logger.debug(f"Base filename '{base_filename}' not found in the pre-built map.")
        return None

    possible_paths = file_map[base_filename]

    # 3. Selezione basata sulla priorità
    if len(possible_paths) == 1:
        logger.debug(f"Found unique match for '{base_filename}' in map: {possible_paths[0]}")
        return possible_paths[0]
    else:
        logger.debug(f"Found {len(possible_paths)} potential matches for '{base_filename}'. Prioritizing...")
        # Priorità 1: Stessa directory del file che include
        same_dir_path = source_dir / base_filename
        for p in possible_paths:
            if p == same_dir_path:
                logger.debug(f"Prioritized match in same directory: {p}")
                return p
        
        # Priorità 2: (Opzionale - Prossimità) - Per ora, prendiamo il primo
        # Si potrebbe implementare un calcolo di distanza basato su common path
        logger.debug(f"No match in same directory. Selecting first found: {possible_paths[0]}")
        return possible_paths[0] # Ritorna il primo trovato da 'find'

def main():
    args = parse_arguments()
    
    # Configura il livello di logging (assicura che sia nell'intervallo valido)
    log_level = max(0, min(50, args.log_level))
    
    # Inizializza il logger
    logger = setup_logger(log_level)
    
    if log_level <= logging.DEBUG:
        logger.debug("=== DEBUG MODE ENABLED ===")
        logger.debug(f"Arguments: {args}")
    
    # Verifica che almeno uno tra project-path e single-file sia specificato
    if not args.project_path and not args.single_file:
        logger.error("ERROR: Devi specificare almeno uno tra --project-path e --single-file")
        sys.exit(1)
    
    # Determina il project_path
    project_path = get_project_path(args)
    
    logger.debug(f"Using project path: {project_path}")
    
    # Costruisci la mappa e ottieni la lista dei file .c
    c_files_list_from_map, file_map = find_source_files_and_build_map(project_path)
    
    # Determina i file da processare
    files_to_process = get_files_to_process(args, project_path, log_level <= logging.DEBUG)
    if files_to_process is None:
        # Se non è stato specificato --single-file, usa la lista dalla mappa
        files_to_process = c_files_list_from_map
        
    log_files_to_process(files_to_process, log_level <= logging.DEBUG) # Logga il numero
    
    # Setup directory temporanea
    temp_dir = setup_directories(str(project_path))
    
    logger.debug(f"Created temporary directory: {temp_dir}")
    
    try:
        # Preprocessa i file
        processed, skipped = process_files(
            files_to_process, 
            project_path, 
            args.include_paths, 
            temp_dir, 
            file_map, # Passa la mappa qui
            args.clean_temp, 
            log_level <= logging.DEBUG
        )
        
        logger.info(f"\nPreprocessing complete:")
        logger.info(f"- Successfully processed: {processed} files")
        logger.info(f"- Skipped: {skipped} files")
        
    finally:
        # Pulisci la directory temporanea
        logger.debug(f"Cleaning up temporary directory: {temp_dir}")
        shutil.rmtree(temp_dir)

if __name__ == '__main__':
    #profiler = cProfile.Profile()
    #profiler.enable()
    main()
    #profiler.disable()
    #stats = pstats.Stats(profiler).sort_stats('cumulative')
    #stats.print_stats() 