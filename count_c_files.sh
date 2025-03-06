#!/bin/bash

# Check if a directory path is provided
if [ $# -eq 0 ]; then
    echo "Usage: $0 <directory_path>"
    exit 1
fi

# Check if the provided path exists and is a directory
if [ ! -d "$1" ]; then
    echo "Error: '$1' is not a valid directory"
    exit 1
fi

# Find all .c files recursively and sum their sizes in bytes
total_size=$(find "$1" -type f -name "*.c" -printf "%s\n" | awk '{sum += $1} END {print sum}')

# Print the total size in bytes
if [ -n "$total_size" ]; then
    echo "$total_size"
else
    echo "0"
fi 