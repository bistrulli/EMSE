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

# Initialize total size in bytes
total_bytes=0

# Read each line from the file
while IFS= read -r directory; do
    # Skip empty lines
    [ -z "$directory" ] && continue
    
    # Remove any trailing whitespace
    directory=$(echo "$directory" | tr -d '[:space:]')
    
    # Skip if directory doesn't exist
    if [ ! -d "$directory" ]; then
        echo "Warning: Directory '$directory' does not exist, skipping..."
        continue
    fi
    
    # Get the size using count_c_files.sh and convert to bytes
    size=$(./count_c_files.sh "$directory" | grep -oP '\d+\.?\d*' | head -n1)
    unit=$(./count_c_files.sh "$directory" | grep -oP '[KMG]B' | head -n1)
    
    # Convert to bytes based on unit
    case $unit in
        "KB")
            size_bytes=$(echo "$size * 1024" | bc)
            ;;
        "MB")
            size_bytes=$(echo "$size * 1024 * 1024" | bc)
            ;;
        "GB")
            size_bytes=$(echo "$size * 1024 * 1024 * 1024" | bc)
            ;;
        *)
            size_bytes=$size
            ;;
    esac
    
    # Add to total
    total_bytes=$(echo "$total_bytes + $size_bytes" | bc)
    
    echo "Directory: $directory"
    echo "Size: $size $unit"
    echo "-------------------"
done < "$1"

# Convert total bytes to human readable format
echo "Total size across all directories:"
echo "$total_bytes" | awk '{ 
    if ($1 < 1024) print $1 " B"
    else if ($1 < 1024*1024) print $1/1024 " KB"
    else if ($1 < 1024*1024*1024) print $1/(1024*1024) " MB"
    else print $1/(1024*1024*1024) " GB"
}' 