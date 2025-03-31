#!/usr/bin/env python3
import re
import subprocess
from pathlib import Path
import argparse

def parse_arguments():
    parser = argparse.ArgumentParser(description='Check if missing project dependencies are actually missing')
    parser.add_argument('--log-file', '-l', required=True, help='Path to the preprocessor log file')
    parser.add_argument('--project-path', '-p', required=True, help='Path to the project root')
    return parser.parse_args()

def find_file_in_project(file_name: str, project_path: Path) -> list[Path]:
    """Cerca un file nel progetto usando find.
    
    Args:
        file_name: Nome del file da cercare
        project_path: Path del progetto
        
    Returns:
        Lista di path dove il file è stato trovato
    """
    try:
        cmd = ['find', str(project_path), '-name', Path(file_name).name]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0 and result.stdout:
            return [Path(p) for p in result.stdout.strip().split('\n') if p]
    except Exception as e:
        print(f"Error searching for {file_name}: {e}")
    return []

def analyze_log(log_file: Path, project_path: Path):
    """Analizza il file di log e verifica le dipendenze mancanti."""
    print(f"\nAnalyzing log file: {log_file}")
    print(f"Project path: {project_path}")
    print("\nResults:")
    print("-" * 80)
    
    # Pattern per trovare i messaggi di errore per dipendenze di progetto mancanti
    # Ora includiamo anche il nome del file che sta includendo
    pattern = r'Processing ([^\n]+)\n.*?Failed: missing project dependency "([^"]+)"'
    
    # Leggi il file di log
    with open(log_file, 'r') as f:
        log_content = f.read()
    
    # Trova tutte le dipendenze mancanti insieme al file che le include
    missing_deps = re.findall(pattern, log_content)
    
    if not missing_deps:
        print("No missing project dependencies found in the log.")
        return
    
    print(f"Found {len(missing_deps)} missing project dependencies:")
    print("-" * 80)
    
    # Per ogni dipendenza mancante
    for including_file, dep in missing_deps:
        # Se la dipendenza ha lo stesso nome del file che la include, la saltiamo
        if Path(dep).name == Path(including_file).name:
            print(f"\nSkipping dependency: {dep}")
            print(f"  Reason: Same name as including file {including_file}")
            print("-" * 40)
            continue
            
        print(f"\nChecking dependency: {dep}")
        print(f"  Including file: {including_file}")
        
        # Cerca il file nel progetto
        found_files = find_file_in_project(dep, project_path)
        
        if found_files:
            print(f"  Found {len(found_files)} occurrences:")
            for file in found_files:
                print(f"    - {file}")
        else:
            print("  Not found in project")
        
        print("-" * 40)

def main():
    args = parse_arguments()
    analyze_log(Path(args.log_file), Path(args.project_path))

if __name__ == '__main__':
    main() 