Creating a new CRT
------------------

(Instructions lifted from Heroku_)

1. Generate a new CSR::
   
   openssl req -new -key server.key -out server.new.csr

1. Generate a new CRT::

   openssl x509 -req -in server.new.csr -signkey server.key -out server.new.crt

Creating a new PEM file with your new CRT
-----------------------------------------

1. Concatenate the ``crt`` and ``key`` files into one::

   cat server.new.crt server.key > cacert.new.pem


:Last Modified: 1 Nov 2014

.. _Heroku: https://devcenter.heroku.com/articles/ssl-certificate-self
