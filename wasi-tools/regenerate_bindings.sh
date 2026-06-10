#! /bin/sh

rm -rf src/wit_world
componentize-py --import-interface-name "wasi:http/types@0.2.0"="types" --import-interface-name "wasi:http/outgoing-handler@0.2.0"="outgoing_handler" --wit-path wasi-tools/wit bindings src
