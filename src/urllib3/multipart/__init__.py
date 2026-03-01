"""Multipart support for urllib3."""

from __future__ import annotations

from .decoder import ImproperBodyPartContentError as ImproperBodyPartContentError
from .decoder import MultipartDecoder as MultipartDecoder
from .decoder import NonMultipartContentTypeError as NonMultipartContentTypeError
from .encoder import MultipartEncoder as MultipartEncoder

__authors__ = "Ian Stapleton Cordasco, Cory Benfield"
__copyright__ = "Copyright 2014 Ian Stapleton Cordasco, Cory Benfield"

__all__ = [
    "MultipartEncoder",
    "MultipartDecoder",
    "ImproperBodyPartContentError",
    "NonMultipartContentTypeError",
]
