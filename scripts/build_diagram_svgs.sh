#!/bin/bash
# Script to generate SVG versions of Mermaid diagrams for standalone use
# Note: Diagrams render automatically on GitHub and MkDocs site without SVG generation
# This script is only needed for generating standalone SVG files for presentations, etc.

set -e

echo "Building SVG diagrams from Mermaid sources..."

# Check if mermaid-cli is available
if ! command -v npx &> /dev/null; then
    echo "Error: npx not found. Please install Node.js and npm."
    exit 1
fi

# Create temporary directory for mermaid files
TEMP_DIR=$(mktemp -d)
trap "rm -rf $TEMP_DIR" EXIT

# Output directory
OUTPUT_DIR="static/docs"
mkdir -p "$OUTPUT_DIR"

# Extract Mermaid diagrams from DATA_FLOW_SEQUENCES.md
echo "Extracting Mermaid diagrams from documentation..."

# This is a placeholder - would need a proper parser to extract diagrams
# For now, users can manually create .mmd files and run conversions

echo ""
echo "=========================================="
echo "Mermaid Diagram SVG Generation"
echo "=========================================="
echo ""
echo "The DATA_FLOW_SEQUENCES.md file contains 6 Mermaid sequence diagrams."
echo "These diagrams render automatically on:"
echo "  - GitHub (native Mermaid support)"
echo "  - MkDocs documentation site (via pymdownx.superfences)"
echo ""
echo "To generate standalone SVG files:"
echo ""
echo "1. Install mermaid-cli:"
echo "   npm install -g @mermaid-js/mermaid-cli"
echo ""
echo "2. Extract individual diagrams to .mmd files"
echo ""
echo "3. Convert to SVG:"
echo "   mmdc -i diagram.mmd -o static/docs/diagram.svg -t neutral -b transparent"
echo ""
echo "For bulk conversion, see:"
echo "   https://mermaid.js.org/ecosystem/integrations-community.html"
echo ""
echo "=========================================="

# Example conversion (if .mmd files exist)
if ls *.mmd 1> /dev/null 2>&1; then
    echo ""
    echo "Found .mmd files in current directory. Converting..."
    for mmd_file in *.mmd; do
        base_name=$(basename "$mmd_file" .mmd)
        svg_file="$OUTPUT_DIR/${base_name}.svg"
        echo "Converting $mmd_file -> $svg_file"
        npx -y @mermaid-js/mermaid-cli mmdc -i "$mmd_file" -o "$svg_file" -t neutral -b transparent || true
    done
    echo ""
    echo "Conversion complete! SVG files saved to $OUTPUT_DIR/"
else
    echo ""
    echo "No .mmd files found in current directory."
    echo "Extract diagrams from docs/architecture/DATA_FLOW_SEQUENCES.md first."
fi
