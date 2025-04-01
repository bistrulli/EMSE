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

def parse_arguments():
    parser = argparse.ArgumentParser(description='Preprocess C files in a project')
    parser.add_argument('--project-path', '-p', required=True, help='Path to the C project')
    parser.add_argument('--include-paths', '-i', nargs='+', default=['/usr/include'], help='System include paths')
    parser.add_argument('--output-dir', '-o', default='preprocessed', help='Output directory')
    return parser.parse_args()

def setup_directories(project_path: str, output_dir: str) -> Tuple[Path, Path]:
    """
    Crea la struttura delle cartelle di output e una directory temporanea.
    Ritorna (project_out_dir, temp_dir)
    """
    # Converti i path in oggetti Path
    project_path = Path(project_path)
    output_dir = Path(output_dir)
    
    # Crea directory di output con il nome del progetto come padre
    project_name = project_path.name
    project_out_dir = output_dir / f"{project_name}"
    
    # Ricrea la struttura delle cartelle
    for src_dir in project_path.rglob('*'):
        if src_dir.is_dir():
            dst_dir = project_out_dir / src_dir.relative_to(project_path)
            dst_dir.mkdir(parents=True, exist_ok=True)
    
    # Crea anche la directory root del progetto
    project_out_dir.mkdir(parents=True, exist_ok=True)
    
    # Crea una directory temporanea con il nome del progetto
    temp_base = Path('/dev/shm')
    temp_dir = None
    max_attempts = 10
    attempt = 0
    
    while attempt < max_attempts:
        try:
            # Usa il nome del progetto nella directory temporanea
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
    
    return project_out_dir, temp_dir

def find_c_files(project_path: str) -> List[Path]:
    """Trova tutti i file .c nel progetto usando find."""
    cmd = ['find', str(project_path), '-name', '*.c']
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        return [Path(p) for p in result.stdout.strip().split('\n') if p]
    return []

def extract_missing_file(err_msg: str) -> Optional[Tuple[str, bool]]:
    """
    Estrae il nome del file mancante dal messaggio di errore.
    Ritorna (nome_file, is_system) dove is_system è True se è un include di sistema.
    """
    pattern = r'#include\s*([<"])([^>"]+)[>"]'
    match = re.search(pattern, err_msg)
    if match:
        delim, file = match.groups()
        return file, delim == '<'
    return None

def find_file_in_project(file_name: str, project_path: Path, current_file: Path) -> Optional[Path]:
    """Cerca un file nel progetto usando find.
    
    Args:
        file_name: Nome del file da cercare
        project_path: Path del progetto
        current_file: Path del file corrente che sta includendo file_name
    """
    try:
        # Prima prova a trovare il file usando il path relativo completo
        relative_path = current_file.parent / file_name
        if relative_path.exists():
            return relative_path
            
        # Se il file ha lo stesso nome del file in preprocessamento,
        # non fare la ricerca project-wise
        if Path(file_name).name == current_file.name:
            return None
            
        # Altrimenti, cerca nel progetto
        cmd = ['find', str(project_path), '-name', Path(file_name).name]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0 and result.stdout:
            matches = [Path(p) for p in result.stdout.strip().split('\n') if p]
            if matches:
                # Ordina per dimensione e prendi il più grande
                matches.sort(key=lambda x: x.stat().st_size if x.exists() else 0, reverse=True)
                return matches[0]
    except Exception as e:
        print(f"  Debug: Exception in find_file_in_project: {str(e)}", flush=True)
    return None

def read_file_with_fallback_encoding(file_path: Path) -> str:
    """Legge un file di testo provando diverse codifiche in ordine di probabilità.
    
    Args:
        file_path: Path del file da leggere
        
    Returns:
        Il contenuto del file come stringa
        
    Raises:
        UnicodeDecodeError: Se nessuna codifica funziona
    """
    encodings = ['utf-8', 'latin-1', 'iso-8859-1', 'cp1252']
    for encoding in encodings:
        try:
            return file_path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError(f"Could not decode file with any of the encodings: {encodings}")

def update_includes(file_path: Path, missing_file: str, update_all_headers: bool = False) -> None:
    """Aggiorna gli include nel file per usare i file copiati nella directory temporanea.
    
    Args:
        file_path: Path del file da modificare
        missing_file: Nome del file mancante
        update_all_headers: Se True, aggiorna gli include anche in tutti gli header nella directory temporanea
    """
    # Leggi il contenuto del file usando il fallback delle codifiche
    content = read_file_with_fallback_encoding(file_path)
    
    # Trova tutti gli include di progetto che contengono il file mancante
    pattern = r'#include\s+".*?' + re.escape(missing_file) + r'"'
    
    # Debug: mostra tutti i match trovati
    matches = re.findall(pattern, content)
    
    if matches:
        # Sostituisci ogni match con l'include appiattito
        new_content = re.sub(pattern, f'#include "{Path(missing_file).name}"', content)
        file_path.write_text(new_content)
    
    # Se richiesto, aggiorna anche tutti gli header nella directory temporanea
    if update_all_headers:
        temp_dir = file_path.parent
        # Trova tutti i file .h e .c nella directory temporanea
        cmd = ['find', str(temp_dir), '-type', 'f', '(', '-name', '*.h', '-o', '-name', '*.c', ')']
        result = subprocess.run(cmd, capture_output=True, text=True)
        files_to_update = [Path(p) for p in result.stdout.strip().split('\n') if p]
        
        for file_to_update in files_to_update:
            if file_to_update != file_path:  # Non aggiornare il file appena modificato
                try:
                    content = read_file_with_fallback_encoding(file_to_update)
                    if missing_file in content:  # Se il file contiene l'include
                        new_content = re.sub(pattern, f'#include "{Path(missing_file).name}"', content)
                        file_to_update.write_text(new_content)
                except Exception as e:
                    print(e)
                    continue

