WASI and componentize-py
========================

`Componentize-py <https://github.com/bytecodealliance/componentize-py>`_ is a tool to convert Python code to a `WebAssembly Component <https://github.com/WebAssembly/component-model>`_.
Urllib3 will not work out of the box with componentize-py due to missing support for the ssl module in the WASI build of CPython.

Starting from version 2.5.0 urllib3 supports being used in such an environment using a new, experimental WASI backend.

Getting started
---------------

Using urllib3 in WASI works by utilizing `wasi-http <https://github.com/WebAssembly/wasi-http>`_ host functions. To begin,
add imports for these to the world your component is going to implement:

.. code-block::

    package unused:unused;

    world demo-world {
      import wasi:http/types@0.2.0;
      import wasi:http/outgoing-handler@0.2.0;

      export wasi:cli/run@0.2.0;
    }

You can then just import and use urllib3 as usual.

.. code-block:: python

    from demo_world import exports
    import urllib3

    class Run(exports.Run):
      resp = urllib3.request("GET", "https://httpbin.org/anything")
      print(resp.status)  # 200
      print(resp.headers) # HTTPHeaderDict(...)
      print(resp.json())  # {"headers": {"Accept": "*/*", ...}, ...}

Features
--------

Because a number of aspects that are normally handled by the library are delegated to the host when using the WASI backend, some
features are not supported or settings are ignored. Notable cases are:

* HTTPS: Sending HTTPS requests is supported, but the entire TLS layer is handled by the host and is not customizable from the urllib3 side. Most of the parameters specific to HTTPS requests, including custom certificate authorities, are ignored.
* Tunneling: All kinds of tunneling and proxies are not supported.
* Transfer-Encoding: Transfer encoding is handled entirely by the host and cannot be customized from the urllib3 side.
