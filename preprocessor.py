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
import select
import time
from cpp_server.cpp_client import CppClient

class CppProcess:
    def __init__(self):
        self.process = None
        self.stdin = None
        self.stdout = None
        self.stderr = None
        self.timeout = 30  # timeout in secondi
        print("  Debug: CppProcess initialized", flush=True)

    def start(self):
        if self.process is None:
            print("  Debug: Starting cpp process", flush=True)
            try:
                self.process = subprocess.Popen(
                    ['cpp', '-'],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    universal_newlines=True
                )
                self.stdin = self.process.stdin
                self.stdout = self.process.stdout
                self.stderr = self.process.stderr
                print(f"  Debug: Cpp process started with PID {self.process.pid}", flush=True)
            except Exception as e:
                print(f"  Debug: Failed to start cpp process: {e}", flush=True)
                raise

    def stop(self):
        if self.process is not None:
            print(f"  Debug: Stopping cpp process (PID: {self.process.pid})", flush=True)
            try:
                print("  Debug: Closing pipes...", flush=True)
                self.stdin.close()
                self.stdout.close()
                self.stderr.close()
                print("  Debug: Terminating process...", flush=True)
                self.process.terminate()
                print("  Debug: Waiting for process to finish...", flush=True)
                self.process.wait(timeout=5)
            except Exception as e:
                print(f"  Debug: Error during process termination: {e}", flush=True)
                print("  Debug: Killing process...", flush=True)
                self.process.kill()
            finally:
                self.process = None
            print("  Debug: Cpp process stopped", flush=True)

    def _read_with_timeout(self, pipe, timeout):
        """Legge da una pipe con timeout"""
        start_time = time.time()
        output = []
        print(f"  Debug: Starting read with timeout {timeout}s", flush=True)
        
        while time.time() - start_time < timeout:
            try:
                # Prova a leggere direttamente
                print("  Debug: Attempting direct read...", flush=True)
                line = pipe.readline()
                if line:
                    print(f"  Debug: Read line: {line.strip()}", flush=True)
                    output.append(line)
                    continue
                
                # Se non c'è output, aspetta un po'
                print("  Debug: No direct output, checking with select...", flush=True)
                if select.select([pipe], [], [], 0.1)[0]:
                    print("  Debug: Data available on pipe", flush=True)
                    continue
                    
                # Se il processo è terminato, esci
                if self.process.poll() is not None:
                    print(f"  Debug: Process terminated with code {self.process.returncode}", flush=True)
                    break
                    
            except Exception as e:
                print(f"  Debug: Error reading from pipe: {e}", flush=True)
                break
                
        if time.time() - start_time >= timeout:
            print("  Debug: Read operation timed out", flush=True)
            raise TimeoutError("Operation timed out")
            
        print(f"  Debug: Read completed with {len(output)} lines", flush=True)
        return output

    def run_cpp_m(self, file_path: Path, include_paths: List[Path]) -> Tuple[bool, Optional[str]]:
        """Esegue cpp -M usando il processo persistente"""
        if self.process is None:
            self.start()

        # Costruisci il comando
        cmd = ['-M'] + [f'-I{p}' for p in include_paths] + [str(file_path)]
        cmd_str = ' '.join(cmd) + '\n'
        print(f"  Debug: Running cpp -M command: {cmd_str}", flush=True)
        print(f"  Debug: File exists: {file_path.exists()}", flush=True)
        print(f"  Debug: File size: {file_path.stat().st_size if file_path.exists() else 'N/A'}", flush=True)

        try:
            # Invia il comando
            print("  Debug: Writing command to stdin...", flush=True)
            self.stdin.write(cmd_str)
            self.stdin.flush()
            print("  Debug: Command written and flushed", flush=True)

            # Leggi l'output con timeout
            print("  Debug: Reading stdout...", flush=True)
            output = self._read_with_timeout(self.stdout, self.timeout)
            print("  Debug: Reading stderr...", flush=True)
            errors = self._read_with_timeout(self.stderr, self.timeout)

            # Verifica il risultato
            success = len(errors) == 0
            error_msg = ''.join(errors) if errors else None
            
            if error_msg:
                print(f"  Debug: cpp -M errors: {error_msg}", flush=True)
            if output:
                print(f"  Debug: cpp -M output: {''.join(output)}", flush=True)

            return success, error_msg

        except TimeoutError:
            print("  Debug: cpp -M operation timed out", flush=True)
            self.stop()  # Riavvia il processo in caso di timeout
            self.start()
            return False, "Operation timed out"
        except Exception as e:
            print(f"  Debug: cpp -M error: {e}", flush=True)
            self.stop()  # Riavvia il processo in caso di errore
            self.start()
            return False, str(e)

    def run_cpp_e(self, file_path: Path, include_paths: List[Path], output_path: Path) -> Tuple[bool, Optional[str]]:
        """Esegue cpp -E usando il processo persistente"""
        if self.process is None:
            self.start()

        # Costruisci il comando
        cmd = ['-E'] + [f'-I{p}' for p in include_paths] + [str(file_path), '-o', str(output_path)]
        cmd_str = ' '.join(cmd) + '\n'
        print(f"  Debug: Running cpp -E command: {cmd_str}", flush=True)
        print(f"  Debug: Input file exists: {file_path.exists()}", flush=True)
        print(f"  Debug: Input file size: {file_path.stat().st_size if file_path.exists() else 'N/A'}", flush=True)

        try:
            # Invia il comando
            print("  Debug: Writing command to stdin...", flush=True)
            self.stdin.write(cmd_str)
            self.stdin.flush()
            print("  Debug: Command written and flushed", flush=True)

            # Leggi eventuali errori con timeout
            print("  Debug: Reading stderr...", flush=True)
            errors = self._read_with_timeout(self.stderr, self.timeout)

            # Verifica il risultato
            success = len(errors) == 0 and output_path.exists()
            error_msg = ''.join(errors) if errors else None
            
            if error_msg:
                print(f"  Debug: cpp -E errors: {error_msg}", flush=True)
            print(f"  Debug: Output file exists: {output_path.exists()}", flush=True)
            if output_path.exists():
                print(f"  Debug: Output file size: {output_path.stat().st_size}", flush=True)

            return success, error_msg

        except TimeoutError:
            print("  Debug: cpp -E operation timed out", flush=True)
            self.stop()  # Riavvia il processo in caso di timeout
            self.start()
            return False, "Operation timed out"
        except Exception as e:
            print(f"  Debug: cpp -E error: {e}", flush=True)
            self.stop()  # Riavvia il processo in caso di errore
            self.start()
            return False, str(e)