def run_cpp_m(file_path: Path, include_paths: List[Path]) -> Tuple[bool, Optional[str]]:
    """
    Esegue cpp -M sul file e ritorna (success, error_message).
    """
    cmd = ['cpp', '-M'] + [f'-I{p}' for p in include_paths] + [str(file_path)]
    #print(f"\n  Debug cpp command: {' '.join(cmd)}", flush=True)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        #print(f"  Debug cpp returncode: {result.returncode}", flush=True)
        #print(f"  Debug cpp search paths:", flush=True)
        #print('\n'.join('    ' + line for line in result.stderr.splitlines()), flush=True)
        return result.returncode == 0, result.stderr if result.stderr else None
    except subprocess.SubprocessError as e:
        print(f"  Debug cpp exception: {str(e)}", flush=True)
        return False, str(e)

def preprocess_file(c_file: Path, project_path: Path, include_paths: List[Path], 
                   output_dir: Path, temp_dir: Path) -> bool:
    """
    Preprocessa un singolo file C risolvendo le dipendenze mancanti.
    """
    print(f"\nProcessing {c_file.relative_to(project_path)}", flush=True)
    
    # Setup dei path di output
    rel_path = c_file.relative_to(project_path)
    out_path = output_dir / f"{rel_path}.i"
    err_path = output_dir / f"{rel_path}.err"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Copia il file .c nella directory temporanea
    temp_file = temp_dir / c_file.name
    shutil.copy2(c_file, temp_file)
    
    # Mappa per tenere traccia dei path originali
    path_map = {str(temp_file): str(c_file)}

    # Loop di risoluzione delle dipendenze
    while True:
        success, err_msg = run_cpp_m(temp_file, [temp_dir] + include_paths)
        if success:
            break
            
        missing_info = extract_missing_file(err_msg)
        if missing_info is None:
            print(f"  Failed: preprocessing error")
            if err_msg:
                err_path.write_text(err_msg)
            return False
        
        missing_file, is_system = missing_info
        
        if is_system:
            print(f"  Failed: missing system dependency <{missing_file}>", flush=True)
            if err_msg:
                err_path.write_text(err_msg)
            return False
        
        # Cerca il file mancante nel progetto
        found_file = find_file_in_project(missing_file, project_path, temp_file)
        if not found_file:
            print(f'  Failed: missing project dependency "{missing_file}"', flush=True)
            if err_msg:
                err_path.write_text(err_msg)
            return False
        
        # Copia il file trovato nella directory temporanea
        temp_dep = temp_dir / found_file.name
        shutil.copy2(found_file, temp_dep)
        path_map[str(temp_dep)] = str(found_file)
        
        # Aggiorna gli include nel file temporaneo
        update_includes(temp_file, missing_file, update_all_headers=True)
    
    # Tutte le dipendenze sono risolte, esegui il preprocessing finale
    cmd = ['cpp', '-E', str(temp_file), '-o', str(out_path)] + [f'-I{p}' for p in [temp_dir] + include_paths]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print("  Failed: preprocessing error", flush=True)
            if result.stderr:
                err_path.write_text(result.stderr)
            return False
        
        # Sostituisci i path temporanei con quelli originali nel file .i
        content = out_path.read_text()
        # Ordina i path per lunghezza decrescente per evitare sostituzioni parziali
        sorted_paths = sorted(path_map.items(), key=lambda x: len(x[0]), reverse=True)
        for temp_path, orig_path in sorted_paths:
            # Sostituisci sia il path completo che solo il nome del file
            content = content.replace(temp_path, orig_path)
            content = content.replace(Path(temp_path).name, Path(orig_path).name)
        out_path.write_text(content)
        
        print("  Success", flush=True)
        return True
        
    except subprocess.CalledProcessError as e:
        print("  Failed: preprocessing error", flush=True)
        if e.stderr:
            err_path.write_text(e.stderr)
        return False

def main():
    args = parse_arguments()
    
    # Setup directories
    project_out_dir, temp_dir = setup_directories(args.project_path, args.output_dir)
    
    try:
        # Trova tutti i file .c del progetto
        c_files = find_c_files(args.project_path)
        
        # Preprocessa ogni file
        processed = 0
        skipped = 0
        
        for c_file in c_files:
            if preprocess_file(c_file, Path(args.project_path), 
                            [Path(p) for p in args.include_paths],
                            project_out_dir, temp_dir):
                processed += 1
            else:
                skipped += 1
        
            # Svuota la directory temporanea dopo aver processato il file
            if temp_dir.exists() and (skipped+processed)%200==0:
                for file in temp_dir.iterdir():
                    file.unlink()
            
            #if(skipped+processed)==200:
            #    break
        
        print(f"\nPreprocessing complete:", flush=True)
        print(f"- Successfully processed: {processed} files", flush=True)
        print(f"- Skipped: {skipped} files", flush=True)
        
    finally:
        # Pulisci la directory temporanea
        shutil.rmtree(temp_dir)

if __name__ == '__main__':
    #profiler = cProfile.Profile()
    #profiler.enable()
    main()
    #profiler.disable()
    #stats = pstats.Stats(profiler).sort_stats('cumulative')
    #stats.print_stats() 