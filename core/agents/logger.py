from enum import Enum
from core.agents.base import BaseAgent
from core.agents.convo import AgentConvo
from core.agents.response import AgentResponse
from core.db.models.project_state import IterationStatus
from core.llm.parser import StringParser, JSONParser
from core.log import get_logger
from typing import Annotated, Literal, Optional, Union
from pydantic import BaseModel, Field

log = get_logger(__name__)

class StepType(str, Enum):
    ADD_LOG = "add_log"
    EXPLAIN_PROBLEM = "explain_problem"
    GET_ADDITIONAL_FILES = "get_additional_files"

class Log(BaseModel):
    filePath: str
    referenceCodeSnippet: str = Field(description="Five lines of code before the line where the log needs to be added. Make sure that this contains **ONLY** the code that is currently written in the file. It must not contain the log that you want to add.")
    log: str

class AddLog(BaseModel):
    type: Literal[StepType.ADD_LOG] = StepType.ADD_LOG
    logsToAdd: list[Log]

class ExplainProblem(BaseModel):
    type: Literal[StepType.EXPLAIN_PROBLEM] = StepType.EXPLAIN_PROBLEM
    problem_explanation: str

class GetAdditionalFiles(BaseModel):
    type: Literal[StepType.GET_ADDITIONAL_FILES] = StepType.GET_ADDITIONAL_FILES
    filePath: str

# TODO enable LLM to ask for more files
class LoggingOptions(BaseModel):
    decision: Annotated[
        Union[AddLog, ExplainProblem, GetAdditionalFiles],
        Field(discriminator="type"),
    ]

class Logger(BaseAgent):
    agent_type = "logger"
    display_name = "Logger Agent"

    async def run(self) -> AgentResponse:
        llm = self.get_llm()
        convo = (
            AgentConvo(self)
            .template(
                "iteration",
                current_task=self.current_state.current_task,
                user_feedback=self.current_state.current_iteration["user_feedback"],
                user_feedback_qa=self.current_state.current_iteration["user_feedback_qa"],
                docs=self.current_state.docs,
                next_solution_to_try=None # TODO što sa ovime????
            )
        )
        human_readable_explanation = await llm(convo, temperature=0.5)

        # TODO call CodeMonkey
        for file in files_needed_to_log:
            self.next_state.set_current_iteration_status(IterationStatus.AWAITING_LOG_IMPLEMENTATION)

        self.next_state.steps = finished_steps + [
            {
                "id": uuid4().hex,
                "completed": False,
                "source": source,
                "iteration_index": len(self.current_state.iterations),
                **step.model_dump(),
            }
            for step in response.steps
        ]
        # TODO call CodeReviewer
        # TODO send for testing



        convo = (
            AgentConvo(self)
            .template(
                "iteration",
                current_task=self.current_state.current_task,
                user_feedback=self.current_state.current_iteration["user_feedback"],
                user_feedback_qa=self.current_state.current_iteration["user_feedback_qa"],
                docs=self.current_state.docs,
                next_solution_to_try=None  # TODO što sa ovime????
            )
            .assistant(human_readable_explanation)
            .template("parse_logging_decision")
            .require_schema(LoggingOptions)
        )
        parsed_next_steps: LoggingOptions = await llm(convo, parser=JSONParser(LoggingOptions), temperature=0.5)

        if parsed_next_steps.decision.type == StepType.ADD_LOG:
            # put the logs in the right place in the code
            for log in parsed_next_steps.decision.logsToAdd:
                # TODO make it so that, if there are multiple logs in a single file, they are processed at the same time and not twice
                path = log.filePath
                content = await self.add_log_to_file(log)
                await self.state_manager.save_file(path, content)

            # TODO
            self.next_state.set_current_task_status(TaskStatus.DOCUMENTED)
            self.current_state.current_iteration["status"] = IterationStatus.AWAITING_TEST
            return AgentResponse.done(self)
        elif parsed_next_steps.decision.type == StepType.EXPLAIN_PROBLEM:
            # TODO
            pass
        elif parsed_next_steps.decision.type == StepType.GET_ADDITIONAL_FILES:
            # TODO
            pass


        # TODO promijeniti status tako da Orchestrator može znati koga da zove


            # TODO tell the user how to test the app

            # TODO parse only the relevant logs
        return AgentResponse.done(self)


    async def  add_log_to_file(self, log: Log):
        file_content = await self.state_manager.get_file_by_path(log.filePath)
        file_content = file_content.content.content if file_content else ""

        # Split the file content by lines
        file_lines = file_content.splitlines()

        # Find the starting index of the reference code snippet
        start_index = None
        snippet_lines = log.referenceCodeSnippet.strip().splitlines()

        for i in range(len(file_lines)):
            match = True
            for j in range(len(snippet_lines)):
                if i + j >= len(file_lines) or file_lines[i + j].strip() != snippet_lines[j].strip():
                    match = False
                    break
            if match:
                start_index = i + len(snippet_lines)
                break

        # If the snippet is found, insert the log after it
        if start_index is not None:
            # Add log after the snippet
            updated_file_lines = file_lines[:start_index] + [log.log] + file_lines[start_index:]
            updated_file_content = "\n".join(updated_file_lines)
            return updated_file_content
        else:
            raise ValueError("Reference code snippet not found in the file content")

