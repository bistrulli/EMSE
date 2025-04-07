#!/usr/bin/env python3

import os
import sys
import subprocess
import argparse
from tqdm import tqdm

# Costante per l'architettura del kernel (x86)
DEFAULT_ARCH = "x86"

def check_file_exists(file_path):
    """Verifica che un file esista"""
    if not os.path.isfile(file_path):
        print(f"ERROR: File not found: {file_path}")
        sys.exit(1)

def check_dir_exists(dir_path):
    """Verifica che una directory esista"""
    if not os.path.isdir(dir_path):
        return False
    return True

def read_file_lines(file_path):
    """Legge le righe non vuote da un file"""
    with open(file_path, 'r') as f:
        return [line.strip() for line in f if line.strip()]

def main():
    # Parsing degli argomenti
    parser = argparse.ArgumentParser(description='Run preprocessor on multiple projects with different kernel versions')
    parser.add_argument('projects_file', help='File containing project paths')
    parser.add_argument('kernel_versions_file', help='File containing kernel versions')
    parser.add_argument('kernel_base_dir', help='Base directory for kernel sources')
    args = parser.parse_args()
    
    # Verifica che i file di input esistano
    check_file_exists(args.projects_file)
    check_file_exists(args.kernel_versions_file)
    
    # Verifica che la directory base dei kernel esista
    if not check_dir_exists(args.kernel_base_dir):
        print(f"ERROR: Kernel base directory not found: {args.kernel_base_dir}")
        sys.exit(1)
    
    # Leggi i file di input
    projects = read_file_lines(args.projects_file)
    kernel_versions = read_file_lines(args.kernel_versions_file)
    
    # Crea la directory per i log se non esiste
    os.makedirs("preprocessing_logs", exist_ok=True)
    
    # Statistiche
    total_tasks = len(projects) * len(kernel_versions)
    successful = 0
    failed = 0
    
    # Crea una barra di progresso
    pbar = tqdm(total=total_tasks, desc="Processing", unit="task")
    
    # Iterazione su ogni progetto e versione del kernel
    for project in projects:
        for kernel_version in kernel_versions:
            # Costruisci i percorsi
            kernel_path = os.path.join(args.kernel_base_dir, kernel_version)
            log_file = f"preprocessing_logs/{os.path.basename(project)}_{kernel_version}.log"
            
            # Verifica che la directory del kernel esista
            if not check_dir_exists(kernel_path):
                print(f"\nWARNING: Kernel directory not found: {kernel_path}")
                failed += 1
                pbar.update(1)
                continue
            
            # Verifica che la directory del progetto esista
            if not check_dir_exists(project):
                print(f"\nWARNING: Project directory not found: {project}")
                failed += 1
                pbar.update(1)
                continue
            
            # Esegui il preprocessore
            print(f"\nProcessing {project} with kernel {kernel_version}")
            
            # Esegui lo script run_preprocessor_working.sh
            try:
                result = subprocess.run(
                    ["./run_preprocessor_working.sh", log_file, kernel_path, project, DEFAULT_ARCH],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                print(result.stdout)
                successful += 1
            except subprocess.CalledProcessError as e:
                print(f"ERROR while processing {project} with {kernel_version}:")
                print(e.stderr)
                failed += 1
            
            # Aggiorna la barra di progresso
            pbar.update(1)
    
    # Chiudi la barra di progresso
    pbar.close()
    
    # Stampa le statistiche
    print("\nPreprocessing completed!")
    print("Statistics:")
    print(f"- Total tasks: {total_tasks}")
    print(f"- Successful: {successful}")
    print(f"- Failed: {failed}")

if __name__ == "__main__":
    main() 