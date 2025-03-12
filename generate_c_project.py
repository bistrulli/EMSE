import os
import random
import string
import argparse
from pathlib import Path
from typing import List, Optional

def generate_random_name(prefix='', length=8):
    """Generate a random name for files or directories."""
    chars = string.ascii_lowercase
    random_str = ''.join(random.choice(chars) for _ in range(length))
    return f"{prefix}{random_str}"

def create_header_file(path):
    """Create a dummy header file with random content."""
    with open(path, 'w') as f:
        guard_name = os.path.basename(path).replace('.', '_').upper()
        f.write(f"#ifndef {guard_name}\n")
        f.write(f"#define {guard_name}\n\n")
        
        # Add some dummy declarations
        num_declarations = random.randint(1, 5)
        for _ in range(num_declarations):
            func_name = generate_random_name('func_')
            f.write(f"void {func_name}(void);\n")
        
        f.write("\n#endif\n")

def create_c_file(path: str, headers: List[str], system_headers: Optional[List[str]] = None):
    """Create a C file that includes random headers and system headers."""
    with open(path, 'w') as f:
        # First add system includes if any
        if system_headers:
            num_sys_includes = random.randint(0, min(len(system_headers), 3))
            selected_sys_headers = random.sample(system_headers, num_sys_includes)
            for header in selected_sys_headers:
                f.write(f'#include <{header}>\n')
            if num_sys_includes > 0:
                f.write('\n')
        
        # Then add project headers
        if headers:
            num_includes = random.randint(1, len(headers))
            selected_headers = random.sample(headers, num_includes)
            for header in selected_headers:
                relative_path = os.path.relpath(header, os.path.dirname(path))
                f.write(f'#include "{relative_path}"\n')
            f.write('\n')
        
        if 'main.c' in path:
            f.write('int main(void) {\n')
            f.write('    return 0;\n')
            f.write('}\n')
        else:
            # Add some dummy function implementations
            num_functions = random.randint(1, 3)
            for _ in range(num_functions):
                func_name = generate_random_name('func_')
                f.write(f'void {func_name}(void) {{\n')
                f.write('    // TODO: Implementation\n')
                f.write('}\n\n')

def generate_c_project(root_dir: str, num_dirs: int = 3, num_headers: int = 5, 
                      num_c_files: int = 3, system_headers: Optional[List[str]] = None):
    """Generate a dummy C project structure."""
    # Create root directory if it doesn't exist
    os.makedirs(root_dir, exist_ok=True)
    
    # Create random subdirectories
    directories = [root_dir]
    for _ in range(num_dirs):
        parent_dir = random.choice(directories)
        new_dir = os.path.join(parent_dir, generate_random_name('dir_'))
        os.makedirs(new_dir)
        directories.append(new_dir)
    
    # Create header files
    header_files = []
    for _ in range(num_headers):
        dir_path = random.choice(directories)
        header_path = os.path.join(dir_path, f"{generate_random_name()}.h")
        create_header_file(header_path)
        header_files.append(header_path)
    
    # Create C files
    for _ in range(num_c_files):
        dir_path = random.choice(directories)
        c_path = os.path.join(dir_path, f"{generate_random_name()}.c")
        create_c_file(c_path, header_files, system_headers)
    
    # Create main.c in root directory
    main_path = os.path.join(root_dir, 'main.c')
    create_c_file(main_path, header_files, system_headers)

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Generate a dummy C project with random structure and files.',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    parser.add_argument(
        '--output-dir', '-o',
        default='dummy_c_project',
        help='Output directory for the generated project'
    )
    
    parser.add_argument(
        '--num-dirs', '-d',
        type=int,
        default=3,
        help='Number of subdirectories to create'
    )
    
    parser.add_argument(
        '--num-headers', '-H',
        type=int,
        default=5,
        help='Number of header files to generate'
    )
    
    parser.add_argument(
        '--num-c-files', '-c',
        type=int,
        default=3,
        help='Number of .c files to generate (excluding main.c)'
    )
    
    parser.add_argument(
        '--system-headers', '-s',
        nargs='+',
        default=['stdio.h', 'stdlib.h', 'string.h'],
        help='List of system headers to randomly include (e.g., stdio.h stdlib.h)'
    )
    
    return parser.parse_args()

if __name__ == '__main__':
    args = parse_arguments()
    
    # Generate the project with the specified parameters
    generate_c_project(
        root_dir=args.output_dir,
        num_dirs=args.num_dirs,
        num_headers=args.num_headers,
        num_c_files=args.num_c_files,
        system_headers=args.system_headers
    )
    
    print(f"Generated dummy C project in {args.output_dir}/")
    print(f"Project structure:")
    print(f"- {args.num_dirs} subdirectories")
    print(f"- {args.num_headers} header files")
    print(f"- {args.num_c_files + 1} C files (including main.c)")
    print(f"Available system headers: {', '.join(args.system_headers)}") 