#!/bin/sh

# Enable verbose logging
set -x

# Check if directory parameter is provided
if [ $# -ne 1 ]; then
    echo "Usage: $0 <output_directory>"
    exit 1
fi

# Store the output directory
OUTPUT_DIR="$1"
echo "Setting output directory to: $OUTPUT_DIR"

# Create the output directory if it doesn't exist
mkdir -p "$OUTPUT_DIR"
cd "$OUTPUT_DIR"
echo "Working in directory: $(pwd)"

# Function to download a kernel version
download_kernel() {
    local version=$1
    local temp_dir="temp-download-${version}"
    
    echo "== DOWNLOADING KERNEL VERSION $version =="
    
    # Create temporary download directory
    mkdir -p "$temp_dir"
    cd "$temp_dir"
    echo "Created and entered directory: $(pwd)"
    
    # Download the kernel source
    echo "Downloading kernel source for version $version"
    if ! wget -v "https://www.kernel.org/pub/linux/kernel/v${version%%.*}.x/linux-${version}.tar.xz"; then
        echo "ERROR: Failed to download kernel version ${version}"
        cd ..
        rm -rf "$temp_dir"
        return 1
    fi
    
    # Extract the source in the same directory
    echo "Extracting kernel source archive"
    if ! tar -xvf "linux-${version}.tar.xz"; then
        echo "ERROR: Failed to extract kernel version ${version}"
        cd ..
        rm -rf "$temp_dir"
        return 1
    fi
    echo "Successfully extracted kernel source"
    
    # Return to parent directory
    cd ..
    echo "Returned to directory: $(pwd)"
    return 0
}

# Function to prepare a kernel for a specific architecture
prepare_for_arch() {
    local major_version=$1
    local full_version=$2
    local arch=$3
    local source_dir="temp-download-${full_version}/linux-${full_version}"
    local target_dir="kernel-${major_version}-${arch}"
    
    echo "== PREPARING KERNEL ${full_version} FOR ${arch} ARCHITECTURE =="
    
    # Create target directory
    echo "Creating directory $target_dir"
    mkdir -p "$target_dir"
    
    # Copy kernel source from temp directory to target directory
    echo "Copying kernel source from $source_dir to $target_dir"
    cp -rv "$source_dir"/* "$target_dir/"
    
    # Run kernel preparation scripts for this architecture
    cd "$target_dir"
    echo "Entered directory: $(pwd)"
    
    if [ -f "Makefile" ]; then
        echo "Running make mrproper"
        make mrproper
        echo "Running make clean"
        make clean
        
        # Set appropriate architecture config
        case "$arch" in
            "arm")
                echo "Configuring for ARM architecture"
                make ARCH=arm defconfig
                ;;
            "arm64")
                echo "Configuring for ARM64 architecture"
                make ARCH=arm64 defconfig
                ;;
            "x86_64")
                echo "Configuring for x86_64 architecture"
                make ARCH=x86_64 defconfig
                ;;
        esac
        echo "Configuration completed"
    else
        echo "ERROR: Makefile not found in $target_dir"
    fi
    
    # Return to parent directory
    cd ..
    echo "Returned to directory: $(pwd)"
}

# Use specific known versions
echo "Using specific kernel versions"

# Process kernel version 4
major_version="4"
full_version="4.19.282"
echo "v${major_version}.x: $full_version"

# Download and extract kernel
if download_kernel "$full_version"; then
    echo "Successfully downloaded and extracted kernel version $full_version"
    
    # Create copies for each architecture
    for arch in "x86_64" "arm" "arm64"; do
        prepare_for_arch "$major_version" "$full_version" "$arch"
    done
    
    # Clean up temporary download directory
    echo "Cleaning up temporary download directory"
    rm -rf "temp-download-${full_version}"
else
    echo "Failed to download and extract kernel version $full_version"
fi

# Process kernel version 5
major_version="5"
full_version="5.15.139"
echo "v${major_version}.x: $full_version"

# Download and extract kernel
if download_kernel "$full_version"; then
    echo "Successfully downloaded and extracted kernel version $full_version"
    
    # Create copies for each architecture
    for arch in "x86_64" "arm" "arm64"; do
        prepare_for_arch "$major_version" "$full_version" "$arch"
    done
    
    # Clean up temporary download directory
    echo "Cleaning up temporary download directory"
    rm -rf "temp-download-${full_version}"
else
    echo "Failed to download and extract kernel version $full_version"
fi

# Process kernel version 6
major_version="6"
full_version="6.5.9"
echo "v${major_version}.x: $full_version"

# Download and extract kernel
if download_kernel "$full_version"; then
    echo "Successfully downloaded and extracted kernel version $full_version"
    
    # Create copies for each architecture
    for arch in "x86_64" "arm" "arm64"; do
        prepare_for_arch "$major_version" "$full_version" "$arch"
    done
    
    # Clean up temporary download directory
    echo "Cleaning up temporary download directory"
    rm -rf "temp-download-${full_version}"
else
    echo "Failed to download and extract kernel version $full_version"
fi

echo "== KERNEL PREPARATION COMPLETED! =="
echo "Directory structure created:"
ls -la "$OUTPUT_DIR" 