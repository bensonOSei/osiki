#!/usr/bin/env bash

# Osiki Development Setup Script
# This script helps contributors get started quickly with the project

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Print functions
print_header() {
    echo -e "\n${BLUE}==>${NC} ${1}"
}

print_success() {
    echo -e "${GREEN}✓${NC} ${1}"
}

print_warning() {
    echo -e "${YELLOW}!${NC} ${1}"
}

print_error() {
    echo -e "${RED}✗${NC} ${1}"
}

# Check if a command exists
command_exists() {
    command -v "$1" &> /dev/null
}

# Get the script's directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

echo -e "${BLUE}"
echo "  ___  ____  _  _  _ "
echo " / _ \/ ___|| || |/ |"
echo "| | | \___ \| || | | |"
echo "| |_| |___) | || | | |"
echo " \___/|____/|_||_|_|_|"
echo -e "${NC}"
echo "Development Environment Setup"
echo "=============================="

# Track what needs to be done
MISSING_DEPS=()

# Check Python version
print_header "Checking prerequisites..."

if command_exists python3; then
    PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    if [[ "$PYTHON_VERSION" == "3.13" ]]; then
        print_success "Python 3.13 found"
    else
        print_warning "Python $PYTHON_VERSION found, but 3.13 is required"
        MISSING_DEPS+=("python3.13")
    fi
else
    print_error "Python 3 not found"
    MISSING_DEPS+=("python3.13")
fi

# Check Poetry
if command_exists poetry; then
    POETRY_VERSION=$(poetry --version | cut -d' ' -f3)
    print_success "Poetry $POETRY_VERSION found"
else
    print_error "Poetry not found"
    MISSING_DEPS+=("poetry")
fi

# Check Docker
if command_exists docker; then
    if docker info &> /dev/null; then
        print_success "Docker found and running"
    else
        print_warning "Docker found but not running"
        MISSING_DEPS+=("docker (start the daemon)")
    fi
else
    print_error "Docker not found"
    MISSING_DEPS+=("docker")
fi

# Check Docker Compose
if command_exists docker-compose || docker compose version &> /dev/null; then
    print_success "Docker Compose found"
else
    print_error "Docker Compose not found"
    MISSING_DEPS+=("docker-compose")
fi

# Check Make
if command_exists make; then
    print_success "Make found"
else
    print_warning "Make not found (optional but recommended)"
fi

# Exit if missing required dependencies
if [ ${#MISSING_DEPS[@]} -gt 0 ]; then
    echo ""
    print_error "Missing required dependencies:"
    for dep in "${MISSING_DEPS[@]}"; do
        echo "  - $dep"
    done
    echo ""
    echo "Please install the missing dependencies and run this script again."
    echo ""
    echo "Installation hints:"
    echo "  Python 3.13: https://www.python.org/downloads/ or use pyenv"
    echo "  Poetry:      curl -sSL https://install.python-poetry.org | python3 -"
    echo "  Docker:      https://docs.docker.com/get-docker/"
    exit 1
fi

# Setup environment file
print_header "Setting up environment..."

if [ ! -f .env ]; then
    cp .env.example .env
    print_success "Created .env from .env.example"
else
    print_success ".env file already exists"
fi

# Install Python dependencies
print_header "Installing Python dependencies..."

poetry install
print_success "Dependencies installed"

# Install pre-commit hooks
print_header "Setting up pre-commit hooks..."

poetry run pre-commit install
print_success "Pre-commit hooks installed"

# Setup CLI alias
print_header "Setting up Osiki CLI..."

SHELL_RC=""
if [ -n "$ZSH_VERSION" ] || [ "$SHELL" = "/bin/zsh" ]; then
    SHELL_RC="$HOME/.zshrc"
elif [ -n "$BASH_VERSION" ] || [ "$SHELL" = "/bin/bash" ]; then
    SHELL_RC="$HOME/.bashrc"
fi

ALIAS_LINE="alias osiki='$PROJECT_ROOT/run'"

if [ -n "$SHELL_RC" ]; then
    if grep -q "alias osiki=" "$SHELL_RC" 2>/dev/null; then
        print_success "Osiki CLI alias already configured"
    else
        echo ""
        read -p "Add 'osiki' command to your shell? [Y/n] " -n 1 -r
        echo ""
        if [[ ! $REPLY =~ ^[Nn]$ ]]; then
            echo "" >> "$SHELL_RC"
            echo "# Osiki CLI" >> "$SHELL_RC"
            echo "$ALIAS_LINE" >> "$SHELL_RC"
            print_success "Added osiki alias to $SHELL_RC"
            echo "  Run 'source $SHELL_RC' or start a new terminal to use 'osiki' command"
        else
            print_warning "Skipped CLI alias setup"
            echo "  You can still use: ./run generate <command>"
        fi
    fi
else
    print_warning "Could not detect shell config file"
    echo "  Add this to your shell config: $ALIAS_LINE"
fi

# Ask about starting services
print_header "Docker services"

echo ""
read -p "Would you like to start Docker services (MongoDB, Redis)? [y/N] " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Starting services..."
    docker compose up -d
    print_success "Services started"

    echo ""
    echo "Waiting for services to be healthy..."
    sleep 5

    # Check service health
    if docker compose ps | grep -q "healthy"; then
        print_success "Services are healthy"
    else
        print_warning "Services may still be starting. Check with: docker compose ps"
    fi
else
    print_warning "Skipped starting Docker services"
    echo "  You can start them later with: make up"
fi

# Final summary
echo ""
echo -e "${GREEN}=============================${NC}"
echo -e "${GREEN}Setup complete!${NC}"
echo -e "${GREEN}=============================${NC}"
echo ""
echo "Osiki CLI commands:"
echo "  osiki generate model <Name>       - Generate a Beanie model"
echo "  osiki generate repository <Name>  - Generate repository files"
echo "  osiki generate service <Name>     - Generate service files"
echo "  osiki generate route <Name>       - Generate API route"
echo "  osiki generate all <Name>         - Generate all of the above"
echo ""
echo "Development commands:"
echo "  make dev        - Run the development server locally"
echo "  make up         - Start Docker services"
echo "  make down       - Stop Docker services"
echo "  make lint       - Run linter"
echo "  make format     - Format code"
echo "  make typecheck  - Run type checker"
echo "  make help       - Show all available commands"
echo ""
echo "The API will be available at: http://localhost:8000"
echo "Health check endpoint:        http://localhost:8000/health"
echo ""
echo "Happy coding!"
