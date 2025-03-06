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

# Initialize total size in bytes
total_bytes=0

# Count total number of directories (excluding empty lines)
total_dirs=$(grep -c '[^[:space:]]' "$1")
current_dir=0

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

# Function to convert human readable size to bytes
convert_to_bytes() {
    local size=$1
    local unit=$2
    
    case $unit in
        "B")
            echo "$size"
            ;;
        "KB")
            echo "$((size * 1024))"
            ;;
        "MB")
            echo "$((size * 1024 * 1024))"
            ;;
        "GB")
            echo "$((size * 1024 * 1024 * 1024))"
            ;;
        *)
            echo "0"
            ;;
    esac
}

# Read each line from the file
while IFS= read -r directory; do
    # Skip empty lines
    [ -z "$directory" ] && continue
    
    # Remove any trailing whitespace
    directory=$(echo "$directory" | tr -d '[:space:]')
    
    # Add ../repos prefix
    full_path="../repos/$directory"
    
    # Skip if directory doesn't exist
    if [ ! -d "$full_path" ]; then
        echo -e "\nWarning: Directory '$full_path' does not exist, skipping..."
        ((current_dir++))
        progress_bar $current_dir $total_dirs
        continue
    fi
    
    # Get the size using count_c_files.sh
    size_output=$(./count_c_files.sh "$full_path")
    
    # Extract size and unit from the output
    if [[ $size_output =~ ([0-9.]+)\s*([KMG]?B) ]]; then
        size=${BASH_REMATCH[1]}
        unit=${BASH_REMATCH[2]}
        
        # Convert to bytes
        size_bytes=$(convert_to_bytes "$size" "$unit")
        
        # Add to total
        if [ $size_bytes -gt 0 ]; then
            total_bytes=$((total_bytes + size_bytes))
        fi
        
        echo -e "\nDirectory: $directory"
        echo "Size: $size $unit"
        echo "-------------------"
    else
        echo -e "\nDirectory: $directory"
        echo "Size: No .c files found"
        echo "-------------------"
    fi
    
    ((current_dir++))
    progress_bar $current_dir $total_dirs
done < "$1"

echo -e "\n\nTotal size across all directories:"
if [ $total_bytes -gt 0 ]; then
    if [ $total_bytes -lt 1024 ]; then
        echo "$total_bytes B"
    elif [ $total_bytes -lt $((1024 * 1024)) ]; then
        echo "$((total_bytes / 1024)) KB"
    elif [ $total_bytes -lt $((1024 * 1024 * 1024)) ]; then
        echo "$((total_bytes / (1024 * 1024))) MB"
    else
        echo "$((total_bytes / (1024 * 1024 * 1024))) GB"
    fi
else
    echo "0 B"
fi 