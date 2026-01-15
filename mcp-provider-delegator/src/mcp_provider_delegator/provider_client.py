"""Provider clients for invoking agents via Codex, Gemini, etc."""

import asyncio
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


class RateLimitError(Exception):
    """Raised when a provider hits rate limits."""
    pass


@dataclass
class FallbackHint:
    """Hint for falling back to Claude Task tool."""
    subagent_type: str
    model: str
    prompt: str

    def to_string(self) -> str:
        """Generate Task() call suggestion."""
        # Escape the prompt for display
        # Include PROVIDER_FALLBACK marker so hooks allow bypass
        escaped_prompt = self.prompt.replace('"', '\\"')[:500]
        if len(self.prompt) > 500:
            escaped_prompt += "..."
        return f'''Task(
    subagent_type="{self.subagent_type}",
    model="{self.model}",
    prompt="PROVIDER_FALLBACK: {escaped_prompt}"
)'''


@dataclass
class InvokeResult:
    """Result of a provider invocation."""
    success: bool
    response: str
    provider: str
    error: Optional[str] = None
    fallback_hint: Optional[FallbackHint] = None


class ProviderClient(ABC):
    """Abstract base class for AI provider clients."""

    name: str = "base"

    @abstractmethod
    async def invoke(self, prompt: str) -> str:
        """Invoke the provider with a prompt."""
        pass

    def is_rate_limit_error(self, error_msg: str) -> bool:
        """Check if error message indicates rate limiting."""
        rate_limit_indicators = [
            "rate limit",
            "429",
            "too many requests",
            "usage limit",
            "quota exceeded",
        ]
        error_lower = error_msg.lower()
        return any(indicator in error_lower for indicator in rate_limit_indicators)


class CodexClient(ProviderClient):
    """Client for OpenAI Codex."""

    name = "codex"

    # Map agent model preferences to Codex models
    MODEL_MAPPING = {
        "haiku": "gpt-5.1-codex-mini",
        "sonnet": "gpt-5.2-codex",
        "opus": "gpt-5.1-codex-max",
    }

    def __init__(self, model: str = "gpt-5.2-codex"):
        self.model = model

    @classmethod
    def map_model(cls, agent_model: str) -> str:
        """Map agent's preferred model to Codex model."""
        return cls.MODEL_MAPPING.get(agent_model, "gpt-5.2-codex")

    async def invoke(self, prompt: str) -> str:
        """Invoke Codex with prompt."""
        cmd = [
            "codex",
            "exec",
            "-m", self.model,
            "--sandbox", "workspace-write",
            prompt,
        ]

        logger.info(f"[Codex] Invoking with model: {self.model}")

        try:
            cwd = os.getcwd()
            env = os.environ.copy()

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=cwd,
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                if self.is_rate_limit_error(error_msg):
                    raise RateLimitError(f"Codex rate limit: {error_msg}")
                raise RuntimeError(f"Codex failed: {error_msg}")

            response = stdout.decode().strip()
            logger.info(f"[Codex] Response length: {len(response)} chars")
            return response

        except FileNotFoundError:
            raise RuntimeError("Codex CLI not found. Install with: codex login")


class GeminiClient(ProviderClient):
    """Client for Google Gemini."""

    name = "gemini"
    model = "gemini-3-flash-preview"

    async def invoke(self, prompt: str) -> str:
        """Invoke Gemini with prompt."""
        cmd = [
            "gemini",
            "-p", prompt,
            "-m", self.model,
            "-y",  # Auto-approve tool calls for agentic execution
        ]

        logger.info(f"[Gemini] Invoking with model: {self.model}")

        try:
            cwd = os.getcwd()
            env = os.environ.copy()

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=cwd,
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                if self.is_rate_limit_error(error_msg):
                    raise RateLimitError(f"Gemini rate limit: {error_msg}")
                raise RuntimeError(f"Gemini failed: {error_msg}")

            response = stdout.decode().strip()
            logger.info(f"[Gemini] Response length: {len(response)} chars")
            return response

        except FileNotFoundError:
            raise RuntimeError("Gemini CLI not found. Install with: pip install gemini-cli")


