"""
Test file for the async command runner and task storage functionality
"""

import asyncio
from .task_manager import TaskManager
from .Datatypes.task import Task


async def test_async_command_runner():
    """Test the AsyncCommandRunner functionality"""
    print("=== Testing AsyncCommandRunner ===")
    
    from .command_runner import AsyncCommandRunner
    
    runner = AsyncCommandRunner(timeout=10, max_output_size=1024)
    
    # Test basic command
    stdout, stderr, return_code, was_timeout = await runner.run("echo 'Hello from async!'")
    print(f"Basic command - stdout: {stdout.strip()}, return_code: {return_code}, timeout: {was_timeout}")
    
    # Test timeout with a separate runner instance
    timeout_runner = AsyncCommandRunner(timeout=1, max_output_size=1024)
    stdout, stderr, return_code, was_timeout = await timeout_runner.run("sleep 3")
    print(f"Timeout test - stdout: '{stdout}', return_code: {return_code}, timeout: {was_timeout}")
    
    # Test with process reference
    process, stdout, stderr, return_code, was_timeout = await runner.run_with_process_reference("echo 'Process test'")
    print(f"Process reference test - stdout: {stdout.strip()}, return_code: {return_code}, timeout: {was_timeout}")
    
    print("AsyncCommandRunner tests completed.\n")


async def test_task_manager():
    """Test the TaskManager functionality"""
    print("=== Testing TaskManager ===")
    
    # Create a task manager
    manager = TaskManager(default_timeout=15, max_output_size=2048)
    
    # Create some test tasks
    task1 = Task(
        name="test_task_1",
        cli_command="echo 'Task 1 executed successfully'",
        reasoning="Testing basic command execution"
    )
    
    task2 = Task(
        name="test_task_2",
        cli_command="sleep 2 && echo 'Task 2 completed after delay'",
        reasoning="Testing delayed command execution"
    )
    
    task3 = Task(
        name="test_task_3",
        cli_command="invalid_command_xyz",
        reasoning="Testing error handling"
    )
    
    # Add tasks to the manager
    task_id_1 = await manager.add_task(task1)
    task_id_2 = await manager.add_task(task2)
    task_id_3 = await manager.add_task(task3)
    
    print(f"Added tasks with IDs: {task_id_1}, {task_id_2}, {task_id_3}")
    
    # Wait for tasks to complete
    print("Waiting for tasks to complete...")
    await asyncio.sleep(4)  # Wait for all tasks to potentially complete
    
    # Check running tasks
    running_tasks = await manager.get_running_tasks()
    print(f"Running tasks count: {len(running_tasks)}")
    
    # Check completed tasks
    completed_tasks = await manager.get_completed_tasks()
    print(f"Completed tasks count: {len(completed_tasks)}")
    
    # Get individual task status
    for task_id in [task_id_1, task_id_2, task_id_3]:
        status = await manager.get_task_status(task_id)
        task = await manager.get_task_by_id(task_id)
        print(f"Task {task.name} (ID: {task_id}) - Status: {status}")
        if task and hasattr(task, 'stdout'):
            print(f"  Output: {task.stdout}")
        if task and hasattr(task, 'return_code'):
            print(f"  Return code: {task.return_code}")
        if task and hasattr(task, 'was_timeout'):
            print(f"  Was timeout: {task.was_timeout}")
    
    print("TaskManager tests completed.\n")


async def test_task_cancellation():
    """Test task cancellation functionality"""
    print("=== Testing Task Cancellation ===")
    
    manager = TaskManager(default_timeout=10, max_output_size=2048)
    
    # Create a long-running task
    long_task = Task(
        name="long_running_task",
        cli_command="sleep 10 && echo 'This should not appear'",
        reasoning="Testing cancellation of long-running task"
    )
    
    task_id = await manager.add_task(long_task)
    print(f"Added long-running task with ID: {task_id}")
    
    # Wait a moment for the task to start
    await asyncio.sleep(1)
    
    # Check that the task is running
    status = await manager.get_task_status(task_id)
    print(f"Task status before cancellation: {status}")
    
    # Cancel the task
    cancelled = await manager.cancel_task(task_id)
    print(f"Task cancelled: {cancelled}")
    
    # Wait a moment for cancellation to process
    await asyncio.sleep(0.5)
    
    # Check that the task is now completed (as cancelled)
    status = await manager.get_task_status(task_id)
    task = await manager.get_task_by_id(task_id)
    print(f"Task status after cancellation: {status}")
    print(f"Task was cancelled: {getattr(task, 'was_cancelled', 'N/A')}")
    
    print("Task cancellation test completed.\n")


async def main():
    """Main test function"""
    print("Starting tests for async command runner and task storage...\n")
    
    await test_async_command_runner()
    await test_task_manager()
    await test_task_cancellation()
    
    print("All tests completed!")


if __name__ == "__main__":
    asyncio.run(main())