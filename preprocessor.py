import os
import shutil
import subprocess
import re
import argparse
import tempfile
import platform
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set
try:
    from tqdm import tqdm
except ImportError:
    # Mock tqdm if not installed
    def tqdm(iterable=None, **kwargs):
        if iterable is not None:
            return iterable
        return lambda x: x
    
verbose=False

def get_ramdisk_temp_dir():
    """Create a temporary directory with correct permissions."""
    # Test the standard temporary directory for write permissions
    system_tmpdir = tempfile.gettempdir()
    test_file_path = os.path.join(system_tmpdir, f"preprocessor_test_{os.getpid()}")
    try:
        with open(test_file_path, 'w') as f:
            f.write("test")
        os.unlink(test_file_path)
    except (PermissionError, OSError) as e:
        # Fail immediately with a clear error message
        raise RuntimeError(f"ERROR: Cannot write to temporary directory {system_tmpdir}: {e}\n"
                          f"The preprocessor requires write access to the temporary directory.\n"
                          f"Please ensure you have the necessary permissions.")
    
    # Create a temporary directory
    try:
        return tempfile.mkdtemp(prefix="preprocessor_")
    except Exception as e:
        # If we can't create a temporary directory, raise an error
        raise RuntimeError(f"ERROR: Failed to create temporary directory: {e}\n"
                          f"Please check your system's temporary directory permissions.")

def get_source_files(project_path: str) -> List[str]:
    """Get all .c and .h files in the project, sorted by size."""
    source_files = []
    for root, _, files in os.walk(project_path):
        for file in files:
            if file.endswith(('.c', '.h')):
                full_path = os.path.join(root, file)
                source_files.append(full_path)
    
    # Sort by file size
    return sorted(source_files, key=lambda x: os.path.getsize(x))

def get_missing_headers(cpp_error: str) -> Set[str]:
    """Parse cpp error message to get all missing header and source file paths."""
    # Pattern for cpp error message about missing headers and source files
    pattern = r'(?:.*?)[: ]([^:]+\.[ch])(?::|$)'
    return set(re.findall(pattern, cpp_error))

def flattening_includes(c_file: str, headers_to_process: Set[str], tmp_dir: str) -> Dict[str, str]:
    """Modify all include directives in the C file to point to tmp_dir."""
    include_map = {}
    
    # Prova diverse codifiche di caratteri
    codecs_to_try = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
    content = None
    
    # Tenta di leggere il file con diverse codifiche
    for codec in codecs_to_try:
        try:
            with open(c_file, 'r', encoding=codec) as f:
                content = f.read()
            # Se siamo qui, la lettura è andata a buon fine
            used_codec = codec
            break
        except UnicodeDecodeError:
            continue
    
    # Se non siamo riusciti a leggere il file con nessuna codifica, prova in modalità binaria
    if content is None:
        try:
            with open(c_file, 'rb') as f:
                binary_content = f.read()
            content = binary_content.decode('ascii', errors='replace')
            used_codec = 'ascii'
        except Exception as e:
            raise RuntimeError(f"ERROR: Could not read file {c_file} with any supported encoding: {e}")
    
    new_content = content
    for original_include in headers_to_process:
        new_include = os.path.basename(original_include)
        include_map[new_include] = original_include
        
        # Replace the include directive for both .h and .c files
        pattern = f'#include.*?[<"].*?{os.path.basename(original_include)}[>"]'
        new_content = re.sub(pattern, f'#include "{new_include}"', new_content)
    
    # Write back the modified content with the same encoding
    try:
        if used_codec == 'ascii':
            # Se abbiamo usato l'approccio binario+ascii, salva in binario
            with open(c_file, 'wb') as f:
                f.write(new_content.encode('ascii', errors='replace'))
        else:
            # Altrimenti usa la codifica che ha funzionato
            with open(c_file, 'w', encoding=used_codec) as f:
                f.write(new_content)
    except Exception as e:
        raise RuntimeError(f"ERROR: Could not write to file {c_file}: {e}")
    
    return include_map

