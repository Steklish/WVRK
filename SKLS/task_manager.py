"""
Task storage and management system for running tasks asynchronously.
"""

import asyncio
from typing import Dict, Optional
from . import command_runner
from .command_runner import AsyncCommandRunner
import uuid
from datetime import datetime
from .Datatypes.task import Task


class TaskManager:
    """
    A class to manage running tasks, store them, and process them as they finish.
    """
    
    def __init__(self, default_timeout: int = 30, max_output_size: int = 10240):
        """
        Initialize the TaskManager.
        
        Args:
            default_timeout (int): Default timeout for commands in seconds
            max_output_size (int): Maximum size of command output in bytes
        """
        self.default_timeout = default_timeout
        self.max_output_size = max_output_size
        self.running_tasks: Dict[str, Task] = {}  # Maps task_id to Task object
        self.completed_tasks: Dict[str, Task] = {}  # Maps task_id to completed Task object
        self.command_runner = AsyncCommandRunner(timeout=default_timeout, max_output_size=max_output_size)
        self._lock = asyncio.Lock()  # For thread-safe operations
    
    async def add_task(self, task: Task) -> str:
        """
        Add a task to the running queue and start executing it.
        
        Args:
            task (Task): The task to add and execute
            
        Returns:
            str: The unique ID assigned to the task
        """
        task_id = str(uuid.uuid4())
        # Ensure process is initialized as None if not already set
        if task.process is None:
            task.process = None  # Will be set when the task starts running
        
        # Store the task as running
        async with self._lock:
            self.running_tasks[task_id] = task
        
        # Run the task asynchronously
        asyncio.create_task(self._execute_task(task_id, task))
        
        return task_id
    
    async def _execute_task(self, task_id: str, task: Task):
        """
        Execute a task and move it to completed when done.
        
        Args:
            task_id (str): The unique ID of the task
            task (Task): The task to execute
        """
        try:
            # Execute the command associated with the task
            process, stdout, stderr, return_code, was_timeout = await self.command_runner.run_with_process_reference(
                task.cli_command,
                cwd=None  # You can customize this based on your needs
            )
            
            # Update the task with execution results
            task.process = process
            task.stdout = stdout
            task.stderr = stderr
            task.return_code = return_code
            task.was_timeout = was_timeout
            task.completed_at = datetime.now()
            
            # Move the task from running to completed
            async with self._lock:
                if task_id in self.running_tasks:
                    del self.running_tasks[task_id]
                    self.completed_tasks[task_id] = task
        except Exception as e:
            # Handle any exceptions during task execution
            task.error = str(e)
            task.completed_at = datetime.now()
            
            async with self._lock:
                if task_id in self.running_tasks:
                    del self.running_tasks[task_id]
                    self.completed_tasks[task_id] = task
    
    async def get_running_tasks(self) -> Dict[str, Task]:
        """
        Get all currently running tasks.
        
        Returns:
            Dict[str, Task]: Dictionary mapping task IDs to Task objects
        """
        async with self._lock:
            return self.running_tasks.copy()
    
    async def get_completed_tasks(self) -> Dict[str, Task]:
        """
        Get all completed tasks.
        
        Returns:
            Dict[str, Task]: Dictionary mapping task IDs to Task objects
        """
        async with self._lock:
            return self.completed_tasks.copy()
    
    async def get_task_by_id(self, task_id: str) -> Optional[Task]:
        """
        Get a specific task by its ID.
        
        Args:
            task_id (str): The ID of the task to retrieve
            
        Returns:
            Optional[Task]: The task if found, None otherwise
        """
        async with self._lock:
            task = self.running_tasks.get(task_id)
            if task is None:
                task = self.completed_tasks.get(task_id)
            return task
    
    async def remove_completed_task(self, task_id: str) -> bool:
        """
        Remove a completed task from storage.
        
        Args:
            task_id (str): The ID of the task to remove
            
        Returns:
            bool: True if the task was removed, False if it didn't exist
        """
        async with self._lock:
            if task_id in self.completed_tasks:
                del self.completed_tasks[task_id]
                return True
            return False
    
    async def wait_for_task_completion(self, task_id: str, timeout: Optional[float] = None) -> Optional[Task]:
        """
        Wait for a specific task to complete.
        
        Args:
            task_id (str): The ID of the task to wait for
            timeout (Optional[float]): Maximum time to wait in seconds
            
        Returns:
            Optional[Task]: The completed task, or None if timeout occurs
        """
        start_time = asyncio.get_event_loop().time()
        
        while True:
            task = await self.get_task_by_id(task_id)
            if task and task_id in self.completed_tasks:
                return task
                
            if timeout is not None:
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed >= timeout:
                    return None
                    
            await asyncio.sleep(0.1)  # Small delay to prevent busy-waiting
    
    async def cancel_task(self, task_id: str) -> bool:
        """
        Cancel a running task by terminating its process.
        
        Args:
            task_id (str): The ID of the task to cancel
            
        Returns:
            bool: True if the task was cancelled, False if it didn't exist or wasn't running
        """
        async with self._lock:
            task = self.running_tasks.get(task_id)
            if task and task.process:
                try:
                    task.process.terminate()
                    # Wait a bit for graceful termination
                    try:
                        await asyncio.wait_for(task.process.wait(), timeout=1)
                    except asyncio.TimeoutError:
                        # Force kill if not terminated
                        task.process.kill()
                    
                    # Move to completed with cancellation status
                    task.was_cancelled = True
                    task.completed_at = datetime.now()
                    del self.running_tasks[task_id]
                    self.completed_tasks[task_id] = task
                    return True
                except Exception:
                    # If termination fails, still remove from running tasks
                    del self.running_tasks[task_id]
                    task.was_cancelled = True
                    task.completed_at = datetime.now()
                    self.completed_tasks[task_id] = task
                    return True
            
            return False
    
    async def get_task_status(self, task_id: str) -> str:
        """
        Get the status of a task.
        
        Args:
            task_id (str): The ID of the task
            
        Returns:
            str: Status of the task ('running', 'completed', or 'not_found')
        """
        async with self._lock:
            if task_id in self.running_tasks:
                return 'running'
            elif task_id in self.completed_tasks:
                return 'completed'
            else:
                return 'not_found'