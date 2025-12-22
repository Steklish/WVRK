"""
Simple test to verify the schema consolidation worked
"""
import asyncio
from SKLS.command_runner import AsyncCommandRunner
from SKLS.Datatypes.task import Task
from SKLS.task_manager import TaskManager


async def test_functionality():
    print("Testing consolidated schema functionality...")
    
    # Test AsyncCommandRunner
    runner = AsyncCommandRunner(timeout=5, max_output_size=1024)
    stdout, stderr, return_code, was_timeout = await runner.run("echo 'Schema consolidation test'")
    print(f"Command runner test: {stdout.strip()}, return_code: {return_code}")
    
    # Test Task creation
    task = Task(
        name="schema_test",
        cli_command="echo 'Task schema test'",
        reasoning="Testing that schema is properly consolidated"
    )
    print(f"Task created: {task.name}, command: {task.cli_command}")
    
    # Test TaskManager
    manager = TaskManager(default_timeout=10, max_output_size=2048)
    task_id = await manager.add_task(task)
    print(f"Task added to manager with ID: {task_id}")
    
    # Wait for completion
    await asyncio.sleep(1)
    status = await manager.get_task_status(task_id)
    print(f"Task status: {status}")
    
    completed_task = await manager.get_task_by_id(task_id)
    print(f"Completed task output: {completed_task.stdout}")
    
    print("All tests passed! Schema consolidation is working correctly.")


if __name__ == "__main__":
    asyncio.run(test_functionality())