def find_files_by_name(project_path: str, filename: str) -> List[str]:
    """Find all files with a given name in the project directory, sorted by size in descending order."""
    matches = []
    for root, _, files in os.walk(project_path):
        if filename in files:
            full_path = os.path.join(root, filename)
            matches.append(full_path)
    
    # Sort by file size in descending order
    matches.sort(key=lambda x: os.path.getsize(x), reverse=True)
    
    if len(matches) > 0 and os.path.exists('/tmp/debug_sort.log'):
        with open('/tmp/debug_sort.log', 'a') as f:
            f.write(f"\nMatches for {filename}:\n")
            for m in matches:
                f.write(f"  {m} ({os.path.getsize(m)} bytes)\n")
    
    return matches

def get_headers_from_list(source_files: List[str], include_paths: Set[str], project_path: str) -> Dict[str, str]:
    """Find the full paths of header files in the source files list."""
    header_map = {}
    for include_path in include_paths:
        # Remove leading/trailing whitespace and any leading './'
        include_path = include_path.strip()
        if include_path.startswith('./'):
            include_path = include_path[2:]
            
        # Get both the basename and the relative path without leading ../
        header_name = os.path.basename(include_path)
        header_rel_path = include_path.replace('../', '')
        
        # Strategy 1: Try exact path match (including relative path)
        for source_file in source_files:
            if source_file.endswith(header_rel_path):
                header_map[header_name] = source_file
                break
                
        # Strategy 2: Try matching by name in any directory
        if header_name not in header_map:
            for source_file in source_files:
                if os.path.basename(source_file) == header_name:
                    # If we find multiple matches, prefer files in similar paths
                    if header_rel_path in source_file:
                        header_map[header_name] = source_file
                        break
                    elif header_name not in header_map:
                        header_map[header_name] = source_file
        
        # Strategy 3: Do a thorough search in the project directory
        if header_name not in header_map:
            matches = []
            for root, _, files in os.walk(project_path):
                if header_name in files:
                    full_path = os.path.join(root, header_name)
                    # If we find the file in a path containing parts of the relative path
                    # it's more likely to be the correct one
                    if header_rel_path in full_path:
                        matches.insert(0, full_path)  # Put at the beginning
                    else:
                        matches.append(full_path)
            
            if matches:
                # Sort matches by size in descending order
                matches.sort(key=lambda x: os.path.getsize(x), reverse=True)
                # Prefer matches that contain parts of the relative path
                header_map[header_name] = matches[0]
                    
    return header_map

def postprocess(preprocessed_file: str, temp_to_orig_map: Dict[str, str]):
    """Postprocess the preprocessed file to restore original include paths.
    
    Args:
        preprocessed_file: Path to the preprocessed .i file
        temp_to_orig_map: Dictionary mapping temporary file paths to original file paths
    """
    if not os.path.exists(preprocessed_file):
        return
    
    # Prova diverse codifiche di caratteri
    codecs_to_try = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
    content = None
    
    # Tenta di leggere il file con diverse codifiche
    for codec in codecs_to_try:
        try:
            with open(preprocessed_file, 'r', encoding=codec) as f:
                content = f.read()
            # Se siamo qui, la lettura è andata a buon fine
            used_codec = codec
            break
        except UnicodeDecodeError:
            continue
    
    # Se non siamo riusciti a leggere il file con nessuna codifica, prova in modalità binaria
    if content is None:
        try:
            with open(preprocessed_file, 'rb') as f:
                binary_content = f.read()
            content = binary_content.decode('ascii', errors='replace')
            used_codec = 'ascii'
        except Exception as e:
            # In caso di file binario preprocessato, non possiamo fare il postprocessing
            # Questo è un caso raro ma possibile
            print(f"WARNING: Could not read preprocessed file {preprocessed_file} with any supported encoding.")
            print(f"Skipping postprocessing for this file.")
            return
    
    # Replace all temporary paths with original paths
    new_content = content
    for temp_path, orig_path in temp_to_orig_map.items():
        new_content = new_content.replace(temp_path, orig_path)
    
    # Write back the modified content with the same encoding
    try:
        if used_codec == 'ascii':
            # Se abbiamo usato l'approccio binario+ascii, salva in binario
            with open(preprocessed_file, 'wb') as f:
                f.write(new_content.encode('ascii', errors='replace'))
        else:
            # Altrimenti usa la codifica che ha funzionato
            with open(preprocessed_file, 'w', encoding=used_codec) as f:
                f.write(new_content)
    except Exception as e:
        print(f"WARNING: Could not write to preprocessed file {preprocessed_file}: {e}")
        print(f"Original file will remain unchanged.")

