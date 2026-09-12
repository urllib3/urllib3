Reject requests where a caller-supplied ``Transfer-Encoding`` header does not end
in ``chunked``. urllib3 always sends the body chunk-framed in that case, so any
other final coding would go out on the wire describing framing that is not
actually used (follow-up to the review discussion on pull request 5122).
