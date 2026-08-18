# tools/common.py
# Claude Code / Frontier Agent Grade Primitive Tools

import os
import sys
import re
import glob
import json
import time
import subprocess
from typing import List, Dict, Any, Optional
from langchain_core.tools import tool
from pydantic import BaseModel, Field

# =============================================================================
# Category 1: File Operations (file_read, file_writer, file_edit)
# =============================================================================

class FileReadInput(BaseModel):
    file_path: str = Field(description="Relative or absolute path of the file to read from disk.")
    offset: int = Field(default=1, description="Line number to start reading from (1-indexed). Defaults to 1.")
    limit: int = Field(default=250, description="Maximum number of lines to read in a single call. Defaults to 250.")
    show_line_numbers: bool = Field(default=True, description="Whether to prefix each line with line numbers (e.g. '     1 | ...'). Defaults to True.")

@tool(args_schema=FileReadInput)
def file_read(file_path: str, offset: int = 1, limit: int = 250, show_line_numbers: bool = True) -> str:
    """Reads lines from a file on the local filesystem with optional line numbers and pagination."""
    abs_path = os.path.abspath(os.path.expanduser(file_path))
    if not os.path.exists(abs_path):
        return f"FileRead Error: File '{file_path}' (resolved to '{abs_path}') does not exist."
    if os.path.isdir(abs_path):
        return f"FileRead Error: Path '{file_path}' is a directory, not a file."

    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            
        total_lines = len(lines)
        start_idx = max(0, offset - 1)
        end_idx = min(total_lines, start_idx + limit)
        
        sliced_lines = lines[start_idx:end_idx]
        output_lines = []
        
        for idx, line in enumerate(sliced_lines, start=start_idx + 1):
            if show_line_numbers:
                output_lines.append(f"{idx:6d} | {line}")
            else:
                output_lines.append(line)
                
        content = "".join(output_lines)
        header = f"[File: {abs_path} (Lines {start_idx+1}-{end_idx} of {total_lines})]\n"
        return header + content
        
    except Exception as e:
        return f"FileRead Error: Failed to read file '{file_path}': {str(e)}"


class FileWriterInput(BaseModel):
    file_path: str = Field(description="Relative or absolute destination file path. Parent directories created automatically.")
    content: str = Field(description="Complete text string content to write into the file.")
    overwrite: bool = Field(default=True, description="If True, overwrites existing file. If False, fails if target file exists. Defaults to True.")

@tool(args_schema=FileWriterInput)
def file_writer(file_path: str, content: str, overwrite: bool = True) -> str:
    """Creates a new file or overwrites an existing file with the provided text content."""
    abs_path = os.path.abspath(os.path.expanduser(file_path))
    if os.path.exists(abs_path) and not overwrite:
        return f"FileWrite Error: File '{file_path}' already exists and overwrite=False."

    try:
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"SUCCESS: Written {len(content)} characters to '{abs_path}'."
    except Exception as e:
        return f"FileWrite Error: Failed to write to '{file_path}': {str(e)}"


class FileEditInput(BaseModel):
    file_path: str = Field(description="Relative or absolute path to the target file to edit.")
    target_content: str = Field(description="The exact multi-line string block to find and replace. Must match uniquely in the file.")
    replacement_content: str = Field(description="The exact string block to substitute in place of target_content.")

@tool(args_schema=FileEditInput)
def file_edit(file_path: str, target_content: str, replacement_content: str) -> str:
    """Replaces an exact matching block of text in a file with replacement_content."""
    abs_path = os.path.abspath(os.path.expanduser(file_path))
    if not os.path.exists(abs_path):
        return f"FileEdit Error: Target file '{file_path}' does not exist."

    try:
        with open(abs_path, "r", encoding="utf-8") as f:
            content = f.read()

        if target_content not in content:
            preview = content[:200] + "..." if len(content) > 200 else content
            return (
                f"FileEdit Error: Exact target_content match not found in '{file_path}'.\n"
                f"File preview:\n{preview}"
            )

        match_count = content.count(target_content)
        if match_count > 1:
            return f"FileEdit Error: target_content matches {match_count} locations in '{file_path}'. Provide a unique block."

        new_content = content.replace(target_content, replacement_content, 1)

        temp_path = abs_path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        os.replace(temp_path, abs_path)

        return f"SUCCESS: File '{abs_path}' edited successfully (replaced {len(target_content)} bytes with {len(replacement_content)} bytes)."

    except Exception as e:
        return f"FileEdit Error: Failed to edit '{file_path}': {str(e)}"


# =============================================================================
# Category 2: Shell Execution (bash_command)
# =============================================================================

class BashCommandInput(BaseModel):
    command: str = Field(description="The shell command line string to execute in bash/sh.")
    timeout_seconds: int = Field(default=30, description="Maximum execution time in seconds before process is terminated. Defaults to 30.")
    max_stdout_length: int = Field(default=4000, description="Maximum character length of stdout to return to prevent prompt bloat. Defaults to 4000.")