def get_project_relative_path(file_path: str, project_path: str) -> str:
    """Get the relative path of a file from the project root."""
    return os.path.relpath(file_path, project_path)

def update_includes(source_file: str, missing_file: str) -> None:
    """Update include directive in source file to use the flattened path."""
    # Estrai il basename dal percorso del file mancante
    basename = os.path.basename(missing_file)
    
    # Crea un pattern regex per trovare la direttiva include per questo file
    # Questo corrisponderà sia agli include con virgolette che a quelli con parentesi angolari
    pattern = rf'#include\s+[<"].*?{re.escape(basename)}[>"]'
    
    # Sostituisci con un include flat usando solo il basename
    replacement = f'#include "{basename}"'
    
    # Prova diverse codifiche di caratteri
    codecs_to_try = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
    
    for codec in codecs_to_try:
        try:
            # Prova a leggere il file con la codifica corrente
            with open(source_file, 'r', encoding=codec) as f:
                content = f.read()
            
            # Se abbiamo letto con successo, aggiorna il contenuto
            new_content = re.sub(pattern, replacement, content)
            
            # Scrivi il contenuto aggiornato usando la stessa codifica
            with open(source_file, 'w', encoding=codec) as f:
                f.write(new_content)
            
            # Abbiamo avuto successo, usciamo dal ciclo
            return
        except UnicodeDecodeError:
            # Questa codifica non ha funzionato, prova la prossima
            continue
        except PermissionError as e:
            raise RuntimeError(f"ERROR: Permission denied when trying to update includes in {source_file}: {e}\n"
                              f"The preprocessor requires write access to files in the temporary directory.")
    
    # Se siamo qui, tutte le codifiche hanno fallito, prova l'approccio binario
    try:
        # Leggi il file in modalità binaria
        with open(source_file, 'rb') as f:
            binary_content = f.read()
        
        # Converti il pattern e il replacement in byte
        pattern_bytes = pattern.encode('utf-8')
        replacement_bytes = replacement.encode('utf-8')
        
        # Cerca di fare la sostituzione trattando come testo ASCII
        # Questo approccio non è perfetto, ma è un fallback
        ascii_content = binary_content.decode('ascii', errors='replace')
        new_content = re.sub(pattern, replacement, ascii_content)
        
        # Scrivi di nuovo in binario
        with open(source_file, 'wb') as f:
            f.write(new_content.encode('ascii', errors='replace'))
            
    except Exception as e:
        # Se anche l'approccio binario fallisce, segnala l'errore dettagliato
        raise RuntimeError(f"ERROR: Could not process file {source_file} with any supported encoding: {e}\n"
                          f"File appears to contain binary or corrupted data.")

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='''
        Preprocess C source files in a project by flattening includes and handling dependencies.
        
        This script:
        1. Takes a C project as input
        2. Processes each .c file, handling its include dependencies
        3. Creates preprocessed versions (.i files) in the output directory
        4. Maintains the original project structure
        5. Uses temporary directory for intermediate files
        
        Example usage:
            %(prog)s -p /path/to/project -i /usr/include -i /usr/local/include
            %(prog)s -p myproject --output-dir preprocessed
        ''',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        '--project-path', '-p',
        required=True,
        help='Path to the C project to preprocess'
    )
    
    parser.add_argument(
        '--include-paths', '-i',
        nargs='+',
        default=['/usr/include', '/usr/local/include'],
        help='List of system include paths to use during preprocessing'
    )
    
    parser.add_argument(
        '--output-dir', '-o',
        default='preprocessed',
        help='Directory where preprocessed files will be saved'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Print detailed progress information'
    )
    
    return parser.parse_args()

