#!/bin/bash
# Initialize environment for EAS Station
# Run this script before starting docker-compose for the first time

set -e

echo "Initializing EAS Station environment..."

# Create .env file if it doesn't exist
if [ ! -f ".env" ]; then
    echo "Creating empty .env file..."
    touch .env
    echo "✓ Created .env file"
else
    echo "✓ .env file already exists"
fi

# Check if .env.example exists
if [ ! -f ".env.example" ]; then
    echo "⚠ Warning: .env.example not found"
    echo "  Make sure you're running this script from the eas-station directory"
    exit 1
fi

echo ""
echo "Environment initialization complete!"
echo ""
echo "Next steps:"
echo "  1. Start the stack: docker-compose up -d"
echo "  2. Access the setup wizard: http://localhost/setup"
echo "  3. Complete the configuration in your browser"
echo "  4. Restart the stack: docker-compose restart"
echo ""
