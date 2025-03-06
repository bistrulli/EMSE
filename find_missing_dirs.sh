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

# Create output filename based on input filename
output_file="missing_$(basename "$1")"

echo "Finding directories in ../repos that are not in $1..."
echo "----------------------------------------"

# Find all directories in ../repos and save those not in the input file
find "../repos" -maxdepth 1 -mindepth 1 -type d -exec basename {} \; | while read dir; do
    if ! grep -q "^$dir$" "$1"; then
        echo "$dir" >> "$output_file"
    fi
done

# Count results
total_dirs=$(find "../repos" -maxdepth 1 -mindepth 1 -type d | wc -l)
missing_dirs=$(wc -l < "$output_file")

echo -e "\nSummary:"
echo "Total directories in ../repos: $total_dirs"
echo "Directories not in $1: $missing_dirs"
echo "Missing directories have been saved to: $output_file" 