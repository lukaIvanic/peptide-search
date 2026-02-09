"""LLM provider interface and DocumentInput abstraction."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Protocol, runtime_checkable, List, Tuple, Dict


class InputType(Enum):
    """Type of document input for LLM processing."""
    TEXT = auto()      # Plain text content
    URL = auto()       # URL to fetch (PDF or HTML)
    FILE = auto()      # Raw file bytes
    MULTI_FILE = auto()  # Multiple raw files


@dataclass
class DocumentInput:
    """
    Abstraction for document input to LLM providers.
    
    This unifies text, URL, and file inputs so providers can handle
    them uniformly without hasattr checks in the service layer.
    """
    input_type: InputType
    text: Optional[str] = None
    url: Optional[str] = None
    file_content: Optional[bytes] = None
    filename: Optional[str] = None
    files: Optional[List[Tuple[bytes, str]]] = None
    metadata_hint: str = ""
    
    @classmethod
    def from_text(cls, text: str, metadata_hint: str = "") -> "DocumentInput":
        """Create input from plain text."""
        return cls(
            input_type=InputType.TEXT,
            text=text,
            metadata_hint=metadata_hint,
        )
    
    @classmethod
    def from_url(cls, url: str, metadata_hint: str = "") -> "DocumentInput":
        """Create input from a URL (PDF or HTML)."""
        return cls(
            input_type=InputType.URL,
            url=url,
            metadata_hint=metadata_hint,
        )
    
    @classmethod
    def from_file(cls, content: bytes, filename: str, metadata_hint: str = "") -> "DocumentInput":
        """Create input from file bytes."""
        return cls(
            input_type=InputType.FILE,
            file_content=content,
            filename=filename,
            metadata_hint=metadata_hint,
        )

    @classmethod
    def from_files(cls, files: List[Tuple[bytes, str]], metadata_hint: str = "") -> "DocumentInput":
        """Create input from multiple file bytes."""
        return cls(
            input_type=InputType.MULTI_FILE,
            files=files,
            metadata_hint=metadata_hint,
        )


@dataclass
class LLMCapabilities:
    """Explicit capabilities of an LLM provider."""
    supports_pdf_url: bool = False      # Can process PDF URLs directly
    supports_pdf_file: bool = False     # Can process uploaded PDF files
    supports_json_mode: bool = True     # Supports JSON response format


@runtime_checkable
class LLMProvider(Protocol):
    """
    Protocol for LLM providers.
    
    All providers must implement:
    - name(): return provider identifier
    - capabilities(): return LLMCapabilities
    - generate(): unified generation method that handles DocumentInput
    """
    
    def name(self) -> str:
        """Return provider identifier (e.g., 'openai', 'deepseek', 'mock')."""
        ...
    
    def model_name(self) -> str:
        """Return the model name being used."""
        ...
    
    def capabilities(self) -> LLMCapabilities:
        """Return provider capabilities."""
        ...

    def get_last_usage(self) -> Optional[Dict[str, Optional[int]]]:
        """Return token usage from the most recent call, if available."""
        ...
    
    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        document: Optional[DocumentInput] = None,
        temperature: float = 0.2,
        max_tokens: int = 2000,
    ) -> str:
        """
        Generate JSON response from the LLM.
        
        Args:
            system_prompt: System/developer instructions
            user_prompt: User prompt with task and schema
            document: Optional document input (URL, file, or pre-extracted text)
            temperature: Sampling temperature
            max_tokens: Maximum output tokens
            
        Returns:
            JSON string response from the model
            
        Raises:
            RuntimeError: If generation fails
        """
        ...
