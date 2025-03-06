#!/bin/bash

# Check if a file path is provided
if [ $# -eq 0 ]; then
    echo "Usage: $0 <file_with_directories>"
    exit 1
fi

# Check if the provided path exists and is a file
if [ ! -f "$1" ]; then
    echo "Error: '$1' is not a valid file"
    exit 1
fi

# Check if ../repos exists
if [ ! -d "../repos" ]; then
    echo "Error: '../repos' directory does not exist"
    exit 1
fi

# Get all directories in ../repos with full paths
repos_dirs=$(find "../repos" -maxdepth 1 -mindepth 1 -type d)

# Read the input file and create a list of directory names
input_dirs=$(cat "$1" | tr -d '[:space:]')

# Function to display progress bar
progress_bar() {
    local current=$1
    local total=$2
    local width=50
    local percentage=$((current * 100 / total))
    local completed=$((current * width / total))
    local remaining=$((width - completed))
    
    printf "\rProgress: [%${completed}s%${remaining}s] %d%%" "" "" "$percentage"
}

# Count total directories for progress bar
total_dirs=$(echo "$repos_dirs" | wc -l)
current_dir=0
missing_dirs=0

# Create output filename based on input filename
output_file="missing_$(basename "$1")"

echo "Checking directories not listed in $1..."
echo "----------------------------------------"

# Clear output file if it exists
> "$output_file"

# Check each directory in repos
echo "$repos_dirs" | while IFS= read -r full_path; do
    # Get just the directory name without the path
    dir_name=$(basename "$full_path")
    
    # Skip empty lines
    [ -z "$dir_name" ] && continue
    
    # Check if directory name is in the input file
    if ! echo "$input_dirs" | grep -q "^$dir_name$"; then
        echo "$dir_name" >> "$output_file"
        ((missing_dirs++))
    fi
    
    ((current_dir++))
    progress_bar $current_dir $total_dirs
done

echo -e "\n\nSummary:"
echo "Total directories in ../repos: $total_dirs"
echo "Directories not in $1: $missing_dirs"
echo "Missing directories have been saved to: $output_file" 