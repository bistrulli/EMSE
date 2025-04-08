#!/usr/bin/env python3
import os
import shutil
import subprocess
import re
import argparse
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple, Dict
import uuid
import cProfile
import pstats
import sys
import gc
import time

def parse_arguments():
    parser = argparse.ArgumentParser(description='Preprocess C files in a project')
    parser.add_argument('--project-path', '-p', help='Path to the C project')
    parser.add_argument('--single-file', '-f', help='Path to a single C file to preprocess (can be used with --project-path)')
    parser.add_argument('--include-paths', '-i', nargs='+', default=['/usr/include'], help='System include paths')
    parser.add_argument('--clean-temp', action='store_true', help='Clean temporary directory after each file')
    parser.add_argument('--debug', '-d', action='store_true', help='Enable debug mode with detailed output')
    return parser.parse_args()

def setup_directories(project_path: str) -> Path:
    """
    Crea una directory temporanea.
    Ritorna temp_dir
    """
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
            print(f"Warning: Could not create temporary directory in /dev/shm: {e}")
            # Fallback su una directory temporanea nel filesystem normale
            temp_dir = Path(tempfile.mkdtemp(prefix=f"preprocessor_{project_name}_"))
            break
        except Exception as e:
            print(f"Warning: Unexpected error creating temporary directory: {e}")
            attempt += 1
    
    if temp_dir is None:
        raise RuntimeError("Failed to create temporary directory after multiple attempts")
    
    return temp_dir

def find_c_files(project_path: str) -> List[Path]:
    """Trova tutti i file .c nel progetto usando find."""
    cmd = ['find', str(project_path), '-name', '*.c']
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        return [Path(p) for p in result.stdout.strip().split('\n') if p]
    return []