def find_header_directories(project_path: str) -> List[str]:
    """Find standard directories where headers are typically located in C projects."""
    header_dirs = []
    
    # Common header directory patterns
    common_patterns = [
        'include',
        'includes',
        'headers',
        'inc',
        'src/include',
        'lib/include'
    ]
    
    # Find all directories that match common patterns or contain header files
    for root, dirs, files in os.walk(project_path):
        # Check if this directory or any parent matches common patterns
        dir_name = os.path.basename(root)
        if any(pattern in dir_name.lower() for pattern in common_patterns):
            header_dirs.append(root)
            continue
            
        # Check if this directory contains header files
        if any(file.endswith('.h') for file in files):
            header_dirs.append(root)
    
    return header_dirs

# Define preprocessing function for repeated calls
def run_preprocessor(include_flags=None,c_file_tmp=None,
                     preprocessed_file=None):
        """Run the preprocessor and capture any errors."""
        cmd = ['cpp', '-M'] + include_flags + [c_file_tmp]

        if(preprocessed_file is not None):
            cmd+=['-o', preprocessed_file]

        if verbose:
            print(f"  Running preprocessor command: {' '.join(cmd)}")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return True, None
        except subprocess.CalledProcessError as e:
            return False, e.stderr

# Define error parsing function
def extract_missing_file(err_msg: str) -> Optional[Tuple[str, bool]]:
    """Extract missing file name from error message and determine if it's a system include.
    
    Returns:
        Tuple of (filename, is_system_include) or None if no match found
    """
    if 'fatal error:' in err_msg and ('file not found' in err_msg or 'No such file or directory' in err_msg):
        # Try to match both system includes (<>) and local includes ("")
        system_match = re.search(r'<([^>]+\.[ch])>', err_msg)
        local_match = re.search(r'"([^"]+\.[ch])"', err_msg)
        
        if system_match:
            return system_match.group(1), True
        elif local_match:
            return local_match.group(1), False
    return None

