"""
Example usage of the CommandRunner module for ad-hoc command execution
"""

from command_runner import CommandRunner


def example_usage():
    print("CommandRunner Example Usage")
    print("="*40)
    
    # Create a command runner with 10 second timeout and 2KB output limit
    runner = CommandRunner(timeout=10, max_output_size=2048)
    
    # Example 1: Simple command
    print("\n1. Running a simple command:")
    stdout, stderr, return_code, was_timeout = runner.run("echo 'Hello from CommandRunner!'")
    print(f"   Output: {stdout.strip()}")
    print(f"   Return Code: {return_code}")
    print(f"   Timed Out: {was_timeout}")
    
    # Example 2: Command with error
    print("\n2. Running a command that produces an error:")
    stdout, stderr, return_code, was_timeout = runner.run("ls /nonexistent_path")
    print(f"   Stdout: {stdout.strip()}")
    print(f"   Stderr: {stderr.strip()}")
    print(f"   Return Code: {return_code}")
    print(f"   Timed Out: {was_timeout}")
    
    # Example 3: Time-limited command
    print("\n3. Running a command with timeout:")
    timeout_runner = CommandRunner(timeout=2, max_output_size=2048)
    stdout, stderr, return_code, was_timeout = timeout_runner.run("sleep 5 && echo 'This should not appear'")
    print(f"   Stdout: '{stdout}'")
    print(f"   Stderr: '{stderr}'")
    print(f"   Return Code: {return_code}")
    print(f"   Timed Out: {was_timeout}")
    
    # Example 4: Output-limited command
    print("\n4. Running a command with output size limit:")
    runner_limited = CommandRunner(timeout=10, max_output_size=50)
    stdout, stderr, return_code, was_timeout = runner_limited.run("printf 'A%.0s' {1..100}; echo")
    print(f"   Stdout Length: {len(stdout)}")
    print(f"   Stdout Preview: {repr(stdout[:60])}")
    print(f"   Return Code: {return_code}")
    print(f"   Timed Out: {was_timeout}")


if __name__ == "__main__":
    example_usage()