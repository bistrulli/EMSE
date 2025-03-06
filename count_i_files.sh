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

# Find all .i files recursively and calculate total size
total_size=$(find "$1" -type f -name "*.i" -exec du -b {} + | awk '{sum += $1} END {print sum}')

# Convert bytes to human readable format
if [ -n "$total_size" ]; then
    echo "Total size of .i files in $1 and subdirectories:"
    echo "$total_size" | awk '{ 
        if ($1 < 1024) print $1 " B"
        else if ($1 < 1024*1024) print $1/1024 " KB"
        else if ($1 < 1024*1024*1024) print $1/(1024*1024) " MB"
        else print $1/(1024*1024*1024) " GB"
    }'
else
    echo "No .i files found in $1 and subdirectories"
fi 