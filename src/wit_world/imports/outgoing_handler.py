"""
This interface defines a handler of outgoing HTTP Requests. It should be
imported by components which wish to make HTTP Requests.
"""

from __future__ import annotations

import weakref
from abc import abstractmethod
from dataclasses import dataclass
from enum import Enum, Flag, auto
from types import TracebackType
from typing import Any, Generic, List, Optional, Protocol, Self, Tuple, TypeVar, Union

from ..imports import types
from ..types import Err, Ok, Result, Some


def handle(
    request: types.OutgoingRequest, options: types.RequestOptions | None
) -> types.FutureIncomingResponse:
    """
    This function is invoked with an outgoing HTTP Request, and it returns
    a resource `future-incoming-response` which represents an HTTP Response
    which may arrive in the future.

    The `options` argument accepts optional parameters for the HTTP
    protocol's transport layer.

    This function may return an error if the `outgoing-request` is invalid
    or not allowed to be made. Otherwise, protocol errors are reported
    through the `future-incoming-response`.

    Raises: `wit_world.types.Err(wit_world.imports.types.ErrorCode)`
    """
    raise NotImplementedError
