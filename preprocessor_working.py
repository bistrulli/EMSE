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
    
    
    temp_dir = Path('/dev/shm') / f'preprocessor_{uuid.uuid4().hex[:8]}'
    temp_dir.mkdir()

    # Crea directory temporanea
    #temp_dir = Path(tempfile.mkdtemp(prefix="preprocessor_"))
    
    #debug_dir=project_out_dir/"debug"
    #debug_dir.mkdir(parents=True, exist_ok=True)
    #temp_dir = debug_dir
    
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
        # Se il file da cercare ha lo stesso nome del file in preprocessamento,
        # cerca solo nella directory del file corrente
        if Path(file_name).name == current_file.name:
            relative_path = current_file.parent / file_name
            if relative_path.exists():
                return relative_path
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
    
    Logica della funzione:
    1. Setup iniziale:
       - Crea i path per il file di output (.i) e di errore (.err)
       - Copia il file sorgente in una directory temporanea
    
    2. Loop di risoluzione dipendenze:
       - Esegue cpp -M per trovare le dipendenze mancanti
       - Se trova una dipendenza mancante:
         * Se è una dipendenza di sistema -> errore
         * Se è una dipendenza di progetto -> cerca il file e copialo in temp
       - Aggiorna gli include per usare i file copiati
       - Ripeti finché non ci sono più dipendenze mancanti
    
    3. Preprocessing finale:
       - Esegue cpp -E per generare il file preprocessato
       - Sostituisci i path temporanei con quelli originali
    
    Args:
        c_file: File .c da preprocessare
        project_path: Path del progetto
        include_paths: Lista dei path dove cercare gli include
        output_dir: Directory dove salvare i file .i e .err
        temp_dir: Directory temporanea per i file copiati
        
    Returns:
        True se il preprocessing ha successo, False altrimenti
    """
    # Mostra il file che stiamo processando (relativo alla root del progetto)
    print(f"\nProcessing {c_file.relative_to(project_path)}", flush=True)
    
    # Setup dei path di output (.i e .err nella stessa struttura del progetto)
    rel_path = c_file.relative_to(project_path)
    out_path = output_dir / f"{rel_path}.i"
    err_path = output_dir / f"{rel_path}.err"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Copia il file .c nella directory temporanea per lavorarci
    temp_file = temp_dir / c_file.name
    shutil.copy2(c_file, temp_file)
    
    # Mappa per tenere traccia dei path originali (serve per il postprocessing)
    path_map = {str(temp_file): str(c_file)}
    
    #ok ho capito il problema, quando risolo i missing include di un file e' possibile che 
    #i nuovi include considerati abbiamo a loro volta dei missing include. Ade esempio il file 
    #cpupower-monitor.c include il file cpupower-monitor.h che a sua volta include "idle-monitor.h" che essendo
    #un file di progetto andrebbe incluso con lo stesso meccanismo. In pratica io dovrei chiamare 
    #la funzione preprocess_file anche su tutta la catena degli include. Una strategia possibile
    #potrebbe essere: quando copio una missing include del file, allora preprocesso ricorsivamente anche quella
    #per cercare di capire se ha delle missing include a sua volta. Puoi autarmi a fare questa modifica in modo pulito e che io possa capirla leggendo il codice


    # Loop di risoluzione delle dipendenze
    while True:
        #print(f"\nDebug iteration:", flush=True)
        # Prova a trovare le dipendenze con cpp -M
        success, err_msg = run_cpp_m(temp_file, [temp_dir] + include_paths)
        if success:
            break  # Tutte le dipendenze sono risolte
            
        # Se c'è un errore, estrai il nome del file mancante
        missing_info = extract_missing_file(err_msg)
        if missing_info is None:
            print(f"  Failed: preprocessing error")
            if err_msg:
                err_path.write_text(err_msg)
            return False
        
        missing_file, is_system = missing_info
        #print(f"  Debug missing file: {missing_file} (system: {is_system})", flush=True)
        
        # Se manca una dipendenza di sistema, non possiamo fare nulla
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
        #print(f" Debug copying found file {temp_dep}, exists:{temp_dep.exists()}")
        shutil.copy2(found_file, temp_dep)
        #print(f" Debug copying found file {temp_dep}, exists:{temp_dep.exists()}")
        path_map[str(temp_dep)] = str(found_file)
        
        #Aggiorna gli include nel file temporaneo per usare il file copiato
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
        for temp_path, orig_path in path_map.items():
            content = content.replace(temp_path, orig_path)
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