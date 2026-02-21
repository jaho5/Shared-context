"""Error types for the subagent tool (spec section 5)."""


class SubagentError(Exception):
    """Base error for all subagent operations."""

    code: str

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)

    def to_dict(self) -> dict:
        return {"error": self.code, "message": self.message}


class AgentNotFoundError(SubagentError):
    code = "AGENT_NOT_FOUND"


class AgentAlreadyExistsError(SubagentError):
    code = "AGENT_ALREADY_EXISTS"


class TaskNotFoundError(SubagentError):
    code = "TASK_NOT_FOUND"


class TaskNotReadyError(SubagentError):
    code = "TASK_NOT_READY"


class TaskTooLargeError(SubagentError):
    code = "TASK_TOO_LARGE"


class MaxTasksExceededError(SubagentError):
    code = "MAX_TASKS_EXCEEDED"


class InvalidAgentNameError(SubagentError):
    code = "INVALID_AGENT_NAME"


class InvalidToolError(SubagentError):
    code = "INVALID_TOOL"


class PromptTooLargeError(SubagentError):
    code = "PROMPT_TOO_LARGE"
