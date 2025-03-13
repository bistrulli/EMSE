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

def get_ramdisk_temp_dir():
    """Create or use a temporary directory in RAM for better I/O performance."""
    os_name = platform.system().lower()
    
    # On Linux, we can use /dev/shm which is already mounted as tmpfs (in RAM)
    if 'linux' in os_name:
        ram_temp = '/dev/shm/preprocessor_tmp'
        os.makedirs(ram_temp, exist_ok=True)
        return ram_temp
        
    # On macOS, use the built-in RAM disk if it exists, otherwise use the standard temp dir
    elif 'darwin' in os_name:
        # Check if we have permission to create files in /tmp
        if os.access('/tmp', os.W_OK):
            ram_temp = '/tmp/preprocessor_ramdisk'
            os.makedirs(ram_temp, exist_ok=True)
            return ram_temp
    
    # Fallback to standard temp directory for other OS or if RAM disk creation failed
    return tempfile.gettempdir()

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
    
    with open(c_file, 'r') as f:
        content = f.read()
    
    new_content = content
    for original_include in headers_to_process:
        new_include = os.path.basename(original_include)
        include_map[new_include] = original_include
        
        # Replace the include directive for both .h and .c files
        pattern = f'#include.*?[<"].*?{os.path.basename(original_include)}[>"]'
        new_content = re.sub(pattern, f'#include "{new_include}"', new_content)
    
    # Write back the modified content
    with open(c_file, 'w') as f:
        f.write(new_content)
    
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
        
    with open(preprocessed_file, 'r') as f:
        content = f.read()
    
    # Replace all temporary paths with original paths
    new_content = content
    for temp_path, orig_path in temp_to_orig_map.items():
        new_content = new_content.replace(temp_path, orig_path)
    
    with open(preprocessed_file, 'w') as f:
        f.write(new_content)

def get_project_relative_path(file_path: str, project_path: str) -> str:
    """Get the relative path of a file from the project root."""
    return os.path.relpath(file_path, project_path)

