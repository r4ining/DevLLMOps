# Makefile for Vibe Coding Guide

.PHONY: help lint

help:
	@echo "Makefile for Vibe Coding Guide"
	@echo ""
	@echo "Usage:"
	@echo "    make lint    - Lint all markdown files"
	@echo ""

lint:
	@echo "Linting markdown files..."
	@npm install -g markdownlint-cli
	@markdownlint **/*.md