def extract_missing_file(error_message: str, debug: bool = False) -> Optional[Tuple[str, bool, Optional[str]]]:
    """Estrae il nome del file mancante, se è di sistema, e il file che lo includeva dall'output di errore di cpp.
    
    Returns:
        Tuple: (nome_file_mancante, is_system, includer_file_path) o None se non trovato.
        includer_file_path può essere None se non è stato possibile estrarlo.
    """
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
        if debug:
            print(f"""  DEBUG: Could not find missing file pattern in error message:
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
        elif debug:
            print(f"  DEBUG: Warning: Extracted file name '{missing_file}' doesn't match include path '{include_path}'")
    else:
        # Non abbiamo trovato la riga dell'include, assumiamo che non sia di sistema
        if debug:
            print(f"  DEBUG: Could not find include line pattern, assuming it's a project dependency")
    
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
                if debug:
                    print(f"  DEBUG: Found includer: '{includer_file_path}' from line: '{line.strip()}'")
                break
    
    if not found_includer and debug:
        print(f"  DEBUG: Could not determine the includer file path for '{missing_file}'")
    
    if debug:
        print(f"  DEBUG: Final extracted -> Missing: '{missing_file}', System: {is_system}, Includer: '{includer_file_path}'")
    
    return missing_file, is_system, includer_file_path

def debug_print(message: str, debug: bool = False) -> None:
    """Print a debug message if debug mode is enabled."""
    if debug:
        print(message, flush=True)

def find_file(filename: str, from_file: str, include_paths: List[Path], project_path: Path, debug: bool = False) -> Optional[Path]:
    """Find a file using a hierarchical search strategy:
    1. First try to resolve relative path from source directory
    2. Look in the same directory as the source file
    3. Look in the specified include paths
    4. Search in the entire project for the base filename
    """
    if not filename:
        return None

    # Get just the base filename (without directories)
    base_filename = Path(filename).name
    
    # Convert relative path to absolute path
    source_dir = Path(from_file).parent
    if debug:
        print(f"  DEBUG: Source directory: {source_dir}")
        print(f"  DEBUG: Looking for file: {filename}")
        print(f"  DEBUG: Base filename: {base_filename}")

    # Phase 1: Try to resolve relative path from source directory
    if '/' in filename or '\\' in filename:
        try:
            # Try the relative path as given
            relative_path = source_dir / filename
            normalized_path = relative_path.resolve()
            if debug:
                print(f"  DEBUG: Trying resolved relative path: {normalized_path}")
            if normalized_path.exists():
                debug_print(f"  DEBUG: Found file using relative path: {normalized_path}", debug)
                return normalized_path
            else:
                debug_print(f"  DEBUG: Relative path not found: {normalized_path}", debug)
                
                # If relative path failed, proceed with normal search
                debug_print(f"  DEBUG: Will try normal search phases", debug)
        except Exception as e:
            debug_print(f"  DEBUG: Error resolving relative path: {e}", debug)

    # Phase 2: Look in the same directory as the source file
    if source_dir.exists():
        debug_print(f"  DEBUG: Phase 2 - Searching in source directory: {source_dir}", debug)
        direct_path = source_dir / base_filename
        if direct_path.exists():
            debug_print(f"  DEBUG: Found file in source directory: {direct_path}", debug)
            return direct_path

    # Phase 3: Look in include paths
    debug_print(f"  DEBUG: Phase 3 - Searching in include paths", debug)
    for include_path in include_paths:
        if include_path.exists():
            include_file = include_path / base_filename
            if include_file.exists():
                debug_print(f"  DEBUG: Found file in include path: {include_file}", debug)
                return include_file

    # Phase 4: Search in entire project
    return search_file_in_project(base_filename, project_path, debug)

def search_file_in_project(filename: str, project_path: Path, debug: bool = False) -> Optional[Path]:
    """Search for a file in the entire project."""
    debug_print(f"  DEBUG: Phase 4 - Searching in entire project: {project_path}", debug)
    try:
        # Use find command to search in the project directory
        find_cmd = f"find {project_path} -type f -name '{filename}'"
        debug_print(f"  DEBUG: Running find command: {find_cmd}", debug)
        result = subprocess.run(find_cmd, shell=True, capture_output=True, text=True, timeout=5)
        
        if result.returncode == 0 and result.stdout.strip():
            # Get all matches
            matches = [Path(p) for p in result.stdout.strip().split('\n') if p]
            
            if matches:
                debug_print(f"  DEBUG: Found {len(matches)} matches in project", debug)
                for i, match in enumerate(matches[:5]):
                    debug_print(f"  DEBUG:   {i+1}. {match}", debug)
                
                # Return the first match
                debug_print(f"  DEBUG: Selected first match: {matches[0]}", debug)
                return matches[0]
        else:
            debug_print(f"  DEBUG: File not found in project", debug)
    except subprocess.TimeoutExpired:
        debug_print(f"  DEBUG: Find command timed out", debug)
    except Exception as e:
        debug_print(f"  DEBUG: Error during project search: {str(e)}", debug)

    debug_print(f"  DEBUG: File not found in any location", debug)
    return None

def read_file_with_fallback_encoding(file_path: Path) -> str:
    """Legge un file provando diverse codifiche comuni."""
    encodings = ['utf-8', 'latin-1', 'cp1252']
    for enc in encodings:
        try:
            return file_path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
        except Exception as e:
            # Gestisci altri possibili errori di lettura
            print(f"  Warning: Error reading {file_path} with {enc}: {e}", flush=True)
            break # Interrompi se c'è un errore diverso dalla decodifica
    # Se tutte le codifiche falliscono, solleva un errore o restituisci una stringa vuota
    print(f"  Error: Could not decode file {file_path} with any known encoding.", flush=True)
    # Potresti voler sollevare un'eccezione qui invece di restituire una stringa vuota
    # raise IOError(f"Could not decode file {file_path}")
    return "" # O restituisci una stringa vuota per provare a continuare

def update_includes(file_to_update: Path, missing_file_base_name: str, debug: bool = False) -> bool:
    """Aggiorna gli include nel file specificato per usare il nome base del file mancante.
    Utilizza un approccio riga per riga per una maggiore robustezza con i path relativi.
    
    Args:
        file_to_update: Path del file da modificare (nella directory temporanea).
        missing_file_base_name: Nome base del file mancante (es. 'lv_conf.h').
        debug: Se True, mostra informazioni di debug dettagliate.
        
    Returns:
        True se il file è stato modificato, False altrimenti.
    """
    if not file_to_update or not file_to_update.exists():
        if debug:
            print(f"  DEBUG: update_includes - File to update does not exist: {file_to_update}")
        return False
        
    if debug:
        print(f"  DEBUG: Updating includes in {file_to_update.name} for base name: {missing_file_base_name}")
    
    try:
        content_lines = read_file_with_fallback_encoding(file_to_update).splitlines()
    except Exception as e:
        if debug:
            print(f"  DEBUG: Error reading file {file_to_update} for update: {e}")
        return False
        
    new_content_lines = []
    updated = False
    # Match #include "..." - cattura solo il path interno alle virgolette
    include_pattern = re.compile(r'^(\s*#include\s+")([^>]+)(")') 

    for line_num, line in enumerate(content_lines):
        match = include_pattern.match(line)
        original_line = line
        modified_line = line

        if match:
            prefix, included_path, suffix = match.groups()
            # Prendiamo il nome base del path trovato nell'include
            included_base_name = Path(included_path).name 
            
            if debug:
                print(f"  DEBUG: Line {line_num+1}: Checking include: '{original_line.strip()}'")
                print(f"  DEBUG:   Extracted path: '{included_path}' -> Base name: '{included_base_name}'")
                print(f"  DEBUG:   Comparing with missing base name: '{missing_file_base_name}'")

            # Confronta SOLO il nome base
            if included_base_name == missing_file_base_name:
                if debug:
                    print(f"  DEBUG:   Base names match!")
                # Ricostruisci la linea con il nome base appiattito    
                modified_line = f'{prefix}{missing_file_base_name}{suffix}'
                if original_line.strip() != modified_line.strip():
                    if debug:
                        print(f"  DEBUG:   Updating line: '{original_line.strip()}' -> '{modified_line.strip()}'")
                    updated = True
                elif debug:
                    print(f"  DEBUG:   Include already flattened: '{original_line.strip()}'")
            elif debug:
                print(f"  DEBUG:   Base names DO NOT match.")
        
        new_content_lines.append(modified_line)

    if updated:
        try:
            new_content = '\n'.join(new_content_lines) + '\n'
            file_to_update.write_text(new_content, encoding='utf-8')
            if debug:
                print(f"  DEBUG: Successfully updated {file_to_update.name}")
            return True # Indica che il file è stato modificato
        except Exception as e:
            if debug:
                print(f"  DEBUG: Error writing updated file {file_to_update}: {e}")
            return False # Fallito l'aggiornamento
    elif debug:
        print(f"  DEBUG: No includes needed updating for '{missing_file_base_name}' in {file_to_update.name}")
        
    return False # Nessuna modifica effettuata

def run_cpp_m(file_path: Path, include_paths: List[Path], debug: bool = False) -> Tuple[bool, Optional[str]]:
    """
    Esegue cpp -M sul file e ritorna (success, error_message).
    """
    start_time = time.time()
    cmd = ['cpp', '-M'] + [f'-I{p}' for p in include_paths] + [str(file_path)]
    
    if debug:
        print(f"  DEBUG: Running cpp -M command: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        end_time = time.time()
        
        if debug:
            print(f"  DEBUG: cpp -M command completed in {end_time - start_time:.6f} seconds")
            print(f"  DEBUG: cpp -M return code: {result.returncode}")
            
            if result.stderr:
                print(f"  DEBUG: cpp -M stderr: {result.stderr[:500]}...")  # Mostra primi 500 caratteri
        
        return result.returncode == 0, result.stderr if result.stderr else None
    except subprocess.SubprocessError as e:
        if debug:
            print(f"  DEBUG: cpp -M exception: {str(e)}")
        else:
            print(f"  Debug cpp exception: {str(e)}", flush=True)
        return False, str(e)

def run_cpp_e(file_path: Path, include_paths: List[Path], debug: bool = False) -> Tuple[bool, str, Optional[str]]:
    """
    Esegue cpp -E sul file e ritorna (success, stdout_content, error_message).
    """
    start_time = time.time()
    cmd = ['cpp', '-E'] + [f'-I{p}' for p in include_paths] + [str(file_path)]
    
    if debug:
        print(f"  DEBUG: Running cpp -E command: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        end_time = time.time()
        
        if debug:
            print(f"  DEBUG: cpp -E command completed in {end_time - start_time:.6f} seconds")
            print(f"  DEBUG: cpp -E return code: {result.returncode}")
            
            if result.stderr:
                print(f"  DEBUG: cpp -E stderr: {result.stderr[:500]}...")  # Mostra primi 500 caratteri
            
            stdout_size = len(result.stdout) if result.stdout else 0
            print(f"  DEBUG: cpp -E stdout size: {stdout_size} bytes")
        
        return (
            result.returncode == 0,
            result.stdout if result.stdout else "",
            result.stderr if result.stderr else None
        )
    except subprocess.SubprocessError as e:
        if debug:
            print(f"  DEBUG: cpp -E exception: {str(e)}")
        else:
            print(f"  Debug cpp exception: {str(e)}", flush=True)
        return False, "", str(e)

def clean_temp_directory(temp_dir: Path, debug: bool = False) -> None:
    """
    Pulisce completamente la directory temporanea eliminando tutti i file.
    
    Args:
        temp_dir: Path della directory temporanea
        debug: Se True, mostra informazioni di debug dettagliate
    """
    if debug:
        print(f"  DEBUG: Cleaning temporary directory {temp_dir}")
        file_count = sum(1 for _ in temp_dir.iterdir() if _.is_file())
        print(f"  DEBUG: Found {file_count} files to clean")
    else:
        print(f"  Cleaning temporary directory {temp_dir}...", flush=True)
    
    try:
        # Elimina tutti i file nella directory temporanea
        for file_path in temp_dir.iterdir():
            if file_path.is_file():
                if debug:
                    print(f"  DEBUG: Removing file: {file_path.name}")
                file_path.unlink()
                
        # Forza la garbage collection per liberare memoria
        if debug:
            print(f"  DEBUG: Running garbage collection")
        gc.collect()
        
        if debug:
            print(f"  DEBUG: Temporary directory cleaned successfully")
        else:
            print(f"  Temporary directory cleaned", flush=True)
    except Exception as e:
        if debug:
            print(f"  DEBUG: Failed to clean temporary directory: {e}")
        else:
            print(f"  Warning: Failed to clean temporary directory: {e}", flush=True)

def preprocess_file(c_file: Path, project_path: Path, include_paths: List[Path], 
                   temp_dir: Path, debug: bool = False) -> bool:
    """
    Preprocessa un singolo file C risolvendo le dipendenze mancanti.
    I file .i e .err vengono salvati nella stessa directory del file .c originale.
    """
    total_start_time = time.time()
    
    print(f"\nProcessing {c_file.name}", flush=True)
    if debug:
        print(f"  DEBUG: Full path: {c_file}")
        print(f"  DEBUG: Project path: {project_path}")
        print(f"  DEBUG: Temporary directory: {temp_dir}")
        print(f"  DEBUG: Include paths: {include_paths}")
    
    # Setup dei path di output nella stessa directory del file .c
    out_path = c_file.with_suffix('.i')
    err_path = c_file.with_suffix('.err')
    
    if debug:
        print(f"  DEBUG: Output paths:")
        print(f"  DEBUG:   .i file: {out_path}")
        print(f"  DEBUG:   .err file: {err_path}")
    
    # Copia il file .c nella directory temporanea
    copy_start_time = time.time()
    try:
        temp_file = temp_dir / c_file.name
        shutil.copy2(c_file, temp_file)
        temp_file.chmod(0o666)
    except Exception as e:
        print(f"  Failed: Error copying {c_file.name} to temp directory: {e}")
        return False
    copy_end_time = time.time()
    
    if debug:
        print(f"  DEBUG: Copied source file to temp directory in {copy_end_time - copy_start_time:.6f} seconds")
        print(f"  DEBUG: Temp file: {temp_file}")
    
    # Mappa per tenere traccia dei path originali (necessaria? Forse non più)
    # path_map = {str(temp_file): str(c_file)}
    
    dependency_count = 0
    max_iterations = 1000 # Rinominato da max_dependencies
    files_updated_in_iteration = set()

    while dependency_count < max_iterations:
        dependency_count += 1
        files_updated_in_iteration.clear() # Resetta per questa iterazione
        
        if debug:
            print(f"\n  DEBUG: === Dependency resolution iteration {dependency_count} ===")
        
        # Esegui cpp -M sul file .c principale nella directory temporanea
        success, err_msg = run_cpp_m(temp_file, [temp_dir] + include_paths, debug)
        if success:
            if debug:
                print(f"  DEBUG: cpp -M succeeded, all dependencies resolved for {temp_file.name}")
            break # Esce dal loop while
        
        if debug:
            print(f"  DEBUG: cpp -M failed for {temp_file.name}, trying to extract missing file")
            
        missing_info = extract_missing_file(err_msg, debug)
        if missing_info is None:
            print(f"  Failed: preprocessing error (could not extract missing file)")
            # ... (salva errore e ritorna) ...
            if err_msg:
                err_path.write_text(err_msg)
            return False
        
        missing_file, is_system, includer_file_path_str = missing_info
        missing_file_base_name = Path(missing_file).name
        
        if debug:
            print(f"  DEBUG: Extracted missing: '{missing_file}' (Base: '{missing_file_base_name}'), System: {is_system}, Includer: '{includer_file_path_str}'")
        
        if is_system:
            print(f"  Failed: missing system dependency <{missing_file}>", flush=True)
            # ... (salva errore e ritorna) ...
            if err_msg:
                err_path.write_text(err_msg)
            return False
        
        # 1. Trova il file sorgente originale per il file mancante
        if debug:
            print(f"  DEBUG: Searching for source of project dependency: {missing_file}")
        search_start_time = time.time()
        # Passiamo il path completo se disponibile, altrimenti solo il nome base
        search_term = missing_file if '/' in missing_file or '\\' in missing_file else missing_file_base_name
        # Usiamo il path del file .c originale come riferimento per la ricerca relativa iniziale
        found_source_file = find_file(search_term, str(c_file), include_paths, project_path, debug)
        search_end_time = time.time()
        
        if debug:
            print(f"  DEBUG: Search completed in {search_end_time - search_start_time:.6f} seconds")
            
        if not found_source_file:
            print(f'  Failed: missing project dependency "{missing_file}" (source not found)', flush=True)
            # ... (salva errore e ritorna) ...
            if err_msg:
                err_path.write_text(err_msg)
            return False
            
        # 2. Copia il file trovato nella directory temporanea (se non già presente e aggiornato)
        temp_dependency_path = temp_dir / missing_file_base_name
        copy_needed = True
        if temp_dependency_path.exists():
            # Evita copie inutili se il file è già lì e identico o più nuovo
            try:
                source_stat = found_source_file.stat()
                temp_stat = temp_dependency_path.stat()
                if temp_stat.st_mtime >= source_stat.st_mtime and temp_stat.st_size == source_stat.st_size:
                    copy_needed = False
                    if debug:
                        print(f"  DEBUG: Dependency {missing_file_base_name} already up-to-date in temp dir.")
            except OSError as e:
                if debug:
                     print(f"  DEBUG: Error stating files for comparison: {e}")

        if copy_needed:
            copy_dep_start = time.time()
            try:
                shutil.copy2(found_source_file, temp_dependency_path)
                temp_dependency_path.chmod(0o666)
                if debug:
                    print(f"  DEBUG: Copied dependency '{found_source_file.name}' to '{temp_dependency_path}'")
            except Exception as e:
                print(f"  Failed: Error copying dependency {found_source_file.name} to temp dir: {e}")
                if err_msg: err_path.write_text(err_msg + f"\nError copying dependency: {e}")
                return False
            copy_dep_end = time.time()
            if debug:
                print(f"  DEBUG: Dependency copy took {copy_dep_end - copy_dep_start:.6f} seconds")
        
        # 3. Identifica il file da aggiornare nella directory TEMP
        file_to_update_in_temp = None
        if includer_file_path_str:
            # Se abbiamo l'includer, cerchiamo il file corrispondente nella temp dir
            # Assumiamo che l'includer path sia relativo alla temp dir o un path assoluto già dentro la temp dir
            potential_path = Path(includer_file_path_str)
            if potential_path.is_absolute() and str(potential_path).startswith(str(temp_dir)):
                 file_to_update_in_temp = potential_path
            else:
                 # Potrebbe essere un path relativo alla radice del progetto? O alla temp dir?
                 # Tentativo: consideralo relativo alla temp_dir
                 relative_to_temp = temp_dir / Path(includer_file_path_str).name # Prendiamo solo il nome base per sicurezza
                 if relative_to_temp.exists():
                      file_to_update_in_temp = relative_to_temp
                 elif temp_dir / includer_file_path_str.exists(): # Prova il path completo relativo a temp
                      file_to_update_in_temp = temp_dir / includer_file_path_str
                 else:
                      if debug: print(f"  DEBUG: Could not locate includer '{includer_file_path_str}' in temp dir '{temp_dir}'")
                           
        # Fallback se non abbiamo l'includer o non l'abbiamo trovato nella temp dir
        if not file_to_update_in_temp or not file_to_update_in_temp.exists():
             if debug and includer_file_path_str:
                  print(f"  DEBUG: Fallback: Updating main file '{temp_file.name}' as includer was not found/specified.")
             file_to_update_in_temp = temp_file # Aggiorna il file .c principale come fallback
        
        # 4. Aggiorna gli include nel file identificato
        if file_to_update_in_temp:
            if debug:
                print(f"  DEBUG: Attempting to update includes in TEMP file: {file_to_update_in_temp}")
            
            # Passa solo il nome base del file mancante
            updated = update_includes(file_to_update_in_temp, missing_file_base_name, debug)
            if updated:
                files_updated_in_iteration.add(file_to_update_in_temp)
        else:
             if debug:
                 print(f"  DEBUG: Could not determine which file to update in temp directory.")

    # Fine del loop while
    if dependency_count >= max_iterations:
        print(f"  Failed: Maximum dependency resolution iterations ({max_iterations}) reached.")
        # Considera di scrivere un errore specifico qui
        if err_msg:
             err_path.write_text(err_msg + f"\nMaximum iterations reached.")
        return False

    # Se siamo usciti dal loop con successo, esegui cpp -E finale
    final_success, final_out, final_err = run_cpp_e(temp_file, [temp_dir] + include_paths)
    
    total_end_time = time.time()
    total_duration = total_end_time - total_start_time
    
    if final_success:
        print(f"  Success (resolved {dependency_count-1} dependencies in {total_duration:.2f} seconds)")
        out_path.write_text(final_out)
        # Rimuovi il file di errore se esiste
        if err_path.exists(): err_path.unlink()
        return True
    else:
        print(f"  Failed: final preprocessing step (cpp -E) failed after {total_duration:.2f} seconds")
        if final_err:
            err_path.write_text(final_err)
        return False

def main():
    args = parse_arguments()
    debug = args.debug
    
    if debug:
        print("=== DEBUG MODE ENABLED ===")
        print(f"Arguments: {args}")
    
    # Verifica che almeno uno tra project-path e single-file sia specificato
    if not args.project_path and not args.single_file:
        print("ERROR: Devi specificare almeno uno tra --project-path e --single-file")
        sys.exit(1)
    
    # Determina il project_path
    if args.project_path:
        project_path = Path(args.project_path)
    else:
        # Se solo single-file è specificato, usa la directory del file come project_path
        project_path = Path(args.single_file).parent
    
    if debug:
        print(f"Using project path: {project_path}")
    
    # Determina i file da processare
    if args.single_file:
        # Se è specificato single-file, processa solo quel file
        c_file = Path(args.single_file)
        if not c_file.exists() or not c_file.is_file() or c_file.suffix.lower() != '.c':
            print(f"ERROR: Invalid C file: {args.single_file}")
            sys.exit(1)
            
        # Se è specificato anche project-path, verifica che il file sia dentro il progetto
        if args.project_path:
            # Converte il percorso in assoluto
            abs_project_path = project_path.resolve()
            abs_c_file = c_file.resolve()
            
            # Verifica che il file sia all'interno del progetto
            try:
                rel_path = abs_c_file.relative_to(abs_project_path)
                # Se arriviamo qui, il file è dentro il progetto
                # Usa il percorso relativo per avere output coerenti
                c_file = abs_c_file  # Usiamo il path assoluto per evitare confusione
                
                if debug:
                    print(f"File is inside project at relative path: {rel_path}")
            except ValueError:
                print(f"WARNING: Il file {args.single_file} non sembra essere all'interno del progetto {args.project_path}")
                print("Procedo comunque con l'elaborazione.")
                
                if debug:
                    print(f"File is not inside project path")
        
        files_to_process = [c_file]
    else:
        # Se è specificato solo project-path, processa tutti i file del progetto
        if debug:
            print(f"Finding all .c files in project directory")
            
        files_to_process = find_c_files(args.project_path)
    
    if debug:
        print(f"Found {len(files_to_process)} files to process")
        if len(files_to_process) <= 10:
            for i, f in enumerate(files_to_process):
                print(f"  {i+1}. {f}")
        else:
            for i, f in enumerate(files_to_process[:5]):
                print(f"  {i+1}. {f}")
            print(f"  ... and {len(files_to_process) - 10} more files")
            for i, f in enumerate(files_to_process[-5:]):
                print(f"  {len(files_to_process) - 5 + i + 1}. {f}")
    
    # Setup directory temporanea
    temp_dir = setup_directories(str(project_path))
    
    if debug:
        print(f"Created temporary directory: {temp_dir}")
    
    try:
        # Preprocessa i file
        processed = 0
        skipped = 0
        
        print(f"Processing {len(files_to_process)} files...")
        
        for i, c_file in enumerate(files_to_process):
            if debug:
                print(f"\n=== Processing file {i+1}/{len(files_to_process)} ===")
            
            try:
                if preprocess_file(c_file, project_path, 
                                [Path(p) for p in args.include_paths],
                                temp_dir, debug):
                    processed += 1
                else:
                    skipped += 1
            except Exception as e:
                print(f"  Error processing file: {e}")
                if debug:
                    import traceback
                    print(f"  DEBUG: Exception traceback:")
                    print(traceback.format_exc())
                skipped += 1
        
            # Se richiesto, pulisci completamente la directory temporanea dopo ogni file
            if args.clean_temp and temp_dir.exists():
                clean_temp_directory(temp_dir, debug)
            # Altrimenti, pulisci solo ogni 200 file come prima
            elif temp_dir.exists() and (skipped+processed)%200==0:
                if debug:
                    print(f"  DEBUG: Cleaning temporary directory (periodic cleanup)")
                for file in temp_dir.iterdir():
                    file.unlink()
        
        print(f"\nPreprocessing complete:", flush=True)
        print(f"- Successfully processed: {processed} files", flush=True)
        print(f"- Skipped: {skipped} files", flush=True)
        
    finally:
        # Pulisci la directory temporanea
        if debug:
            print(f"Cleaning up temporary directory: {temp_dir}")
        shutil.rmtree(temp_dir)

if __name__ == '__main__':
    #profiler = cProfile.Profile()
    #profiler.enable()
    main()
    #profiler.disable()
    #stats = pstats.Stats(profiler).sort_stats('cumulative')
    #stats.print_stats() 