Fixed ``SSLTransport.makefile()`` leaking a socket reference (``_io_refs``) and
preventing the underlying socket from closing when stream creation failed.
