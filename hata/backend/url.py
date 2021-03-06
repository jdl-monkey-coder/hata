﻿# -*- coding: utf-8 -*-
# https://github.com/squeaky-pl/zenchmarks/blob/master/vendor/yarl/__init__.py
from ipaddress import ip_address
from urllib.parse import SplitResult, parse_qsl as parse_query_string_list, urljoin as url_join, \
    urlsplit as url_split, urlunsplit as url_unsplit
from math import isinf, isnan

from .utils import multidict, cached_property
from .quote import quote, unquote

NoneType = type(None)

DEFAULT_PORTS = {
    'http'  : 80,
    'https' : 443,
    'ws'    : 80,
    'wss'   : 443,
        }

class URL:
    # Don't derive from str
    # follow pathlib.Path design
    # probably URL will not suffer from pathlib problems:
    # it's intended for libraries like aiohttp,
    # not to be passed into standard library functions like os.open etc.

    # URL grammar (RFC 3986)
    # pct-encoded = "%" HEXDIG HEXDIG
    # reserved    = gen-delims / sub-delims
    # gen-delims  = ":" / "/" / "?" / "#" / "[" / "]" / "@"
    # sub-delims  = "!" / "$" / "&" / "'" / "(" / ")"
    #             / "*" / "+" / "," / ";" / "="
    # unreserved  = ALPHA / DIGIT / "-" / "." / "_" / "~"
    # URI         = scheme ":" hier-part [ "?" query ] [ "#" fragment ]
    # hier-part   = "//" authority path-abempty
    #             / path-absolute
    #             / path-rootless
    #             / path-empty
    # scheme      = ALPHA *( ALPHA / DIGIT / "+" / "-" / "." )
    # authority   = [ userinfo "@" ] host [ ":" port ]
    # userinfo    = *( unreserved / pct-encoded / sub-delims / ":" )
    # host        = IP-literal / IPv4address / reg-name
    # IP-literal = "[" ( IPv6address / IPvFuture  ) "]"
    # IPvFuture  = "v" 1*HEXDIG "." 1*( unreserved / sub-delims / ":" )
    # IPv6address =                            6( h16 ":" ) ls32
    #             /                       "::" 5( h16 ":" ) ls32
    #             / [               h16 ] "::" 4( h16 ":" ) ls32
    #             / [ *1( h16 ":" ) h16 ] "::" 3( h16 ":" ) ls32
    #             / [ *2( h16 ":" ) h16 ] "::" 2( h16 ":" ) ls32
    #             / [ *3( h16 ":" ) h16 ] "::"    h16 ":"   ls32
    #             / [ *4( h16 ":" ) h16 ] "::"              ls32
    #             / [ *5( h16 ":" ) h16 ] "::"              h16
    #             / [ *6( h16 ":" ) h16 ] "::"
    # ls32        = ( h16 ":" h16 ) / IPv4address
    #             ; least-significant 32 bits of address
    # h16         = 1*4HEXDIG
    #             ; 16 bits of address represented in hexadecimal
    # IPv4address = dec-octet "." dec-octet "." dec-octet "." dec-octet
    # dec-octet   = DIGIT                 ; 0-9
    #             / %x31-39 DIGIT         ; 10-99
    #             / "1" 2DIGIT            ; 100-199
    #             / "2" %x30-34 DIGIT     ; 200-249
    #             / "25" %x30-35          ; 250-255
    # reg-name    = *( unreserved / pct-encoded / sub-delims )
    # port        = *DIGIT
    # path          = path-abempty    ; begins with "/" or is empty
    #               / path-absolute   ; begins with "/" but not "//"
    #               / path-noscheme   ; begins with a non-colon segment
    #               / path-rootless   ; begins with a segment
    #               / path-empty      ; zero characters
    # path-abempty  = *( "/" segment )
    # path-absolute = "/" [ segment-nz *( "/" segment ) ]
    # path-noscheme = segment-nz-nc *( "/" segment )
    # path-rootless = segment-nz *( "/" segment )
    # path-empty    = 0<pchar>
    # segment       = *pchar
    # segment-nz    = 1*pchar
    # segment-nz-nc = 1*( unreserved / pct-encoded / sub-delims / "@" )
    #               ; non-zero-length segment without any colon ":"
    # pchar         = unreserved / pct-encoded / sub-delims / ":" / "@"
    # query       = *( pchar / "/" / "?" )
    # fragment    = *( pchar / "/" / "?" )
    # URI-reference = URI / relative-ref
    # relative-ref  = relative-part [ "?" query ] [ "#" fragment ]
    # relative-part = "//" authority path-abempty
    #               / path-absolute
    #               / path-noscheme
    #               / path-empty
    # absolute-URI  = scheme ":" hier-part [ "?" query ]
    __slots__ = ('_cache', '_val', )

    def __new__(cls, val='', encoded=False):
        if isinstance(val, cls):
            return val
        
        self = object.__new__(cls)
        
        if isinstance(val, str):
            val = url_split(val)
        elif isinstance(val, SplitResult):
            if not encoded:
                raise ValueError('Cannot apply decoding to SplitResult')
        else:
            raise TypeError(f'Constructor parameter should be str, got {val.__class__.__name__}')
        
        if not encoded:
            if not val[1]:
                netloc = ''
            else:
                netloc = val.hostname
                if netloc is None:
                    raise ValueError('Invalid URL: host is required for abolute urls.')
                try:
                    netloc.encode('ascii')
                except UnicodeEncodeError:
                    netloc = netloc.encode('idna').decode('ascii')
                else:
                    try:
                        ip = ip_address(netloc)
                    except:
                        pass
                    else:
                        if ip.version == 6:
                            netloc = f'[{netloc}]'
                val_port = val.port
                if val_port:
                    netloc = f'{netloc}:{val_port}'
                val_username = val.username
                if val_username:
                    user = quote(val_username)
                    val_password = val.password
                    if val_password:
                        user = f'{user}:{quote(val_password)}'
                    netloc = f'{user}@{netloc}'
            
            val = SplitResult(val[0], netloc, quote(val[2], safe='@:', protected='/'),
                query=quote(val[3], safe='=+&?/:@', protected='=+&', query_string=True),
                fragment=quote(val[4], safe='?/:@'))
        
        self._val = val
        self._cache = {}
        return self
    
    def __str__(self):
        val = self._val
        if not val.path and self.is_absolute() and (val.query or val.fragment):
            val = val._replace(path='/')
        return url_unsplit(val)
    
    def __repr__(self):
        return f'{self.__class__.__name__}({str(self)!r})'

    def __hash__(self):
        ret = self._cache.get('hash')
        if ret is None:
            ret = self._cache['hash'] = hash(self._val)
        return ret

    def __gt__(self, other):
        if type(self) is type(other):
            return self._val > other._val
        if isinstance(other, str):
            return self._val > type(self)(other)._val
        return NotImplemented
        
    def __ge__(self, other):
        if type(self) is type(other):
            return self._val >= other._val
        if isinstance(other, str):
            return self._val >= type(self)(other)._val
        return NotImplemented
        
    def __eq__(self, other):
        if type(self) is type(other):
            return self._val == other._val
        if isinstance(other, str):
            return self._val == type(self)(other)._val
        return NotImplemented
        
    def __ne__(self, other):
        if type(self) is type(other):
            return self._val != other._val
        if isinstance(other, str):
            return self._val != type(self)(other)._val
        return NotImplemented
    
    def __le__(self, other):
        if type(self) is type(other):
            return self._val <= other._val
        if isinstance(other, str):
            return self._val <= type(self)(other)._val
        return NotImplemented
        
    def __lt__(self, other):
        if type(self) is type(other):
            return self._val < other._val
        if isinstance(other, str):
            return self._val <= type(self)(other)._val
        return NotImplemented
    
    def __truediv__(self, name):
        name = quote(name, safe=':@', protected='/')
        if name.startswith('/'):
            raise ValueError('Appending path starting from slash is forbidden')
        path = self._val.path
        if path == '/':
            new_path = f'/{name}' 
        elif not path and not self.is_absolute():
            new_path = name
        else:
            parts = path.rstrip('/').split('/')
            parts.append(name)
            new_path = '/'.join(parts)
        return URL(self._val._replace(path=new_path, query='', fragment=''), encoded=True)
    
    # A check for absolute URLs.
    # Return True for absolute ones (having scheme or starting with //), False otherwise.
    def is_absolute(self):
        return (self.raw_host is not None)
    
    # A check for default port.
    # Return True if port is default for specified scheme, e.g. 'http://python.org' or 'http://python.org:80', False
    # otherwise.
    def is_default_port(self):
        if self.port is None:
            return False
        default = DEFAULT_PORTS.get(self.scheme)
        if default is None:
            return False
        return self.port == default
    
    # Return an URL with scheme, host and port parts only.
    # user, password, path, query and fragment are removed.
    def origin(self):
        if not self.is_absolute():
            raise ValueError('URL should be absolute')
        if not self._val.scheme:
            raise ValueError('URL should have scheme')
        v = self._val
        netloc = self._make_netloc(None, None, v.hostname, v.port)
        val = v._replace(netloc=netloc, path='', query='', fragment='')
        return URL(val, encoded=True)
    
    # Return a relative part of the URL.
    # scheme, user, password, host and port are removed.
    def relative(self):
        if not self.is_absolute():
            raise ValueError("URL should be absolute")
        val = self._val._replace(scheme='', netloc='')
        return URL(val, encoded=True)
    
    # Scheme for absolute URLs.
    # Empty string for relative URLs or URLs starting with //
    @property
    def scheme(self):
        return self._val.scheme
    
    # Encoded user part of URL.
    # None if user is missing.
    @property
    def raw_user(self):
        #not .username
        return self._val.username
    
    # Decoded user part of URL.
    # None if user is missing.
    @cached_property
    def user(self):
        return unquote(self.raw_user)
    
    # Encoded password part of URL.
    # None if password is missing.
    @property
    def raw_password(self):
        return self._val.password
    
    # Decoded password part of URL.
    # None if password is missing.
    @cached_property
    def password(self):
        return unquote(self.raw_password)
    
    # Encoded host part of URL.
    # None for relative URLs.
    @property
    def raw_host(self):
        # Use host instead of hostname for sake of shortness
        # May add .hostname prop later
        return self._val.hostname
    
    # Decoded host part of URL.
    # None for relative URLs.
    @cached_property
    def host(self):
        raw = self.raw_host
        if raw is None:
            return None
        return raw.encode('ascii').decode('idna')
    
    # Port part of URL.
    # None for relative URLs or URLs without explicit port and scheme without default port substitution.
    @property
    def port(self):
        return self._val.port or DEFAULT_PORTS.get(self._val.scheme)
    
    # Encoded path of URL.
    # / for absolute URLs without path part.
    @property
    def raw_path(self):
        ret = self._val.path
        if not ret and self.is_absolute():
            ret = '/'
        return ret
    
    # Decoded path of URL.
    # / for absolute URLs without path part.
    @cached_property
    def path(self):
        return unquote(self.raw_path)
    
    @cached_property
    def query(self):
        """
        A multidict representing parsed query parameters in decoded representation.
        
        An empty multidict is returned if the url has no query parts.
        
        Returns
        -------
        query : `multidict of (`str`, `Any`) items
        """
        return multidict(parse_query_string_list(self.query_string, keep_blank_values=True))
    
    # Encoded query part of URL.
    # Empty string if query is missing.
    @property
    def raw_query_string(self):
        return self._val.query
    
    # Decoded query part of URL.
    # Empty string if query is missing.
    @cached_property
    def query_string(self):
        return unquote(self.raw_query_string, query_string=True)
    
    # Encoded fragment part of URL.
    # Empty string if fragment is missing.
    
    @property
    def raw_fragment(self):
        return self._val.fragment

    # Decoded fragment part of URL.
    # Empty string if fragment is missing.
    @cached_property
    def fragment(self):
        return unquote(self.raw_fragment)
    
    # A tuple containing encoded *path* parts.
    # ('/',) for absolute URLs if *path* is missing.
    @cached_property
    def raw_parts(self):
        path = self._val.path
        if self.is_absolute():
            parts = ['/']
            if path:
                parts.extend(path[1:].split('/'))
        else:
            if path.startswith('/'):
                parts=['/']
                parts.extend(path[1:].split('/'))
            else:
                parts = path.split('/')
        return tuple(parts)
    
    # A tuple containing decoded *path* parts.
    # ('/',) for absolute URLs if *path* is missing.
    
    @cached_property
    def parts(self):
        return tuple(unquote(part) for part in self.raw_parts)
    
    # A new URL with last part of path removed and cleaned up query and fragment.
    @cached_property
    def parent(self):
        path = self.raw_path
        if not path or path == '/':
            if self.raw_fragment or self.raw_query_string:
                return URL(self._val._replace(query='', fragment=''), encoded=True)
            return self
        parts = path.split('/')
        val = self._val._replace(path='/'.join(parts[:-1]), query='', fragment='')
        return URL(val, encoded=True)
    
    # The last part of raw_parts.
    @cached_property
    def raw_name(self):
        parts = self.raw_parts
        if self.is_absolute():
            parts = parts[1:]
            if not parts:
                return ''
            else:
                return parts[-1]
        else:
            return parts[-1]
    # The last part of parts.
    @cached_property
    def name(self):
        return unquote(self.raw_name)
    
    @classmethod
    def _make_netloc(cls, user, password, host, port):
        ret = host
        if port:
            ret = f'{ret}:{port!s}'
        if password:
            if not user:
                raise ValueError('Non-empty password requires non-empty user')
            user = f'{user}:{password}'
        if user:
            ret = f'{user}@{ret}'
        return ret
    
    # Return a new URL with scheme replaced.
    def with_scheme(self, scheme):
        # N.B. doesn't cleanup query/fragment
        if not isinstance(scheme, str):
            raise TypeError(f'Invalid scheme type: {type(scheme)!r}.')
        if not self.is_absolute():
            raise ValueError('scheme replacement is not allowed  for relative URLs')
        return URL(self._val._replace(scheme=scheme.lower()), encoded=True)
    
    # Return a new URL with user replaced.
    # Autoencode user if needed.
    # Clear user/password if user is None.
    def with_user(self, user):
        # N.B. doesn't cleanup query/fragment
        val = self._val
        if user is None:
            password = None
        elif isinstance(user, str):
            user = quote(user)
            password = val.password
        else:
            raise TypeError(f'Invalid user type {type(user)!r}')
        if not self.is_absolute():
            raise ValueError('User replacement is not allowed for relative URLs')
        return URL(
            self._val._replace(netloc=self._make_netloc(user, password, val.hostname, val.port)), encoded=True)
    
    # Return a new URL with password replaced.
    # Autoencode password if needed.
    # Clear password if argument is None.
    def with_password(self, password):
        # N.B. doesn't cleanup query/fragment
        if password is None:
            pass
        elif isinstance(password, str):
            password = quote(password)
        else:
            raise TypeError(f'Invalid password type: {type(password)!r}.')
        if not self.is_absolute():
            raise ValueError('Password replacement is not allowed for relative URLs')
        val = self._val
        return URL(
            self._val._replace( netloc=self._make_netloc(val.username, password, val.hostname, val.port)), encoded=True)
    
    # Return a new URL with host replaced.
    # Autoencode host if needed.
    # Changing host for relative URLs is not allowed, use .join() instead.
    def with_host(self, host):
        # N.B. doesn't cleanup query/fragment
        if not isinstance(host, str):
            raise TypeError(f'Invalid host type: {type(host)!r}.')
        if not self.is_absolute():
            raise ValueError('host replacement is not allowed for relative URLs')
        if not host:
            raise ValueError('host removing is not allowed')
        try:
            ip = ip_address(host)
        except:
            host = host.encode('idna').decode('ascii')
        else:
            if ip.version == 6:
                host = f'[{host}]'
        val = self._val
        return URL(self._val._replace(netloc=self._make_netloc(val.username, val.password,host, val.port)), encoded=True)
    
    # Return a new URL with port replaced.
    # Clear port to default if None is passed.
    def with_port(self, port):
        # N.B. doesn't cleanup query/fragment
        if port is not None and not isinstance(port, int):
            raise TypeError(f'port should be int or None, got {type(port)!r}.')
        if not self.is_absolute():
            raise ValueError('port replacement is not allowed for relative URLs')
        val = self._val
        return URL(self._val._replace(netloc=self._make_netloc(val.username, val.password, val.hostname, port)),
            encoded=True)
    
    def with_query(self, query):
        """
        Returns a new url with query part replaced. If `None` is given as `param` you can clear the actual query.
        
        Parameters
        ----------
        query : `None`, `str`, (`dict`, `list`, `set`) of \
                (`str`, (`str`, `int`, `bool`, `NoneType`, `float`, (`list`, `set`, `tuple`) of repeat value)) items
            The query to use.
        
        Returns
        -------
        url : ``URL``
            The new url instance.
        
        Raises
        ------
        TypeError
            - If `query` was given as an invalid type.
            - If `query` was given as `set` or `list`, but `1` of it's elements cannot be unpacked correctly.
            - If a query key was not given as `str` instance.
            - If a query value was not given as any of the expected types.
        ValueError
            - If a query value was given as `float`, but as `inf`.
            - If a query value was given as `float`, but as `nan`.
        """
        if query is None:
            query = ''
        elif isinstance(query, dict):
            query = build_query_from_dict(query)
        elif isinstance(query, (list, set)):
            query = build_query_from_list(query)
        elif isinstance(query, str):
            query = quote(query, safe='/?:@', protected='=&+', query_string=True)
        elif isinstance(query, (bytes, bytearray, memoryview)):
            raise TypeError(f'Query type cannot be `bytes`, `bytearray` and `memoryview`, got '
                f'{query.__class__.__name__}')
        else:
            raise TypeError(f'Invalid query type: {query.__class__.__name__}.')
        
        path = self._val.path
        if path == '':
            path = '/'
        
        return URL(self._val._replace(path=path, query=query), encoded=True)
    
    # Return a new URL with fragment replaced.
    # Autoencode fragment if needed.
    # Clear fragment to default if None is passed.
    def with_fragment(self, fragment):
        # N.B. doesn't cleanup query/fragment
        if fragment is None:
            fragment = ''
        elif not isinstance(fragment, str):
            raise TypeError('Invalid fragment type')
        return URL(self._val._replace(fragment=quote(fragment, safe='?/:@')), encoded=True)
    
    # Return a new URL with name (last part of path) replaced.
    # Query and fragment parts are cleaned up.
    # Name is encoded if needed.
    def with_name(self, name):
        # N.B. DOES cleanup query/fragment
        if not isinstance(name, str):
            raise TypeError(f'Invalid name type: {type(str)!r}.')
        if '/' in name:
            raise ValueError('Slash in name is not allowed')
        name = quote(name, safe='@:', protected='/')
        parts = list(self.raw_parts)
        if self.is_absolute():
            if len(parts) == 1:
                parts.append(name)
            else:
                parts[-1] = name
            parts[0] = ''  # replace leading '/'
        else:
            parts[-1] = name
            if parts[0] == '/':
                parts[0] = ''  # replace leading '/'
        return URL(self._val._replace(path='/'.join(parts), query='', fragment=''), encoded=True)
    
    # Join URLs
    # Construct a full (“absolute”) URL by combining a “base URL” (self) with another URL (url).
    # Informally, this uses components of the base URL, in particular the addressing scheme, the network location and
    # (part of) the path, to provide missing components in the relative URL.
    def join(self, url):
        # See docs for urllib.parse.url_join
        if not isinstance(url, URL):
            raise TypeError('url should be URL')
        return URL(url_join(str(self), str(url)), encoded=True)
    
    # Return decoded human readable string for URL representation.
    def human_repr(self):
        return url_unsplit(SplitResult(self.scheme, self._make_netloc(self.user, self.password, self.host,
            self._val.port), self.path, self.query_string, self.fragment))
    
    def extend_query(self, params):
        if params:
            query = multidict(self.query)
            url = self.with_query(params)
            query.extend(url.query)
            self = self.with_query(query)
        
        return self


