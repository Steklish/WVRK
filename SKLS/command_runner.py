"""
Module for launching CLI commands with limits on output size and execution time.
"""

import asyncio
import subprocess
import time
from typing import Optional, Tuple


class AsyncCommandRunner:
    """
    An async class to run CLI commands with configurable limits on output size and execution time.
    """

    def __init__(self, timeout: int = 30, max_output_size: int = 10240):
        """
        Initialize the AsyncCommandRunner with default limits.

        Args:
            timeout (int): Maximum execution time in seconds (default: 30)
            max_output_size (int): Maximum size of stdout/stderr in bytes (default: 10240 = 10KB)
        """
        self.timeout = timeout
        self.max_output_size = max_output_size

    async def run(self, command: str, cwd: Optional[str] = None) -> Tuple[str, str, int, bool]:
        """
        Run a command asynchronously and return stdout, stderr, return code, and timeout status.

        Args:
            command (str): The command to execute
            cwd (Optional[str]): Working directory for the command

        Returns:
            Tuple[str, str, int, bool]: (stdout, stderr, return_code, was_timeout)
        """
        # Start the subprocess using asyncio
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd
        )

        # Track execution time
        start_time = time.time()
        was_timeout = False

        try:
            # Wait for the process to complete with timeout
            stdout_data, stderr_data = await asyncio.wait_for(
                process.communicate(),
                timeout=self.timeout
            )

            # Decode the output
            stdout = stdout_data.decode() if stdout_data else ""
            stderr = stderr_data.decode() if stderr_data else ""

        except asyncio.TimeoutError:
            # Process exceeded timeout, terminate it
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=1)  # Give it a moment to terminate gracefully
            except asyncio.TimeoutError:
                process.kill()  # Force kill if not terminated
            was_timeout = True

            # Return empty strings for timed-out processes
            stdout = ""
            stderr = ""

        # Truncate output if needed
        if len(stdout) > self.max_output_size:
            stdout = stdout[:self.max_output_size] + "\n... [OUTPUT TRUNCATED]"
        if len(stderr) > self.max_output_size:
            stderr = stderr[:self.max_output_size] + "\n... [OUTPUT TRUNCATED]"

        return_code = process.returncode if not was_timeout else -1

        return stdout, stderr, return_code, was_timeout

    async def run_with_process_reference(self, command: str, cwd: Optional[str] = None) -> Tuple[subprocess.Popen, str, str, int, bool]:
        """
        Run a command and return the process reference along with results.

        Args:
            command (str): The command to execute
            cwd (Optional[str]): Working directory for the command

        Returns:
            Tuple[subprocess.Popen, str, str, int, bool]: (process, stdout, stderr, return_code, was_timeout)
        """
        # Start the subprocess using asyncio
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd
        )

        # Track execution time
        start_time = time.time()
        was_timeout = False

        try:
            # Wait for the process to complete with timeout
            stdout_data, stderr_data = await asyncio.wait_for(
                process.communicate(),
                timeout=self.timeout
            )

            # Decode the output
            stdout = stdout_data.decode() if stdout_data else ""
            stderr = stderr_data.decode() if stderr_data else ""

        except asyncio.TimeoutError:
            # Process exceeded timeout, terminate it
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=1)  # Give it a moment to terminate gracefully
            except asyncio.TimeoutError:
                process.kill()  # Force kill if not terminated
            was_timeout = True

            # Return empty strings for timed-out processes
            stdout = ""
            stderr = ""

        # Truncate output if needed
        if len(stdout) > self.max_output_size:
            stdout = stdout[:self.max_output_size] + "\n... [OUTPUT TRUNCATED]"
        if len(stderr) > self.max_output_size:
            stderr = stderr[:self.max_output_size] + "\n... [OUTPUT TRUNCATED]"

        return_code = process.returncode if not was_timeout else -1

        return process, stdout, stderr, return_code, was_timeout