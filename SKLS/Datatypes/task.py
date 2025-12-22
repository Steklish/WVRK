import subprocess
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

# pydantic class for AI generation
class AITask(BaseModel):
    name: str = Field(description="The name of the task")
    cli_command: str = Field(description="The CLI command to execute the task")
    reasoning: str = Field(description="The reasoning behind the task")
    time_limit: int = Field(default=30, description="Maximum execution time in seconds")


# Extended class containing the process and execution results to handle in code
class Task(AITask):
    process: Optional[subprocess.Popen] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    return_code: Optional[int] = None
    was_timeout: Optional[bool] = None
    was_cancelled: Optional[bool] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None

    model_config = {'arbitrary_types_allowed': True}