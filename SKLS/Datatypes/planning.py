from pydantic import BaseModel, Field

class AIPlanning(BaseModel):
    objective: str = Field(description="The overall objective to be achieved")
    constraints: str = Field(description="Constraints that must be adhered to during planning")
    steps: int = Field(default=5, description="Number of planning steps to generate")
    
class AISubtask(BaseModel):
    name: str = Field(description="The name of the subtask")
    description: str = Field(description="A detailed description of the subtask")
    dependencies: list[str] = Field(default_factory=list, description="List of subtasks that must be completed before this one")
    
class AIAction(BaseModel):
    subtask_name: str = Field(description="The name of the subtask this action belongs to")
    action_command: str = Field(description="The CLI command to execute this action")
    expectations: str = Field(description="The expected output or result of this action")