#!/bin/bash
# This script deletes all files with the .Identifier extension in the current directory and its subdirectories.
find . -type f -name '*.Identifier' -delete