from __future__ import annotations

import weakref
from abc import abstractmethod
from dataclasses import dataclass
from enum import Enum, Flag, auto
from types import TracebackType
from typing import Any, Generic, List, Optional, Protocol, Self, Tuple, TypeVar, Union

S = TypeVar("S")


@dataclass
class Some(Generic[S]):
    value: S


T = TypeVar("T")


@dataclass
class Ok(Generic[T]):
    value: T


E = TypeVar("E")


@dataclass(frozen=True)
class Err(Generic[E], Exception):
    value: E


Result = Union[Ok[T], Err[E]]