# Map agent names to Claude Task subagent_types for fallback
# These match the subagent_type values available in Claude Code's Task tool
AGENT_TO_SUBAGENT = {
    "scout": "scout",
    "detective": "scout",  # detective uses scout for investigation
    "architect": "Plan",
    "scribe": "scout",  # scribe reads codebase to document
    "code-reviewer": "superpowers:code-reviewer",
}

# Map agent model preferences to Claude Task models
AGENT_MODEL_TO_TASK_MODEL = {
    "haiku": "haiku",
    "sonnet": "sonnet",
    "opus": "opus",
}


class ProviderChain:
    """Chain of providers with fallback support."""

    def __init__(
        self,
        providers: list[ProviderClient],
        allow_skip: bool = False,
        agent_name: str = "",
        agent_model: str = "sonnet",
    ):
        """
        Initialize provider chain.

        Args:
            providers: List of providers to try in order
            allow_skip: If True, return skip message when all providers fail
            agent_name: Name of the agent (for fallback hints)
            agent_model: Agent's preferred model (for fallback hints)
        """
        self.providers = providers
        self.allow_skip = allow_skip
        self.agent_name = agent_name
        self.agent_model = agent_model

    def _create_fallback_hint(self, user_prompt: str) -> FallbackHint:
        """Create a fallback hint for Claude Task tool."""
        subagent_type = AGENT_TO_SUBAGENT.get(self.agent_name, "general-purpose")
        task_model = AGENT_MODEL_TO_TASK_MODEL.get(self.agent_model, "sonnet")
        return FallbackHint(
            subagent_type=subagent_type,
            model=task_model,
            prompt=user_prompt,
        )

    async def invoke(
        self,
        system_prompt: str,
        user_prompt: str,
        task_id: Optional[str] = None,
    ) -> InvokeResult:
        """
        Invoke providers in chain until one succeeds.

        Returns:
            InvokeResult with success status, response, and provider used
        """
        combined_prompt = f"{system_prompt}\n\n---\n\n{user_prompt}"
        if task_id:
            combined_prompt = f"TASK_ID: {task_id}\n\n{combined_prompt}"

        errors = []

        for provider in self.providers:
            try:
                logger.info(f"Trying provider: {provider.name}")
                response = await provider.invoke(combined_prompt)
                return InvokeResult(
                    success=True,
                    response=response,
                    provider=provider.name,
                )
            except RateLimitError as e:
                logger.warning(f"{provider.name} rate limited: {e}")
                errors.append(f"{provider.name}: rate limited")
                continue
            except RuntimeError as e:
                logger.error(f"{provider.name} failed: {e}")
                errors.append(f"{provider.name}: {e}")
                continue

        # All providers failed
        if self.allow_skip:
            return InvokeResult(
                success=True,  # Skip is a valid outcome
                response="SKIPPED: All providers rate limited. Task skipped.",
                provider="skip",
                error="; ".join(errors),
            )

        # Create fallback hint for non-skippable agents
        fallback_hint = self._create_fallback_hint(user_prompt)
        fallback_response = f"""PROVIDER_FALLBACK_REQUIRED

All external providers (Codex, Gemini) failed for agent '{self.agent_name}'.
Errors: {'; '.join(errors)}

To complete this task, use Claude Task tool instead:

{fallback_hint.to_string()}

Note: The Task tool runs locally and doesn't have the same rate limits."""

        return InvokeResult(
            success=False,
            response=fallback_response,
            provider="none",
            error=f"All providers failed: {'; '.join(errors)}",
            fallback_hint=fallback_hint,
        )


def create_provider_chain(agent_model: str, agent_name: str) -> ProviderChain:
    """
    Create a provider chain for an agent.

    Args:
        agent_model: Agent's preferred model (haiku, sonnet, opus)
        agent_name: Name of the agent (for skip logic and fallback hints)

    Returns:
        ProviderChain configured for the agent
    """
    codex_model = CodexClient.map_model(agent_model)

    providers = [
        CodexClient(model=codex_model),
        GeminiClient(),
    ]

    # Code reviewer can be skipped if all providers fail
    allow_skip = agent_name == "code-reviewer"

    return ProviderChain(
        providers=providers,
        allow_skip=allow_skip,
        agent_name=agent_name,
        agent_model=agent_model,
    )