def build_query_from_dict(query):
    """
    Builds a query string and adds the parts of it to the given `build_to` list.
    
    Parameters
    ----------
    query : `dict` of (`str`, (`str`, `int`, `bool`, `NoneType`, `float`, (`list`, `tuple`, `set`) of repeat value)) items
        The query to serialize.
    
    Returns
    -------
    query_string : `str`
        The built query string.
    
    Raises
    ------
    TypeError
        - If `1` of `query`'s keys is not `str` instance.
        - If a query value is not any of the expected types.
    ValueError
        - If a query value was given as `float` and it is `inf`.
        - If a query value was given as `float` and it is `nan`.
    """
    build_to = []
    
    for key, value in query.items():
        query_key = quote(key, safe="/?:@", query_string=True)
        build_query_element_to(build_to, query_key, value)
    
    return ''.join(build_to)


def build_query_from_list(query):
    """
    Builds a query string and adds the parts of it to the given `build_to` list.
    
    Parameters
    ----------
    query : (`list` or `set`) of `tuple` \
            (`str`, (`str`, `int`, `bool`, `NoneType`, `float`, (`list`, `tuple`, `set`) of repeat value))
        The query to serialize.
    
    Returns
    -------
    query_string : `str`
        The built query string.
    
    Raises
    ------
    TypeError
        - If `1` of `query`'s elements cannot be unpacked to a `key` - `value` pair.
        - If `1` of `query`'s keys is not `str` instance.
        - If a query value is not any of the expected types.
    ValueError
        - If a query value was given as `float` and it is `inf`.
        - If a query value was given as `float` and it is `nan`.
    """
    build_to = []
    
    for key, value in query:
        query_key = quote(key, safe="/?:@", query_string=True)
        build_query_element_to(build_to, query_key, value)
    
    return ''.join(build_to)