def update_includes(source_file: str, missing_file: str) -> None:
    """Update include directive in source file to use the flattened path."""
    with open(source_file, 'r') as f:
        content = f.read()
    
    # Extract the basename from the missing file path
    basename = os.path.basename(missing_file)
    
    # Create a regex pattern to match the include directive for this file
    # This will match both quoted and angled includes with any path format
    pattern = rf'#include\s+[<"].*?{re.escape(basename)}[>"]'
    
    # Replace with a flat include using the basename only
    replacement = f'#include "{basename}"'
    
    new_content = re.sub(pattern, replacement, content)
    
    with open(source_file, 'w') as f:
        f.write(new_content)

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
    os.makedirs(project_out_dir, exist_ok=True)
    
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
    
    # Get RAM disk temp directory
    ram_temp_dir = get_ramdisk_temp_dir()
    
    # Create a temporary directory for processing in RAM for better performance
    tmp_base_dir = os.path.join(ram_temp_dir, f"preprocessor_{os.getpid()}")
    try:
        # Create a subdirectory with the project name inside the temporary directory
        tmp_dir = os.path.join(tmp_base_dir, project_name)
        os.makedirs(tmp_dir, exist_ok=True)
        
        if verbose:
            print(f"Using RAM-based temporary directory: {tmp_dir}")
        
        # Dictionary to track original paths
        temp_to_orig_map = {}
        
        # Initialize progress bar
        progress_bar = tqdm(
            total=len(c_files),
            desc="Preprocessing C files",
            unit="file",
            disable=verbose,  # Disable progress bar when verbose output is enabled
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
            shutil.copy2(c_file, c_file_tmp)
            
            # Map temporary path to original path
            temp_to_orig_map[c_file_tmp] = c_file
            
            # Build include flags
            # 1. Temp directory (highest priority)
            # 2. User-provided include paths
            include_flags = [f'-I{tmp_dir}']
            include_flags.extend([f'-I{path}' for path in include_paths])
            
            # Initialize processing state
            is_processable = True
            
            # Initialize error log
            error_log = []
            
            # Set to track missing files we've already attempted to resolve to prevent infinite loops
            attempted_missing_files = set()
            
            # Define preprocessing function for repeated calls
            def run_preprocessor():
                """Run the preprocessor and capture any errors."""
                cmd = ['cpp', '-M'] + include_flags + [c_file_tmp]
                if verbose:
                    print(f"  Running preprocessor command: {' '.join(cmd)}")
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                    return True, None
                except subprocess.CalledProcessError as e:
                    return False, e.stderr
            
            # Define error parsing function
            def extract_missing_file(err_msg: str) -> Optional[str]:
                """Extract missing file name from error message."""
                if 'fatal error:' in err_msg and ('file not found' in err_msg or 'No such file or directory' in err_msg):
                    matches = re.findall(r"'([^']+\.[ch])'|\"([^\"]+\.[ch])\"", err_msg)
                    if matches:
                        for match in matches:
                            if match[0]:  # Match in first group (single quotes)
                                return match[0]
                            elif match[1]:  # Match in second group (double quotes)
                                return match[1]
                return None
            
            # Try preprocessing iteratively, looking for missing files
            max_iterations = float('inf')  # No limit on iterations
            current_iteration = 0
            
            while is_processable and current_iteration < max_iterations:
                current_iteration += 1
                
                success, err_msg = run_preprocessor()
                
                if success:
                    # Successfully generated dependencies, proceed to actual preprocessing
                    if verbose:
                        print(f"  Successfully determined dependencies")
                    break
                
                error_log.append(f"Error during dependency check (iteration {current_iteration}):\n{err_msg}\n")
                
                # Check if error is due to missing file
                missing_file = extract_missing_file(err_msg)
                
                if missing_file:
                    if verbose:
                        print(f"  Missing file detected: {missing_file}")
                    
                    basename = os.path.basename(missing_file)
                    
                    # Check if we've already tried to resolve this file to prevent infinite loops
                    if basename in attempted_missing_files:
                        if verbose:
                            print(f"  Already attempted to resolve {basename}, skipping to prevent loops")
                        is_processable = False
                        error_log = [f"Fatal error: Circular dependency detected for {basename}\n", f"{err_msg}\n"]
                        break
                        
                    # Add to our set of attempted files
                    attempted_missing_files.add(basename)
                    
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
                            shutil.copy2(match, dest)
                            
                            # Map temporary path to original path
                            temp_to_orig_map[dest] = match
                            
                            # Update include directive in the C file to use the flattened path
                            update_includes(c_file_tmp, missing_file)
                            
                            if verbose:
                                print(f"  Copied to temporary directory and updated include")
                            
                            # Try preprocessor with this file to see if it resolves the dependency
                            test_success, test_err = run_preprocessor()
                            
                            if test_success:
                                if verbose:
                                    print(f"  Successfully resolved missing file with exact path: {match_rel}")
                                # Clear error log since we're making progress
                                error_log = []
                            else:
                                # Check if the error is about a different missing file
                                new_missing_file = extract_missing_file(test_err)
                                if new_missing_file and new_missing_file != missing_file:
                                    if verbose:
                                        print(f"  Exact path match found for {basename}, but now missing: {new_missing_file}")
                                    # Keep exact_path_found as True, we successfully resolved this file
                                    # Clear error log since we're making progress
                                    error_log = []
                                    # Don't break, just continue with the next iteration of the while loop
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
                                shutil.copy2(match, dest)
                                
                                # Map temporary path to original path
                                temp_to_orig_map[dest] = match
                                
                                # Update include directive in the C file to use the flattened path
                                update_includes(c_file_tmp, missing_file)
                                
                                if verbose:
                                    print(f"  Copied to temporary directory and updated include")
                                
                                # Try preprocessor with this file to see if it resolves the dependency
                                test_success, test_err = run_preprocessor()
                                
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
                                    new_missing_file = extract_missing_file(test_err)
                                    if new_missing_file and new_missing_file != missing_file:
                                        if verbose:
                                            print(f"  File {match_rel} is correct, but now missing: {new_missing_file}")
                                        # This file is actually good, it helped resolve the original dependency
                                        # Clear error log since we're making progress
                                        error_log = []
                                        missing_file_resolved = True
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
                                shutil.copy2(match, dest)
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
                
                # Safety check for very large iteration counts
                if current_iteration > 1000:
                    if verbose:
                        print(f"  WARNING: Very high iteration count ({current_iteration}), possible loop detected")
                    
                    # Every 1000 iterations, log the current state to help debug
                    if current_iteration % 1000 == 0:
                        error_log.append(f"WARNING: High iteration count ({current_iteration}), possible loop detected\n")
                        error_log.append(f"Attempted missing files: {', '.join(attempted_missing_files)}\n")
            
            # Check if we exceeded max iterations
            if current_iteration >= max_iterations:
                if verbose:
                    print(f"  Exceeded maximum iterations ({max_iterations}), stopping")
                is_processable = False
                # Reset error log to only keep this error
                error_log = [f"Fatal error: Exceeded maximum number of iterations ({max_iterations})\n", f"Last error: {err_msg}\n"]
            
            # Try actual preprocessing if dependencies were resolved
            if is_processable:
                preprocessed_file = c_file_tmp + '.i'
                
                try:
                    if verbose:
                        print(f"  Running full preprocessing")
                    
                    cpp_result = subprocess.run(
                        ['cpp'] + include_flags + [c_file_tmp, '-o', preprocessed_file],
                        capture_output=True,
                        text=True,
                        check=True
                    )
                    
                    # Save any warnings to error log
                    if cpp_result.stderr:
                        error_log.append(f"Warnings during preprocessing:\n{cpp_result.stderr}\n")
                    
                    # Copy preprocessed file to output directory
                    shutil.copy2(preprocessed_file, out_path)
                    
                    # Apply postprocessing to replace temporary paths with original paths
                    if verbose:
                        print(f"  Applying postprocessing to replace temporary paths")
                    postprocess(out_path, temp_to_orig_map)
                    
                    if verbose:
                        rel_out_path = os.path.relpath(out_path)
                        print(f"  Successfully saved preprocessed file: {rel_out_path}")
                        if os.path.exists(err_path):
                            os.remove(err_path)
                    
                    processed_files += 1
                    progress_bar.set_postfix(processed=processed_files, skipped=skipped_files)
                    progress_bar.update(1)
                
                except subprocess.CalledProcessError as e:
                    # Reset error log to only keep the final error
                    error_log = [f"Fatal error during full preprocessing:\n", f"{e.stderr}\n"]
                    if verbose:
                        print(f"  Error during preprocessing: {e}")
                    skipped_files += 1
                    
                    # Save error log since processing failed
                    with open(err_path, 'w') as f:
                        f.write(f"Error log for {rel_path}:\n")
                        f.write("="*80 + "\n")
                        f.writelines(error_log)
            else:
                skipped_files += 1
                progress_bar.set_postfix(processed=processed_files, skipped=skipped_files)
                progress_bar.update(1)
                if verbose:
                    print(f"  Failed to preprocess: {rel_path}")
                
                # Save error log since processing failed - only the last error is saved
                with open(err_path, 'w') as f:
                    f.write(f"Error log for {rel_path}:\n")
                    f.write("="*80 + "\n")
                    f.writelines(error_log)
        
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
    
    return processed_files, skipped_files

if __name__ == '__main__':
    args = parse_arguments()
    
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