def parse_arguments():
    parser = argparse.ArgumentParser(description='Preprocess C files in a project')
    parser.add_argument('--project-path', '-p', required=True, help='Path to the C project')
    parser.add_argument('--include-paths', '-i', nargs='+', default=['/usr/include'], help='System include paths')
    parser.add_argument('--output-dir', '-o', default='preprocessed', help='Output directory')
    parser.add_argument('--server-path', default='./cpp_api', help='Path to the cpp server executable')
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

def find_file_in_project(file_name: str, project_path: Path) -> Optional[Path]:
    """Cerca un file nel progetto usando find."""
    try:
        cmd = ['find', str(project_path), '-name', Path(file_name).name]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0 and result.stdout:
            matches = [Path(p) for p in result.stdout.strip().split('\n') if p]
            if matches:
                # Ordina per dimensione e prendi il più grande
                matches.sort(key=lambda x: x.stat().st_size if x.exists() else 0, reverse=True)
                return matches[0]
    except Exception:
        pass
    return None

def update_includes(file_path: Path, missing_file: str, update_all_headers: bool = False) -> None:
    """Aggiorna gli include nel file per usare i file copiati nella directory temporanea."""
    content = file_path.read_text()
    pattern = r'#include\s+".*?' + re.escape(missing_file) + r'"'
    matches = re.findall(pattern, content)
    
    if matches:
        new_content = re.sub(pattern, f'#include "{Path(missing_file).name}"', content)
        file_path.write_text(new_content)
    
    if update_all_headers:
        temp_dir = file_path.parent
        cmd = ['find', str(temp_dir), '-type', 'f', '(', '-name', '*.h', '-o', '-name', '*.c', ')']
        result = subprocess.run(cmd, capture_output=True, text=True)
        files_to_update = [Path(p) for p in result.stdout.strip().split('\n') if p]
        
        for file_to_update in files_to_update:
            if file_to_update != file_path:
                try:
                    content = file_to_update.read_text()
                    if missing_file in content:
                        new_content = re.sub(pattern, f'#include "{Path(missing_file).name}"', content)
                        file_to_update.write_text(new_content)
                except Exception:
                    continue