@tool(args_schema=BashCommandInput)
def bash_command(command: str, timeout_seconds: int = 30, max_stdout_length: int = 4000) -> str:
    """Executes a real shell command on local system, capturing stdout, stderr, and exit code."""
    stdout_limit = min(50000, max(100, max_stdout_length))
    
    try:
        start_time = time.time()
        process = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=os.getcwd()
        )
        duration = round(time.time() - start_time, 2)
        
        stdout_clean = process.stdout.strip()
        stderr_clean = process.stderr.strip()
        
        result_parts = [
            f"[Command: '{command}']",
            f"[Exit Code: {process.returncode} | Execution Time: {duration}s]"
        ]
        
        if stdout_clean:
            if len(stdout_clean) > stdout_limit:
                stdout_clean = stdout_clean[:stdout_limit] + f"\n... [STDOUT TRUNCATED {len(stdout_clean)-stdout_limit} bytes]"
            result_parts.append(f"--- STDOUT ---\n{stdout_clean}")
            
        if stderr_clean:
            if len(stderr_clean) > 2000:
                stderr_clean = stderr_clean[:2000] + f"\n... [STDERR TRUNCATED {len(stderr_clean)-2000} bytes]"
            result_parts.append(f"--- STDERR ---\n{stderr_clean}")
            
        if not stdout_clean and not stderr_clean:
            result_parts.append("(Command executed silently with no output)")

        return "\n".join(result_parts)

    except subprocess.TimeoutExpired:
        return f"Bash Error: Command '{command}' timed out after {timeout_seconds} seconds."
    except Exception as e:
        return f"Bash Error: Failed to execute command '{command}': {str(e)}"


# =============================================================================
# Category 3: Search (glob_search, grep_search)
# =============================================================================

VCS_EXCLUDE_DIRS = {".git", ".svn", ".hg", "node_modules", "__pycache__", ".venv", "env_langchain_123", ".ipynb_checkpoints"}

class GlobSearchInput(BaseModel):
    pattern: str = Field(description="Glob wildcard pattern string to match file names and paths (e.g. '**/*.py' or 'skills/**/SKILL.md').")
    search_path: str = Field(default=".", description="Base directory path to execute search from. Defaults to current directory ('.').")

@tool(args_schema=GlobSearchInput)
def glob_search(pattern: str, search_path: str = ".") -> str:
    """Finds file paths matching a glob wildcard pattern (e.g. '**/*.py' or 'skills/**/SKILL.md')."""
    abs_root = os.path.abspath(os.path.expanduser(search_path))
    full_pattern = os.path.join(abs_root, pattern)
    
    matches = glob.glob(full_pattern, recursive=True)
    clean_matches = [
        os.path.relpath(m, os.getcwd()) for m in matches 
        if not any(ex in m for ex in VCS_EXCLUDE_DIRS)
    ]
    
    if not clean_matches:
        return f"No files matched glob pattern '{pattern}' in '{search_path}'."
        
    return f"Found {len(clean_matches)} files matching '{pattern}':\n" + "\n".join(clean_matches[:100])


class GrepSearchInput(BaseModel):
    pattern: str = Field(description="Regular expression pattern string to match within file contents.")
    search_path: str = Field(default=".", description="Directory or file path to search within. Defaults to current directory ('.').")
    output_mode: str = Field(default="files_with_matches", description="Output format mode - 'files_with_matches' (paths only), 'content' (lines with match), or 'count'. Defaults to 'files_with_matches'.")
    head_limit: int = Field(default=50, description="Maximum number of matching files or lines to return. Defaults to 50.")

@tool(args_schema=GrepSearchInput)
def grep_search(pattern: str, search_path: str = ".", output_mode: str = "files_with_matches", head_limit: int = 50) -> str:
    """Searches file contents using regex matching while excluding VCS and environment directories."""
    abs_root = os.path.abspath(os.path.expanduser(search_path))
    if not os.path.exists(abs_root):
        return f"Grep Error: Search path '{search_path}' does not exist."

    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except Exception as err:
        return f"Grep Error: Invalid regex pattern '{pattern}': {err}"

    matching_files = []
    content_matches = []
    total_match_count = 0

    if os.path.isfile(abs_root):
        target_files = [abs_root]
    else:
        target_files = []
        for root, dirs, files in os.walk(abs_root):
            dirs[:] = [d for d in dirs if d not in VCS_EXCLUDE_DIRS]
            for f in files:
                target_files.append(os.path.join(root, f))

    for fpath in target_files:
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()

            rel_path = os.path.relpath(fpath, os.getcwd())
            file_had_match = False
            
            for line_no, line in enumerate(lines, start=1):
                if regex.search(line):
                    file_had_match = True
                    total_match_count += 1
                    if output_mode == "content" and len(content_matches) < head_limit:
                        content_matches.append(f"{rel_path}:{line_no}:{line.strip()}")

            if file_had_match:
                matching_files.append(rel_path)
                if output_mode == "files_with_matches" and len(matching_files) >= head_limit:
                    break
        except Exception:
            continue

    if output_mode == "content":
        if not content_matches:
            return f"No matches found for pattern '{pattern}'."
        return f"Found {total_match_count} matches for '{pattern}':\n" + "\n".join(content_matches)

    elif output_mode == "count":
        return f"Found {total_match_count} total occurrences across {len(matching_files)} files."

    else:
        if not matching_files:
            return f"No files matching pattern '{pattern}'."
        return f"Found {len(matching_files)} matching files:\n" + "\n".join(matching_files[:head_limit])
