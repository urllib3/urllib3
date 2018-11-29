"""Module containing the implementation of the URIReference class."""
# -*- coding: utf-8 -*-
# Copyright (c) 2014 Rackspace
# Copyright (c) 2015 Ian Cordasco
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from collections import namedtuple
import warnings

from . import compat
from . import exceptions as exc
from . import misc
from . import normalizers
from . import validators


class URIReference(namedtuple('URIReference', misc.URI_COMPONENTS)):
    """Immutable object representing a parsed URI Reference.

    .. note::

        This class is not intended to be directly instantiated by the user.

    This object exposes attributes for the following components of a
    URI:

    - scheme
    - authority
    - path
    - query
    - fragment

    .. attribute:: scheme

        The scheme that was parsed for the URI Reference. For example,
        ``http``, ``https``, ``smtp``, ``imap``, etc.

    .. attribute:: authority

        Component of the URI that contains the user information, host,
        and port sub-components. For example,
        ``google.com``, ``127.0.0.1:5000``, ``username@[::1]``,
        ``username:password@example.com:443``, etc.

    .. attribute:: path

        The path that was parsed for the given URI Reference. For example,
        ``/``, ``/index.php``, etc.

    .. attribute:: query

        The query component for a given URI Reference. For example, ``a=b``,
        ``a=b%20c``, ``a=b+c``, ``a=b,c=d,e=%20f``, etc.

    .. attribute:: fragment

        The fragment component of a URI. For example, ``section-3.1``.

    This class also provides extra attributes for easier access to information
    like the subcomponents of the authority component.

    .. attribute:: userinfo

        The user information parsed from the authority.

    .. attribute:: host

        The hostname, IPv4, or IPv6 adddres parsed from the authority.

    .. attribute:: port

        The port parsed from the authority.
    """

    slots = ()

    def __new__(cls, scheme, authority, path, query, fragment,
                encoding='utf-8'):
        """Create a new URIReference."""
        ref = super(URIReference, cls).__new__(
            cls,
            scheme or None,
            authority or None,
            path or None,
            query,
            fragment)
        ref.encoding = encoding
        return ref

    def __eq__(self, other):
        """Compare this reference to another."""
        other_ref = other
        if isinstance(other, tuple):
            other_ref = URIReference(*other)
        elif not isinstance(other, URIReference):
            try:
                other_ref = URIReference.from_string(other)
            except TypeError:
                raise TypeError(
                    'Unable to compare URIReference() to {0}()'.format(
                        type(other).__name__))

        # See http://tools.ietf.org/html/rfc3986#section-6.2
        naive_equality = tuple(self) == tuple(other_ref)
        return naive_equality or self.normalized_equality(other_ref)

    @classmethod
    def from_string(cls, uri_string, encoding='utf-8'):
        """Parse a URI reference from the given unicode URI string.

        :param str uri_string: Unicode URI to be parsed into a reference.
        :param str encoding: The encoding of the string provided
        :returns: :class:`URIReference` or subclass thereof
        """
        uri_string = compat.to_str(uri_string, encoding)

        split_uri = misc.URI_MATCHER.match(uri_string).groupdict()
        return cls(
            split_uri['scheme'], split_uri['authority'],
            normalizers.encode_component(split_uri['path'], encoding),
            normalizers.encode_component(split_uri['query'], encoding),
            normalizers.encode_component(split_uri['fragment'], encoding),
            encoding,
        )

    def authority_info(self):
        """Return a dictionary with the ``userinfo``, ``host``, and ``port``.

        If the authority is not valid, it will raise a
        :class:`~rfc3986.exceptions.InvalidAuthority` Exception.

        :returns:
            ``{'userinfo': 'username:password', 'host': 'www.example.com',
            'port': '80'}``
        :rtype: dict
        :raises rfc3986.exceptions.InvalidAuthority:
            If the authority is not ``None`` and can not be parsed.
        """
        if not self.authority:
            return {'userinfo': None, 'host': None, 'port': None}

        match = misc.SUBAUTHORITY_MATCHER.match(self.authority)

        if match is None:
            # In this case, we have an authority that was parsed from the URI
            # Reference, but it cannot be further parsed by our
            # misc.SUBAUTHORITY_MATCHER. In this case it must not be a valid
            # authority.
            raise exc.InvalidAuthority(self.authority.encode(self.encoding))

        # We had a match, now let's ensure that it is actually a valid host
        # address if it is IPv4
        matches = match.groupdict()
        host = matches.get('host')

        if (host and misc.IPv4_MATCHER.match(host) and not
                validators.valid_ipv4_host_address(host)):
            # If we have a host, it appears to be IPv4 and it does not have
            # valid bytes, it is an InvalidAuthority.
            raise exc.InvalidAuthority(self.authority.encode(self.encoding))

        return matches

    @property
    def host(self):
        """If present, a string representing the host."""
        try:
            authority = self.authority_info()
        except exc.InvalidAuthority:
            return None
        return authority['host']

    @property
    def port(self):
        """If present, the port extracted from the authority."""
        try:
            authority = self.authority_info()
        except exc.InvalidAuthority:
            return None
        return authority['port']

    @property
    def userinfo(self):
        """If present, the userinfo extracted from the authority."""
        try:
            authority = self.authority_info()
        except exc.InvalidAuthority:
            return None
        return authority['userinfo']

    def is_absolute(self):
        """Determine if this URI Reference is an absolute URI.

        See http://tools.ietf.org/html/rfc3986#section-4.3 for explanation.

        :returns: ``True`` if it is an absolute URI, ``False`` otherwise.
        :rtype: bool
        """
        return bool(misc.ABSOLUTE_URI_MATCHER.match(self.unsplit()))

    def is_valid(self, **kwargs):
        """Determine if the URI is valid.

        .. deprecated:: 1.1.0

            Use the :class:`~rfc3986.validators.Validator` object instead.

        :param bool require_scheme: Set to ``True`` if you wish to require the
            presence of the scheme component.
        :param bool require_authority: Set to ``True`` if you wish to require
            the presence of the authority component.
        :param bool require_path: Set to ``True`` if you wish to require the
            presence of the path component.
        :param bool require_query: Set to ``True`` if you wish to require the
            presence of the query component.
        :param bool require_fragment: Set to ``True`` if you wish to require
            the presence of the fragment component.
        :returns: ``True`` if the URI is valid. ``False`` otherwise.
        :rtype: bool
        """
        warnings.warn("Please use rfc3986.validators.Validator instead. "
                      "This method will be eventually removed.",
                      DeprecationWarning)
        validators = [
            (self.scheme_is_valid, kwargs.get('require_scheme', False)),
            (self.authority_is_valid, kwargs.get('require_authority', False)),
            (self.path_is_valid, kwargs.get('require_path', False)),
            (self.query_is_valid, kwargs.get('require_query', False)),
            (self.fragment_is_valid, kwargs.get('require_fragment', False)),
            ]
        return all(v(r) for v, r in validators)

    def authority_is_valid(self, require=False):
        """Determine if the authority component is valid.

        .. deprecated:: 1.1.0

            Use the :class:`~rfc3986.validators.Validator` object instead.

        :param bool require:
            Set to ``True`` to require the presence of this component.
        :returns:
            ``True`` if the authority is valid. ``False`` otherwise.
        :rtype:
            bool
        """
        warnings.warn("Please use rfc3986.validators.Validator instead. "
                      "This method will be eventually removed.",
                      DeprecationWarning)
        try:
            self.authority_info()
        except exc.InvalidAuthority:
            return False

        return validators.authority_is_valid(
            self.authority,
            host=self.host,
            require=require,
        )

    def scheme_is_valid(self, require=False):
        """Determine if the scheme component is valid.

        .. deprecated:: 1.1.0

            Use the :class:`~rfc3986.validators.Validator` object instead.

        :param str require: Set to ``True`` to require the presence of this
            component.
        :returns: ``True`` if the scheme is valid. ``False`` otherwise.
        :rtype: bool
        """
        warnings.warn("Please use rfc3986.validators.Validator instead. "
                      "This method will be eventually removed.",
                      DeprecationWarning)
        return validators.scheme_is_valid(self.scheme, require)

    def path_is_valid(self, require=False):
        """Determine if the path component is valid.

        .. deprecated:: 1.1.0

            Use the :class:`~rfc3986.validators.Validator` object instead.

        :param str require: Set to ``True`` to require the presence of this
            component.
        :returns: ``True`` if the path is valid. ``False`` otherwise.
        :rtype: bool
        """
        warnings.warn("Please use rfc3986.validators.Validator instead. "
                      "This method will be eventually removed.",
                      DeprecationWarning)
        return validators.path_is_valid(self.path, require)

    def query_is_valid(self, require=False):
        """Determine if the query component is valid.

        .. deprecated:: 1.1.0

            Use the :class:`~rfc3986.validators.Validator` object instead.

        :param str require: Set to ``True`` to require the presence of this
            component.
        :returns: ``True`` if the query is valid. ``False`` otherwise.
        :rtype: bool
        """
        warnings.warn("Please use rfc3986.validators.Validator instead. "
                      "This method will be eventually removed.",
                      DeprecationWarning)
        return validators.query_is_valid(self.query, require)

    def fragment_is_valid(self, require=False):
        """Determine if the fragment component is valid.

        .. deprecated:: 1.1.0

            Use the Validator object instead.

        :param str require: Set to ``True`` to require the presence of this
            component.
        :returns: ``True`` if the fragment is valid. ``False`` otherwise.
        :rtype: bool
        """
        warnings.warn("Please use rfc3986.validators.Validator instead. "
                      "This method will be eventually removed.",
                      DeprecationWarning)
        return validators.fragment_is_valid(self.fragment, require)

    def normalize(self):
        """Normalize this reference as described in Section 6.2.2.

        This is not an in-place normalization. Instead this creates a new
        URIReference.

        :returns: A new reference object with normalized components.
        :rtype: URIReference
        """
        # See http://tools.ietf.org/html/rfc3986#section-6.2.2 for logic in
        # this method.
        return URIReference(normalizers.normalize_scheme(self.scheme or ''),
                            normalizers.normalize_authority(
                                (self.userinfo, self.host, self.port)),
                            normalizers.normalize_path(self.path or ''),
                            normalizers.normalize_query(self.query),
                            normalizers.normalize_fragment(self.fragment),
                            self.encoding)

    def normalized_equality(self, other_ref):
        """Compare this URIReference to another URIReference.

        :param URIReference other_ref: (required), The reference with which
            we're comparing.
        :returns: ``True`` if the references are equal, ``False`` otherwise.
        :rtype: bool
        """
        return tuple(self.normalize()) == tuple(other_ref.normalize())

    def resolve_with(self, base_uri, strict=False):
        """Use an absolute URI Reference to resolve this relative reference.

        Assuming this is a relative reference that you would like to resolve,
        use the provided base URI to resolve it.

        See http://tools.ietf.org/html/rfc3986#section-5 for more information.

        :param base_uri: Either a string or URIReference. It must be an
            absolute URI or it will raise an exception.
        :returns: A new URIReference which is the result of resolving this
            reference using ``base_uri``.
        :rtype: :class:`URIReference`
        :raises rfc3986.exceptions.ResolutionError:
            If the ``base_uri`` is not an absolute URI.
        """
        if not isinstance(base_uri, URIReference):
            base_uri = URIReference.from_string(base_uri)

        if not base_uri.is_absolute():
            raise exc.ResolutionError(base_uri)

        # This is optional per
        # http://tools.ietf.org/html/rfc3986#section-5.2.1
        base_uri = base_uri.normalize()

        # The reference we're resolving
        resolving = self

        if not strict and resolving.scheme == base_uri.scheme:
            resolving = resolving.copy_with(scheme=None)

        # http://tools.ietf.org/html/rfc3986#page-32
        if resolving.scheme is not None:
            target = resolving.copy_with(
                path=normalizers.normalize_path(resolving.path)
            )
        else:
            if resolving.authority is not None:
                target = resolving.copy_with(
                    scheme=base_uri.scheme,
                    path=normalizers.normalize_path(resolving.path)
                )
            else:
                if resolving.path is None:
                    if resolving.query is not None:
                        query = resolving.query
                    else:
                        query = base_uri.query
                    target = resolving.copy_with(
                        scheme=base_uri.scheme,
                        authority=base_uri.authority,
                        path=base_uri.path,
                        query=query
                    )
                else:
                    if resolving.path.startswith('/'):
                        path = normalizers.normalize_path(resolving.path)
                    else:
                        path = normalizers.normalize_path(
                            misc.merge_paths(base_uri, resolving.path)
                        )
                    target = resolving.copy_with(
                        scheme=base_uri.scheme,
                        authority=base_uri.authority,
                        path=path,
                        query=resolving.query
                    )
        return target

    def unsplit(self):
        """Create a URI string from the components.

        :returns: The URI Reference reconstituted as a string.
        :rtype: str
        """
        # See http://tools.ietf.org/html/rfc3986#section-5.3
        result_list = []
        if self.scheme:
            result_list.extend([self.scheme, ':'])
        if self.authority:
            result_list.extend(['//', self.authority])
        if self.path:
            result_list.append(self.path)
        if self.query is not None:
            result_list.extend(['?', self.query])
        if self.fragment is not None:
            result_list.extend(['#', self.fragment])
        return ''.join(result_list)

    def copy_with(self, scheme=misc.UseExisting, authority=misc.UseExisting,
                  path=misc.UseExisting, query=misc.UseExisting,
                  fragment=misc.UseExisting):
        """Create a copy of this reference with the new components.

        :param str scheme:
            (optional) The scheme to use for the new reference.
        :param str authority:
            (optional) The authority to use for the new reference.
        :param str path:
            (optional) The path to use for the new reference.
        :param str query:
            (optional) The query to use for the new reference.
        :param str fragment:
            (optional) The fragment to use for the new reference.
        :returns:
            New URIReference with provided components.
        :rtype:
            URIReference
        """
        attributes = {
            'scheme': scheme,
            'authority': authority,
            'path': path,
            'query': query,
            'fragment': fragment,
        }
        for key, value in list(attributes.items()):
            if value is misc.UseExisting:
                del attributes[key]
        uri = self._replace(**attributes)
        uri.encoding = self.encoding
        return uri