def build_query_element_to(build_to, query_key, value):
    """
    Builds a query string element to the given `build_to` list.
    
    Parameters
    ----------
    build_to : `list`
        A list to build the query element to.
    query_key : `str`
        An already escaped query key.
    value : `str`, `int`, `bool`, `NoneType`, `float`, (`list`, `tuple`,  `set`) of repeat
        The query string value.
    
    Raises
    ------
    TypeError
        - If `value` was not given as any of the expected types.
    ValueError
        - If `value` is a `float`, but it is `inf`.
        - If `value` is a `float`, but it is `nan`.
    """
    if isinstance(value, str):
        query_value = value
    elif isinstance(value, int):
        query_value = str(value)
    elif isinstance(value, bool):
        query_value = 'true' if value else 'false'
    elif isinstance(value, NoneType):
        query_value = 'null'
    elif isinstance(value, float):
        if isinf(value):
             raise ValueError('`inf` is not a supported query string parameter value.')
        
        if isnan(value):
            raise ValueError('`nan` is not a supported query string parameter value.')
        
        query_value = str(value)
    
    elif isinstance(value, (list, tuple, set)):
        build_query_list_to(build_to, query_key, value)
        return
    
    else:
        raise TypeError(f'Unexpected value type received when serializing query string, got '
            f'{value.__class__.__name__}; {value!r}.')
    
    query_value = quote(query_value, safe="/?:@", query_string=True)
    
    if build_to:
        build_to.append('&')
    build_to.append(query_key)
    build_to.append('=')
    build_to.append(query_value)


def build_query_list_to(build_to, query_key, query_list):
    """
    Builds a query element from a `list` or `set`.
    
    Parameters
    ----------
    build_to : `list`
        A list to build the query element to.
    query_key : `str`
        An already escaped query key.
    query_list : (`list`, `tuple`, `set`) of (`str`, `int`, `bool`, `NoneType`, `float`, repeat)
        The query string value.
    
    Raises
    -----
    TypeError
        - If `query_list` contains a value with an unexpected type.
    ValueError
        - If `query_list` contains a value as a `float` what it is `inf`.
        - If `query_list` contains a value as a `float` what it is `nan`.
    """
    for value in query_list:
        build_query_element_to(build_to, query_key, value)
