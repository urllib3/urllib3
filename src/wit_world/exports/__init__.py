from __future__ import annotations

import weakref
from abc import abstractmethod
from dataclasses import dataclass
from enum import Enum, Flag, auto
from types import TracebackType
from typing import Any, Generic, List, Optional, Protocol, Self, Tuple, TypeVar, Union

from ..types import Err, Ok, Result, Some


class Run(Protocol):

    @abstractmethod
    def run(self) -> None:
        """
        Run the program.

        Raises: `wit_world.types.Err(None)`
        """
        raise NotImplementedError