def preprocess_file(c_file: Path, project_path: Path, include_paths: List[Path], 
                   output_dir: Path, temp_dir: Path, cpp_process: CppProcess) -> bool:
    """
    Preprocessa un singolo file C risolvendo le dipendenze mancanti.
    """
    print(f"\nProcessing {c_file.relative_to(project_path)}", flush=True)
    
    rel_path = c_file.relative_to(project_path)
    out_path = output_dir / f"{rel_path}.i"
    err_path = output_dir / f"{rel_path}.err"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    temp_file = temp_dir / c_file.name
    shutil.copy2(c_file, temp_file)
    path_map = {str(temp_file): str(c_file)}
    
    # Loop di risoluzione delle dipendenze
    while True:
        success, err_msg = cpp_process.run_cpp_m(temp_file, [temp_dir] + include_paths)
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
        
        found_file = find_file_in_project(missing_file, project_path)
        if not found_file:
            print(f'  Failed: missing project dependency "{missing_file}"', flush=True)
            if err_msg:
                err_path.write_text(err_msg)
            return False
        
        temp_dep = temp_dir / found_file.name
        shutil.copy2(found_file, temp_dep)
        path_map[str(temp_dep)] = str(found_file)
        
        update_includes(temp_file, missing_file, update_all_headers=True)
    
    # Preprocessing finale
    success, err_msg = cpp_process.run_cpp_e(temp_file, [temp_dir] + include_paths, out_path)
    if not success:
        print("  Failed: preprocessing error", flush=True)
        if err_msg:
            err_path.write_text(err_msg)
        return False
    
    # Sostituisci i path temporanei con quelli originali
    content = out_path.read_text()
    for temp_path, orig_path in path_map.items():
        content = content.replace(temp_path, orig_path)
    out_path.write_text(content)
    
    print("  Success", flush=True)
    return True

def main():
    args = parse_arguments()
    print(f"\nStarting preprocessor with:", flush=True)
    print(f"- Project path: {args.project_path}", flush=True)
    print(f"- Include paths: {args.include_paths}", flush=True)
    print(f"- Output directory: {args.output_dir}", flush=True)
    print(f"- Server path: {args.server_path}", flush=True)
    
    # Setup directories
    project_out_dir, temp_dir = setup_directories(args.project_path, args.output_dir)
    print(f"\nCreated directories:", flush=True)
    print(f"- Project output directory: {project_out_dir}", flush=True)
    print(f"- Temporary directory: {temp_dir}", flush=True)
    
    # Crea il processo cpp persistente
    cpp_process = CppProcess()
    
    try:
        # Trova tutti i file .c del progetto
        print("\nFinding C files in project...", flush=True)
        c_files = find_c_files(args.project_path)
        print(f"Found {len(c_files)} C files", flush=True)
        
        # Preprocessa ogni file
        processed = 0
        skipped = 0
        
        for c_file in c_files:
            if preprocess_file(c_file, Path(args.project_path), 
                            [Path(p) for p in args.include_paths],
                            project_out_dir, temp_dir, cpp_process):
                processed += 1
            else:
                skipped += 1
            
            # Svuota la directory temporanea periodicamente
            if temp_dir.exists() and (skipped+processed)%200==0:
                for file in temp_dir.iterdir():
                    file.unlink()
            
            if(skipped+processed)==200:
                print("\nReached maximum file limit (200)", flush=True)
                break
        
        print(f"\nPreprocessing complete:", flush=True)
        print(f"- Successfully processed: {processed} files", flush=True)
        print(f"- Skipped: {skipped} files", flush=True)
        
    finally:
        # Pulisci la directory temporanea e ferma il processo cpp
        shutil.rmtree(temp_dir)
        cpp_process.stop()

if __name__ == '__main__':
    profiler = cProfile.Profile()
    profiler.enable()
    main()
    profiler.disable()
    stats = pstats.Stats(profiler).sort_stats('cumulative')
    stats.print_stats() 