def preprocess_project(project_path: str, include_paths: List[str], 
                      output_base_dir: str, verbose: bool = False):
    """Main function to preprocess a C project using an iterative approach."""
    # Convert paths to absolute paths
    project_path = os.path.abspath(project_path)
    output_base_dir = os.path.abspath(output_base_dir)
    
    # Get project name and setup directories
    project_name = os.path.basename(project_path)
    project_out_dir = os.path.join(output_base_dir, project_name)
    
    if verbose:
        print(f"Processing project: {project_name}")
        print(f"Output directory: {os.path.relpath(project_out_dir)}")
    
    # Create output directory
    try:
        os.makedirs(project_out_dir, exist_ok=True)
    except PermissionError as e:
        raise RuntimeError(f"ERROR: Cannot create output directory {project_out_dir}: {e}\n"
                          f"Please check that you have write permissions to {output_base_dir}")

    # Find standard header directories in the project
    standard_include_dirs = find_header_directories(project_path)
    
    # Get sorted list of source files
    source_files = get_source_files(project_path)
    
    # Count C and H files
    c_files = [f for f in source_files if f.endswith('.c')]
    h_files = [f for f in source_files if f.endswith('.h')]
    
    if verbose:
        print(f"Found {len(c_files)} C files and {len(h_files)} header files")
    
    # Process each C file
    processed_files = 0
    skipped_files = 0
    error_files = []  # Lista per tenere traccia dei file che hanno generato errori
    
    # Create a temporary directory with proper permissions
    try:
        tmp_base_dir = get_ramdisk_temp_dir()
    except Exception as e:
        raise

    try:
        # Create a subdirectory with the project name inside the temporary directory
        tmp_dir = os.path.join(tmp_base_dir, project_name)
        try:
            os.makedirs(tmp_dir, exist_ok=True)
            os.chmod(tmp_dir, 0o755)
        except PermissionError as e:
            raise RuntimeError(f"ERROR: Cannot set permissions on temporary directory {tmp_dir}: {e}\n"
                             f"The preprocessor requires full write access to the temporary directory.")
        
        if verbose:
            print(f"Using temporary directory: {tmp_dir}")
        
        # Dictionary to track original paths
        temp_to_orig_map = {}
        
        # Initialize progress bar
        progress_bar = tqdm(
            total=len(c_files),
            desc="Preprocessing C files",
            unit="file",
            disable=verbose,
            bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]"
        )
        
        for c_file in c_files:
            # Calculate relative path and create output paths
            rel_path = os.path.relpath(c_file, project_path)
            out_path = os.path.join(project_out_dir, rel_path + '.i')
            err_path = os.path.join(project_out_dir, rel_path + '.err')
            
            # Update progress bar description with current file
            progress_bar.set_description(f"Processing {os.path.basename(c_file)}")
            
            if verbose:
                print(f"\nProcessing: {rel_path}")
                
            # Create directory structure
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
                
            # Get the directory of the current C file for relative includes
            c_file_dir = os.path.dirname(c_file)
            
            # Copy C file to temporary directory
            c_file_tmp = os.path.join(tmp_dir, os.path.basename(c_file))
            
            # Make sure the parent directory exists with correct permissions
            parent_dir = os.path.dirname(c_file_tmp)
            if not os.path.exists(parent_dir):
                try:
                    os.makedirs(parent_dir, mode=0o755, exist_ok=True)
                except PermissionError as e:
                    raise RuntimeError(f"ERROR: Cannot create directory {parent_dir}: {e}\n"
                                      f"The preprocessor requires full write access to all subdirectories.")
            
            try:
                shutil.copy2(c_file, c_file_tmp)
                os.chmod(c_file_tmp, 0o644)
                temp_to_orig_map[c_file_tmp] = c_file
            except PermissionError as e:
                raise RuntimeError(f"ERROR: Permission denied when copying {c_file} to {c_file_tmp}: {e}\n"
                                  f"The preprocessor requires full write access to the temporary directory.")
            
            # Build include flags
            include_flags = [f'-I{tmp_dir}']
            include_flags.extend([f'-I{path}' for path in include_paths])
            
            # Initialize processing state
            is_processable = True
            error_log = []
            attempted_missing_files = set()
            
            while is_processable:
                success, err_msg = run_preprocessor(include_flags,c_file_tmp)
                
                if success:
                    if verbose:
                        print(f"  Successfully determined dependencies")
                    break
                
                error_log.append(f"Error during dependency check:\n{err_msg}\n")
                
                # Check if error is due to missing file
                missing_file_info = extract_missing_file(err_msg)
                
                if missing_file_info:
                    missing_file, is_system_include = missing_file_info
                    
                    basename = os.path.basename(missing_file)
                    
                    # Check if we've already tried to resolve this file to prevent infinite loops
                    if basename in attempted_missing_files:
                        is_processable = False
                        error_log = [f"Fatal error: Circular dependency detected for {basename}\n", f"{err_msg}\n"]
                        if verbose:
                            print(f"FATAL ERROR: {os.path.relpath(err_path)}")
                        break
                        
                    attempted_missing_files.add(basename)
                    
                    # If it's a system include and not found, mark as not processable
                    if is_system_include:
                        is_processable = False
                        error_log = [f"Fatal error: System include {missing_file} not found in system paths\n", f"{err_msg}\n"]
                        if verbose:
                            print(f"FATAL ERROR: {os.path.relpath(err_path)}")
                        break
                    
                    # For local includes, proceed with project-wide search
                    # Strategy 1: Try exact path first
                    exact_path_found = False
                    
                    # Try relative to the current C file
                    if not os.path.isabs(missing_file):
                        possible_paths = []
                        
                        # Try relative to the original C file directory
                        rel_to_c_file = os.path.join(c_file_dir, missing_file)
                        if os.path.exists(rel_to_c_file):
                            possible_paths.append(rel_to_c_file)
                            
                        # Try relative to project root
                        rel_to_project = os.path.join(project_path, missing_file)
                        if os.path.exists(rel_to_project) and rel_to_project not in possible_paths:
                            possible_paths.append(rel_to_project)
                        
                        if possible_paths:
                            exact_path_found = True
                            match = possible_paths[0]  # Take the first found path
                            match_rel = os.path.relpath(match, project_path)
                            
                            if verbose:
                                print(f"  Found exact path match: {match_rel}")
                            
                            # Copy to temp directory with project name
                            dest = os.path.join(tmp_dir, basename)
                            
                            # Ensure the parent directory exists with correct permissions
                            parent_dir = os.path.dirname(dest)
                            if not os.path.exists(parent_dir):
                                try:
                                    os.makedirs(parent_dir, mode=0o755, exist_ok=True)
                                except PermissionError as e:
                                    raise RuntimeError(f"ERROR: Cannot create directory {parent_dir}: {e}\n"
                                                     f"The preprocessor requires full write access to all subdirectories.")
                                
                            shutil.copy2(match, dest)
                            
                            # Ensure the copied file is writable
                            try:
                                os.chmod(dest, 0o644)
                            except Exception as e:
                                raise RuntimeError(f"ERROR: Cannot set permissions for file {dest}: {e}\n"
                                                 f"The preprocessor requires permissions to modify files in the temporary directory.")
                                
                            # Map temporary path to original path
                            temp_to_orig_map[dest] = match
                            
                            # Update include directive in the C file to use the flattened path
                            update_includes(c_file_tmp, missing_file)
                            
                            if verbose:
                                print(f"  Copied to temporary directory and updated include")
                            
                            # Try preprocessor with this file to see if it resolves the dependency
                            test_success, test_err = run_preprocessor(include_flags,c_file_tmp)
                            
                            if test_success:
                                if verbose:
                                    print(f"  Successfully resolved missing file with exact path: {match_rel}")
                                # Clear error log since we're making progress
                                error_log = []
                            else:
                                # Check if the error is about a different missing file
                                new_missing_file_info = extract_missing_file(test_err)
                                if new_missing_file_info:
                                    new_missing_file, new_is_system_include = new_missing_file_info
                                    if new_missing_file != missing_file:
                                        if verbose:
                                            print(f"  Exact path match found for {basename}, but now missing: {new_missing_file}")
                                        # Keep exact_path_found as True, we successfully resolved this file
                                        # Clear error log since we're making progress
                                        error_log = []
                                        # Don't break, just continue with the next iteration of the while loop
                                    elif new_is_system_include:
                                        if verbose:
                                            print(f"  Exact path match found but now missing system include: {new_missing_file}")
                                        is_processable = False
                                        error_log = [f"Fatal error: System include {new_missing_file} not found in system paths\n", f"{test_err}\n"]
                                        break
                                else:
                                    if verbose:
                                        print(f"  Exact path match did not resolve dependency")
                                    exact_path_found = False
                    
                    # Strategy 2: If exact path didn't work, find file in project
                    if not exact_path_found:
                        if verbose:
                            print(f"  Exact path not found or didn't resolve dependency, searching project-wide")
                            
                        # Find file in project
                        matches = find_files_by_name(project_path, basename)
                        
                        if matches:
                            # Log information about how many files with the same name were found
                            if verbose:
                                print(f"  Found {len(matches)} files with name '{basename}' in project")
                                print(f"  Files are sorted by size in descending order:")
                                for i, m in enumerate(matches[:5]):  # Show top 5 to avoid log clutter
                                    size_kb = os.path.getsize(m) / 1024
                                    print(f"    {i+1}. {os.path.relpath(m, project_path)} ({size_kb:.2f} KB)")
                                if len(matches) > 5:
                                    print(f"    ... and {len(matches) - 5} more")
                        
                            # Try each matching file, starting with the largest, until preprocessing succeeds
                            missing_file_resolved = False
                            tried_files = []
                            
                            for match in matches:
                                match_rel = os.path.relpath(match, project_path)
                                tried_files.append(match_rel)
                                
                                if verbose:
                                    print(f"  Trying matching file: {match_rel} ({os.path.getsize(match)} bytes)")
                                
                                # Copy to temp directory with project name
                                dest = os.path.join(tmp_dir, basename)
                                
                                # Ensure the parent directory exists with correct permissions
                                parent_dir = os.path.dirname(dest)
                                if not os.path.exists(parent_dir):
                                    try:
                                        os.makedirs(parent_dir, mode=0o755, exist_ok=True)
                                    except PermissionError as e:
                                        raise RuntimeError(f"ERROR: Cannot create directory {parent_dir}: {e}\n"
                                                         f"The preprocessor requires full write access to all subdirectories.")
                                    
                                shutil.copy2(match, dest)
                                
                                # Ensure the copied file is writable
                                try:
                                    os.chmod(dest, 0o644)
                                except Exception as e:
                                    raise RuntimeError(f"ERROR: Cannot set permissions for file {dest}: {e}\n"
                                                     f"The preprocessor requires permissions to modify files in the temporary directory.")
                                
                                # Map temporary path to original path
                                temp_to_orig_map[dest] = match
                                
                                # Update include directive in the C file to use the flattened path
                                update_includes(c_file_tmp, missing_file)
                                
                                if verbose:
                                    print(f"  Copied to temporary directory and updated include")
                                
                                # Try preprocessor with this file to see if it resolves the dependency
                                test_success, test_err = run_preprocessor(include_flags,c_file_tmp)
                                
                                if test_success:
                                    if verbose:
                                        print(f"  Successfully resolved missing file with: {match_rel}")
                                    # Clear error log since we're making progress
                                    error_log = []
                                    missing_file_resolved = True
                                    break
                                else:
                                    # Check if the error is for a different missing file - that means this file
                                    # is probably correct but we need to resolve more dependencies
                                    new_missing_file_info = extract_missing_file(test_err)
                                    if new_missing_file_info:
                                        new_missing_file, new_is_system_include = new_missing_file_info
                                        if new_missing_file != missing_file:
                                            if verbose:
                                                print(f"  File {match_rel} is correct, but now missing: {new_missing_file}")
                                            # This file is actually good, it helped resolve the original dependency
                                            # Clear error log since we're making progress
                                            error_log = []
                                            missing_file_resolved = True
                                            break
                                        elif new_is_system_include:
                                            if verbose:
                                                print(f"  File {match_rel} is correct, but now missing system include: {new_missing_file}")
                                            is_processable = False
                                            error_log = [f"Fatal error: System include {new_missing_file} not found in system paths\n", f"{test_err}\n"]
                                            break
                                        else:
                                            if verbose:
                                                print(f"  This file did not resolve the dependency, trying next match...")
                            
                            if not missing_file_resolved:
                                if verbose:
                                    print(f"  Tried {len(tried_files)} matching files but none resolved the dependency")
                                    print(f"  Using the largest file as a best effort: {tried_files[0]}")
                                # Use the largest file anyway as a last resort
                                dest = os.path.join(tmp_dir, basename)
                                match = matches[0]
                                
                                # Ensure the parent directory exists with correct permissions
                                parent_dir = os.path.dirname(dest)
                                if not os.path.exists(parent_dir):
                                    try:
                                        os.makedirs(parent_dir, mode=0o755, exist_ok=True)
                                    except PermissionError as e:
                                        raise RuntimeError(f"ERROR: Cannot create directory {parent_dir}: {e}\n"
                                                         f"The preprocessor requires full write access to all subdirectories.")
                                    
                                shutil.copy2(match, dest)
                                
                                # Ensure the copied file is writable
                                try:
                                    os.chmod(dest, 0o644)
                                except Exception as e:
                                    raise RuntimeError(f"ERROR: Cannot set permissions for file {dest}: {e}\n"
                                                     f"The preprocessor requires permissions to modify files in the temporary directory.")
                                
                                temp_to_orig_map[dest] = match
                                update_includes(c_file_tmp, missing_file)
                                
                                # Reset error log to show we tried all options
                                error_log = [
                                    f"Warning: Tried multiple files matching {basename} but none resolved all dependencies\n",
                                    f"Files tried: {', '.join(tried_files)}\n",
                                    f"Using the largest file ({tried_files[0]}) as a best effort\n",
                                    f"Original error: {err_msg}\n"
                                ]
                        else:
                            if verbose:
                                print(f"  Could not find {missing_file} in project")
                            is_processable = False
                            # Reset error log to only keep the last error
                            error_log = [f"Fatal error: Missing file {missing_file} not found in project\n", f"{err_msg}\n"]
                else:
                    if verbose:
                        print(f"  Error not related to missing file")
                    is_processable = False
                    # Reset error log to only keep the last error
                    error_log = [f"Fatal error: Preprocessing failed with error not related to missing files\n", f"{err_msg}\n"]
            
            # Try actual preprocessing if dependencies were resolved
            if is_processable:
                preprocessed_file = c_file_tmp + '.i'
                
                try:
                    if verbose:
                        print(f"  Running full preprocessing")
                    
                    success, err_msg = run_preprocessor(include_flags,c_file_tmp,preprocessed_file)
                    
                    # Copy preprocessed file to output directory
                    shutil.copy2(preprocessed_file, out_path)
                    
                    # Apply postprocessing to replace temporary paths with original paths
                    if verbose:
                        print(f"  Applying postprocessing to replace temporary paths")
                    postprocess(out_path, temp_to_orig_map)
                    
                    if verbose:
                        rel_out_path = os.path.relpath(out_path)
                        print(f"  Successfully saved preprocessed file: {rel_out_path}")
                    
                    processed_files += 1
                    progress_bar.set_postfix(processed=processed_files, skipped=skipped_files)
                    progress_bar.update(1)
                
                except subprocess.CalledProcessError as e:
                    error_msg = e.stderr.strip()
                    
                    # Save detailed error to .err file
                    with open(err_path, 'w') as f:
                        f.write(f"Error during preprocessing:\n{error_msg}\n")
                    
                    if verbose:
                        print(f"FATAL ERROR: {os.path.relpath(err_path)}")
                    
                    skipped_files += 1
                    error_files.append((rel_path, error_msg))
                    progress_bar.set_postfix(processed=processed_files, skipped=skipped_files)
                    progress_bar.update(1)
            else:
                skipped_files += 1
                progress_bar.set_postfix(processed=processed_files, skipped=skipped_files)
                progress_bar.update(1)
                
                # Save detailed error to .err file
                if error_log:
                    error_msg = ' '.join(error_log).strip()
                    with open(err_path, 'w') as f:
                        f.write(error_msg)
                    
                    if verbose:
                        print(f"FATAL ERROR: {os.path.relpath(err_path)}")
                    
                    error_files.append((rel_path, error_msg))
                else:
                    if verbose:
                        print(f"FATAL ERROR: {os.path.relpath(err_path)}")
                    error_files.append((rel_path, "Unknown error during preprocessing"))
        
        # Close progress bar
        progress_bar.close()
        
        # Clean up temporary directory
        shutil.rmtree(tmp_base_dir, ignore_errors=True)
        
    except Exception as e:
        # Clean up in case of error
        shutil.rmtree(tmp_base_dir, ignore_errors=True)
        raise e
    
    if verbose:
        print(f"\nPreprocessing complete:")
        print(f"- Successfully processed: {processed_files} files")
        print(f"- Skipped: {skipped_files} files")
        
        if error_files:
            print(f"\nError files generated:")
            for rel_path, _ in error_files:
                print(f"- {os.path.join(project_out_dir, rel_path + '.err')}")
    
    return processed_files, skipped_files

if __name__ == '__main__':
    args = parse_arguments()

    verbose=args.verbose
    
    processed, skipped = preprocess_project(
        project_path=args.project_path,
        include_paths=args.include_paths,
        output_base_dir=args.output_dir,
        verbose=args.verbose
    )
    
    if not args.verbose:
        print(f"\nPreprocessing complete:")
        print(f"- Successfully processed: {processed} files")
        print(f"- Skipped: {skipped} files") 