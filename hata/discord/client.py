﻿# -*- coding: utf-8 -*-
__all__ = ('Client', )

import re, sys, warnings
from time import time as time_now
from collections import deque
from os.path import split as splitpath
from threading import current_thread
from math import inf
from datetime import datetime

from ..env import CACHE_USER, CACHE_PRESENCE, API_VERSION
from ..backend.utils import imultidict, methodize, change_on_switch
from ..backend.futures import Future, Task, sleep, CancelledError, WaitTillAll, WaitTillFirst, WaitTillExc, \
    future_or_timeout
from ..backend.eventloop import EventThread, LOOP_TIME
from ..backend.formdata import Formdata
from ..backend.hdrs import AUTHORIZATION
from ..backend.helpers import BasicAuth
from ..backend.url import URL

from .utils import log_time_converter, DISCORD_EPOCH, image_to_base64, random_id, to_json, RelationshipType, \
    get_image_extension
from .user import User, USERS, GuildProfile, UserBase, UserFlag, create_partial_user, GUILD_PROFILES_TYPE
from .emoji import Emoji
from .channel import ChannelCategory, ChannelGuildBase, ChannelPrivate, ChannelText, ChannelGroup, ChannelStore, \
    message_relativeindex, cr_pg_channel_object, MessageIterator, CHANNEL_TYPES, ChannelTextBase, ChannelVoice
from .guild import Guild, create_partial_guild, GuildWidget, GuildFeature, GuildPreview, GuildDiscovery, \
    DiscoveryCategory, COMMUNITY_FEATURES, WelcomeScreen, SystemChannelFlag, VerificationScreen, WelcomeChannel, \
    VerificationScreenStep
from .http import DiscordHTTPClient, URLS
from .http.URLS import VALID_ICON_FORMATS, VALID_ICON_FORMATS_EXTENDED, CDN_ENDPOINT
from .role import Role, PermOW, PERMOW_TYPE_ROLE, PERMOW_TYPE_USER
from .webhook import Webhook, create_partial_webhook
from .gateway import DiscordGateway, DiscordGatewaySharder
from .parsers import EventDescriptor, _with_error, IntentFlag, PARSER_DEFAULTS, InteractionEvent
from .audit_logs import AuditLog, AuditLogIterator
from .invite import Invite
from .message import Message, MessageRepr, MessageReference, Attachment
from .oauth2 import Connection, parse_locale, DEFAULT_LOCALE, OA2Access, UserOA2, Achievement
from .exceptions import DiscordException, DiscordGatewayException, ERROR_CODES, InvalidToken
from .client_core import CLIENTS, KOKORO, GUILDS, DISCOVERY_CATEGORIES, EULAS, CHANNELS
from .voice_client import VoiceClient
from .activity import ActivityUnknown, ActivityBase, ActivityCustom
from .integration import Integration
from .application import Application, Team, EULA
from .ratelimit import RatelimitProxy, RATELIMIT_GROUPS
from .preconverters import preconvert_snowflake, preconvert_str, preconvert_bool, preconvert_discriminator, \
    preconvert_flag, preconvert_preinstanced_type
from .permission import Permission
from .bases import ICON_TYPE_NONE
from .preinstanced import Status, VoiceRegion, ContentFilterLevel, PremiumType, VerificationLevel, \
    MessageNotificationLevel, HypesquadHouse
from .client_utils import SingleUserChunker, MassUserChunker, DiscoveryCategoryRequestCacher, UserGuildPermission, \
    DiscoveryTermRequestCacher, MultiClientMessageDeleteSequenceSharder, WaitForHandler, Typer, maybe_snowflake
from .embed import EmbedBase, EmbedImage
from .interaction import ApplicationCommand, InteractionResponseTypes

from . import client_core as module_client_core, message as module_message, webhook as module_webhook, \
    channel as module_channel, invite as module_invite, parsers as module_parsers, client_utils as module_client_utils,\
    guild as module_guild


_VALID_NAME_CHARS = re.compile('([0-9A-Za-z_]+)')

CHANNEL_MOVE_RESET_INDEXES = tuple(index for index, type_ in enumerate(CHANNEL_TYPES) if \
    (issubclass(type_, ChannelGuildBase) and type_ is not ChannelCategory))


class Client(UserBase):
    """
    Discord client class used to interact with the Discord API.
    
    Attributes
    ----------
    id : `int`
        The client's unique identificator number.
    name : str
        The client's username.
    discriminator : `int`
        The client's discriminator. Given to avoid overlapping names.
    avatar_hash : `int`
        The client's avatar's hash in `uint128`.
    avatar_type : ``Icontype``
        The client's avatar's type.
    guild_profiles : `dict` or ``WeakKeyDictionary`` of (``Guild``, ``GuildProfile``) items
        A dictionary, which contains the client's guild profiles. If a client is member of a guild, then it should
        have a respective guild profile accordingly.
    is_bot : `bool`
        Whether the client is a bot or a user account.
    partial : `bool`
        Partial clients have only their id set. If any other data is set, it might not be in sync with Discord.
    activities : `None` or `list` of ``ActivityBase`` instances
        A list of the client's activities. Defaults to `None`.
    status : `Status`
        The client's display status.
    statuses : `dict` of (`str`, `str`) items
        The client's statuses for each platform.
    email : `None` or `str`
        The client's email.
    flags : ``UserFlag``
        The client's user flags.
    locale : `str`
        The preferred locale by the client.
    mfa : `bool`
        Whether the client has two factor authorization enabled on the account.
    premium_type : ``PremiumType``
        The Nitro subscription type of the client.
    system : `bool`
        Whether the client is an Official Discord System user (part of the urgent message system).
    verified : `bool`
        Whether the email of the client is verified.
    application : ``Application``
        The bot account's application. The application data of the client is requested meanwhile it logs in.
    events : ``EventDescriptor``
        Contains the event handlers of the client. New event handlers can be added through it as well.
    gateway : ``DiscordGateway`` or ``DiscordGatewaySharder``
        The gateway of the client towards Discord. If the client uses sharding, then ``DiscordGatewaySharder`` is used
        as gateway.
    http : ``DiscordHTTPClient``
        The http session of the client. Can be used as a normal http session, or for lower level interactions with the
        Discord API.
    intents : ``IntentFlag``
        The intent flags of the client.
    private_channels : `dict` of (`int`, ``ChannelPrivate``) items
        Stores the private channels of the client. The channels' other recipement' ids are the keys, meanwhile the
        channels are the values.
    group_channels : `dict` of (`int`, ``ChannelGroup``) items
        The group channels of the client. They can be accessed by their id as the key.
    ready_state : ``ReadyState`` or `None`
        The client on login fills up it's ``.ready_state`` with ``Guild`` objects, which will have their members
        requested.
        
        When receiving a `READY` dispatch event, the client's ``.ready_state`` is set as a ``ReadyState`` instance and
        a ``._delay_ready`` task is started, what delays the handleable `ready` event, till every user from the received
        guilds is cached up. When done, ``.ready_state`` is set back to `None`.
    
    relationships : `dict` of (`int`, ``Relationship``) items
        Stores the relationships of the client. The relationships' users' ids are the keys and the relationships
        themselves are the values.
    running : `bool`
        Whether the client is running or not. When the client is stopped, this attribute is set as `False` what causes
        it's heartbeats to stop and it's gateways to close and not reconnect.
    secret : `str`
        The client's secret used when interacting with oauth2 endpoints.
    shard_count : `int`
        The client's shardcount. Set as `0` if the is not using sharding.
    token : `str`
        The client's token.
    voice_clients : `dict` of (`int`, ``VoiceClient``) items
        Each bot can join a channel at every ``Guild`` and meanwhile they do, they have an active voice client for that
        guild. This attribute stores these voice clients. They keys are the guilds' ids, meanwhile the values are
        the voice clients.
    _activity : ``ActivityBase`` instance
        The client's preffered activity.
    _additional_owner_ids : `None` or `set` of `int`
        Additional users' (as id) to be passed by the ``.is_owner`` check.
    _gateway_url : `str`
        Cached up gateway url, what is invalidated after `1` minute. Used to avoid unnecessary requests when launching
        up more shards.
    _gateway_requesting : `bool`
        Whether the client alredy requests it's gateway.
    _gateway_time : `float`
        The last timestamp when ``._gateway_url`` was updated.
    _gateway_max_concurrency : `int`
        The max amount of shards, which can be launched at the same time.
    _gateway_waiter : `None` or ``Future``
        When client gateway is being requested multiple times at the same time, this future is set and awaited at the
        secondary requests.
    _status : ``Status``
        The client's preferred status.
    _user_chunker_nonce : `int`
        The last nonce in int used for requesting guild user chunks. The default value is `0`, what means the next
        request will start at `1`.
        
        Nonce `0` is allocated for the case, when all the guild's users are requested.
    
    Class Attributes
    ----------------
    loop : ``EventThread``
        The eventloop of the client. Every client uses the same one.
    
    See Also
    --------
    - ``UserBase`` : The superclass of ``Client`` and of other user classes.
    - ``User`` : The default type of Discord users.
    - ``Webhook`` : Discord webhook entity.
    - ``WebhookRepr`` : Discord webhook's user representation.
    - ``UserOA2`` : A user class with extended oauth2 attributes.
    
    Notes
    -----
    Client supports weakreferencing and dynamic attribute names as well for extension support.
    """
    __slots__ = (
        'guild_profiles', 'is_bot', 'partial', # default user
        'activities', 'status', 'statuses', # presence
        'email', 'flags', 'locale', 'mfa', 'premium_type', 'system', 'verified', # OAUTH 2
        '__dict__', '_additional_owner_ids', '_activity', '_gateway_requesting', '_gateway_time', '_gateway_url',
        '_gateway_max_concurrency', '_gateway_waiter', '_status', '_user_chunker_nonce', 'application', 'events',
        'gateway', 'http', 'intents', 'private_channels', 'ready_state', 'group_channels', 'relationships', 'running',
        'secret', 'shard_count', 'token', 'voice_clients', )
    
    loop = KOKORO
    
    def __new__(cls, token, *, secret=None, client_id=None, application_id=None, activity=ActivityUnknown, status=None,
            is_bot=True, shard_count=0, intents=-1, additional_owners=None, **kwargs):
        """
        Creates a new ``Client`` instance with the given pramateres.
        
        Parameters
        ----------
        token : `str`
            A valid Discord token, what the client can use to interact with the Discord API.
        secret: `str`, optional
            Client secret used when interacting with oauth2 endpoints.
        client_id : `None`, `int` or `str`, Optional
            The client's `.id`. If passed as `str` will be converted to `int`. Defaults to `None`.
            
            When more `Client` is started up, it is recommended to define their id initially. The wrapper can detect the
            clients' id-s only when they are logging in, so the wrapper  needs to check if a ``User`` alterego of the
            client exists anywhere, and if does will replace it.
        application_id : `None`, `int` or `str`, Optional
            The client's application id. If passed as `str`, will be converterd to `int`. Defaults to `None`.
        activity : ``ActivityBase``, optional
            The client's preferred activity.
        status : `str` or ``Status``, optional
            The client's preferred status.
        is_bot : `bool`, optional
            Whether the client is a bot user or a user account. Defaults to False.
        shard_count : `int`, optional
            The client's shard count. If passed as lower as the recommended one, will reshard itself.
        intents : ``IntentFlag``, optional
             By default the client will launch up using all the intent flags. Negative values will be interpretered as
             using all the intents, meanwhile if passed as positive, non existing intent flags are removed.
        **kwargs : keyword arguments
            Additional predefined attributes for the client.
        
        Other Parameters
        ----------------
        name : `str`, Optional
            The client's ``.name``.
        discriminator : `int` or `str` instance, Optional
            The client's ``.discriminator``. Is accepted as `str` instance as well and will be converted to `int`.
        avatar : `None`, ``Icon`` or `str`, Optional
            The client's avatar. Mutually exclusive with `avatar_type` and `avatar_hash`.
        avatar_type : ``Icontype``, Optional
            The client's avatar's type. Mutually exclusive with `avatar_type`.
        avatar_hash : `int`, Optional
            The client's avatar hash. Mutually exclusive with `avatar`.
        flags : ``UserFlag`` or `int` instance, Optional
            The client's ``.flags``. If not passed as ``UserFlag``, then will be converted to it.
        
        Returns
        -------
        client : ``Client``
        
        Raises
        ------
        TypeError
            If any argument's type is bad or if unexpected argument is passed.
        ValueError
            If an argument's type is good, but it's value is unacceptable.
        """
        # token
        if (type(token) is str):
            pass
        elif isinstance(token, str):
            token = str(token)
        else:
            raise TypeError(f'`token` can be passed as `str` instance, got {token!r}.')
        
        # secret
        if (secret is None) or type(secret is str):
            pass
        elif isinstance(secret, str):
            secret = str(secret)
        else:
            raise TypeError(f'`secret` can be passed as `str` instance, got `{secret.__class__.__name__}`.')
        
        # client_id
        if client_id is None:
            client_id = 0
        else:
            client_id = preconvert_snowflake(client_id, 'client_id')
        
        application = Application._create_empty()
        if (application_id is not None):
            application_id = preconvert_snowflake(application_id, 'application_id')
            application.id = application_id
        
        # activity
        if (not isinstance(activity, ActivityBase)) or (type(activity) is ActivityCustom):
            raise TypeError(f'`activity` should have been passed as `{ActivityBase.__name__} instance (except '
                f'{ActivityCustom.__name__}), got: {activity.__class__.__name__}.')
        
        # status
        if (status is not None):
            status = preconvert_preinstanced_type(status, 'status', Status)
            if status is Status.offline:
                status = Status.invisible
        
        # is_bot
        is_bot = preconvert_bool(is_bot, 'is_bot')
        
        # shard count
        if (type(shard_count) is int):
            pass
        elif isinstance(shard_count, int):
            shard_count = int(shard_count)
        else:
            raise TypeError(f'`shard_count` should have been passed as `int` instance, got '
                f'{shard_count.__class__.__name__}.')
        
        if shard_count<0:
            raise ValueError(f'`shard_count` can be passed only as non negative `int`, got {shard_count!r}.')
        
        # Default to `0`
        if shard_count == 1:
            shard_count = 0
        
        # intents
        intents = preconvert_flag(intents, 'intents', IntentFlag)
        
        # additonal owners
        if additional_owners is None:
            additional_owner_ids = None
        else:
            iter_ = getattr(additional_owners, '__iter__', None)
            if iter_ is None:
                raise TypeError('`additional_owners` should have been passed as `iterable`, got '
                    f'{additional_owners.__class__.__name__}.')
            
            additional_owner_ids = set()
            
            index = 1
            for additional_owner in iter_(additional_owners):
                index += 1
                if not isinstance(additional_owner, (int, UserBase)):
                    raise TypeError(f'User {index} at `additional_owners`  was not passed neither as `int` or as '
                        f'`{UserBase.__name__}` instance, got {additional_owner.__class__.__name__}')
                
                if type(additional_owner) is int:
                    pass
                elif isinstance(additional_owner, int):
                    additional_owner = int(additional_owner)
                else:
                    additional_owner = additional_owner.id
                
                additional_owner_ids.add(additional_owner)
            
            if (not additional_owner_ids):
                additional_owner_ids = None
        
        # kwargs
        if kwargs:
            processable = []
            # kwargs.name
            try:
                name = kwargs.pop('name')
            except KeyError:
                pass
            else:
                name = preconvert_str(name, 'name', 2, 32)
                processable.append(('name', name))
            
            # kwargs.discriminator
            try:
                discriminator = kwargs.pop('discriminator')
            except KeyError:
                pass
            else:
                discriminator = preconvert_discriminator(discriminator)
                processable.append(('discriminator', discriminator))
            
            # kwargs.avatar & kwargs.avatar_type & kwargs.avatar_hash
            cls.avatar.preconvert(kwargs, processable)
            
            # kwargs.flags
            try:
                flags = kwargs.pop('flags')
            except KeyError:
                pass
            else:
                flags = preconvert_flag(flags, 'flags', UserFlag)
                processable.append(('flags', flags))
            
            if kwargs:
                raise TypeError(f'Unused or unsettable attributes: {kwargs}.')
        
        else:
            processable = None
        
        if (status is None):
            _status = Status.online
        else:
            _status = status
        
        self = object.__new__(cls)
        
        self.name = ''
        self.discriminator = 0
        self.avatar_type = ICON_TYPE_NONE
        self.avatar_hash = 0
        self.flags = UserFlag()
        self.mfa = False
        self.system = False
        self.verified = False
        self.email = None
        self.premium_type = PremiumType.none
        self.locale = DEFAULT_LOCALE
        self.token = token
        self.secret = secret
        self.is_bot = is_bot
        self.shard_count = shard_count
        self.intents = intents
        self.running = False
        self.relationships = {}
        self.guild_profiles = GUILD_PROFILES_TYPE()
        self._status = _status
        self.status = Status.offline
        self.statuses = {}
        self._activity = activity
        self.activities = None
        self._additional_owner_ids = additional_owner_ids
        self._gateway_url = ''
        self._gateway_time = -inf
        self._gateway_max_concurrency = 1
        self._gateway_requesting = False
        self._gateway_waiter = None
        self._user_chunker_nonce= 0
        self.group_channels = {}
        self.private_channels = {}
        self.voice_clients = {}
        self.id = client_id
        self.partial = True
        self.ready_state = None
        self.application = application
        self.gateway = (DiscordGatewaySharder if shard_count else DiscordGateway)(self)
        self.http = DiscordHTTPClient(self)
        self.events = EventDescriptor(self)
        
        if (processable is not None):
            for item in processable:
                setattr(self, *item)
        
        CLIENTS.append(self)
        
        if client_id:
            self._maybe_replace_alterego()
        
        return self
    
    def _maybe_replace_alterego(self):
        """
        Replaces the type ``User`` alterego of the client if applicable.
        """
        client_id = self.id
        
        # GOTO
        while True:
            if CACHE_USER:
                try:
                    alterego = USERS[client_id]
                except KeyError:
                    # Go Out
                    break
                else:
                    if alterego is not self:
                        # we already exists, we need to go tru everthing and replace ourself.
                        guild_profiles = alterego.guild_profiles
                        self.guild_profiles = guild_profiles
                        for guild in guild_profiles:
                            guild.users[client_id] = self
            
            # This part should run at both case, except when there is no alterego detected when caching users.
            for client in CLIENTS:
                if (client is self) or (not client.running):
                    continue
                
                for channel in client.group_channels.values():
                    users = channel.users
                    for index in range(len(users)):
                        if users[index].id == client_id:
                            users[index] = self
                            break
                
                for channel in client.private_channels.values():
                    users = channel.users
                    for index in range(len(users)):
                        if users[index].id == client_id:
                            users[index] = self
                            break
            
            break
        
        USERS[client_id] = self
    
    def _init_on_ready(self, data):
        """
        Fills up the client's instance attributes on login. If there is an already existing User object with the same
        id, the client will replace it at channel participans, at ``USERS`` weakreference dictionary, at
        ``guild.users``. This replacing is avoidable, if at the creation of the client the ``.client_id`` argument is
        set.
        
        Parameters
        ----------
        data : `dict` of (`str`, `Any`) items
            Data requested from Discord by the ``.client_login_static`` method.
        """
        client_id = int(data['id'])
        if self.id != client_id:
            CLIENTS.update(self, client_id)
        
        self._maybe_replace_alterego()
        
        self.name = data['username']
        self.discriminator = int(data['discriminator'])
        self._set_avatar(data)
        self.mfa = data.get('mfa_enabled', False)
        self.system = data.get('system', False)
        self.verified = data.get('verified', False)
        self.email = data.get('email')
        self.flags = UserFlag(data.get('flags', 0))
        self.premium_type = PremiumType.get(data.get('premium_type', 0))
        self.locale = parse_locale(data)
        
        self.partial = False
    
    _update_presence = User._update_presence
    _update_presence_no_return = User._update_presence_no_return
    
    
    @property
    def _platform(self):
        """
        Returns the client's local platform.
        
        Returns
        -------
        platform : `str`
            The platform's name or empty string if the client's status is offline or invisible.
            
        Notes
        -----
        Custom client's status is always `'web'`, so other than `''` or `'web'` will not be returned.
        """
        if self.status in (Status.offline, Status.invisible):
            return ''
        return 'web'
    
    def _delete(self):
        """
        Cleares up the client's references. By default this is not called when a client is stopped. This method should
        be used when you want to get rid of every allocated objects by the client. Take care, local modules might still
        have active references to the client or to some other objects, what could cause them to not garbage collect.
        
        Raises
        ------
        RuntimeError
            If called when the client is still running.
        
        Examples
        --------
        ```
        >>> from hata import Client, GUILDS
        >>> import gc
        >>> TOKEN = 'a token goes here'
        >>> client = Client(TOKEN)
        >>> client.start()
        >>> len(GUILDS)
        4
        >>> client.stop()
        >>> client._delete()
        >>> client = None
        >>> gc.collect()
        680
        >>> len(GUILDS)
        0
        ```
        """
        if self.running:
            raise RuntimeError(f'{self.__class__.__name__}._delete called from a running client.')
        
        CLIENTS.remove(self)
        client_id = self.id
        alterego = object.__new__(User)
        for attrname in User.__slots__:
            if attrname.startswith('__'):
                continue
            setattr(alterego, attrname, getattr(self, attrname))
        
        if CACHE_USER:
            USERS[client_id] = alterego
            guild_profiles = self.guild_profiles
            for guild in guild_profiles:
                guild.users[client_id] = self
            
            for client in CLIENTS:
                if (client is not self) and client.running:
                    for relationship in client.relationships:
                        if relationship.user is self:
                            relationship.user = alterego
        
        else:
            try:
                del USERS[client_id]
            except KeyError:
                pass
            guild_profiles = self.guild_profiles
            for guild in guild_profiles:
                try:
                    del guild[client_id]
                except KeyError:
                    pass
        
        self.relationships.clear()
        for channel in self.group_channels.values():
            users = channel.users
            for index in range(users):
                if users[index].id == client_id:
                    users[index] = alterego
                    continue
        
        self.private_channels.clear()
        self.group_channels.clear()
        self.events.clear()
        
        self.guild_profiles = GUILD_PROFILES_TYPE()
        self.status = Status.offline
        self.statuses = {}
        self._activity = ActivityUnknown
        self.activities = None
        self.ready_state = None
    
    async def download_url(self, url):
        """
        Requests an url and returns the response's content. A shortcut option for doing a get request with the
        client's http and reading it.
        
        This method is a coroutine.
        
        Parameters
        ----------
        url : `str` or ``URL`` instance
            The url to request.

        Returns
        -------
        response_data : `bytes`
        
        Raises
        ------
        AssertionError
            If `url` was not given as `str`, nor ``URL`` instance.
        ConnectionError
            No internet connection.
        """
        if __debug__:
            if not isinstance(url, (str, URL)):
                raise AssertionError(f'`url` can be given as `str` or `{URL.__name__}` instance, got '
                    f'{url.__class__.__name__}.')
        
        async with self.http.get(url) as response:
            return (await response.read())
    
    async def download_attachment(self, attachment):
        """
        Downloads an attachment object's file. This method always prefers the proxy url of the attachment if applicable.
        
        This method is a coroutine.
        
        Parameters
        ----------
        attachment : ``Attachment`` or ``EmbedImage``
            The attachment object, which's file will be requested.
        
        Returns
        -------
        response_data : `bytes`
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            If `attachment` was not given as ``Attachment`` nor ``EmbedImage`` instance.
        """
        if __debug__:
            if not isinstance(attachment, (Attachment, EmbedImage)):
                raise AssertionError(f'`attachment` can be given as `{Attachment.__name__}` or `{EmbedImage.__name__}` '
                    f'instance, got {attachment.__class__.__name__}.')
        
        url = attachment.proxy_url
        if (url is None) or (not url.startswith(CDN_ENDPOINT)):
            url = attachment.url
        
        async with self.http.get(url) as response:
            return (await response.read())
    
    
    async def client_edit(self, *, name=None, avatar=..., password=None, new_password=None, email=None, house=...):
        """
        Edits the client. Only the provided parameters will be changed. Every argument what refers to a user
        account is not tested.
        
        This method is a coroutine.
        
        Parameters
        ----------
        name : `str`, Optional
            The client's new name.
        avatar : `bytes-like` or `None`, Optional
            An `'jpg'`, `'png'`, `'webp'` image's raw data. If the client is premium account, then it can be
            `'gif'` as well. By passing `None` you can remove the client's current avatar.
        password : `str`, Optional
            The actual password of the client.
        new_password : `str`, Optional
            The client's new password.
        email : `str`, Optional
            The client's new email.
        house : `int`, ``HypesquadHouse`` or `None`, Optional
            Remove or change the client's hypesquad house.
        
        Raises
        ------
        TypeError
            - If `avatar` was not given as `None`, neither as `bytes-like`.
            - If `house` was not given as `int`  neither as ``HypesquadHouse`` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            - If `name` was given but not as `str` instance.
            - If `name`'s length is out of range [2:32].
            - If `avatar`'s type in unsettable for the client.
            - If password was not given meanwhile the client is not bot.
            - If password was not given as `str` instance.
            - If `email` was given, but nto as `str` instance.
            - If `new_password` was given, but nto as `str` instance.
        
        Notes
        -----
        The method's endpoint has long ratelimit reset, so consider using timeout and checking ratelimits with
        ``RatelimitProxy``.
        
        The `password`, `new_password`, `email` and the `house` parameters are only for user accounts.
        """
        data = {}
        
        if (name is not None):
            if __debug__:
                if not isinstance(name, str):
                    raise AssertionError(f'`name` can be given as `str` instance, got {name.__class__.__name__}.')
                
                name_ln = len(name)
                if name_ln < 2 or name_ln > 32:
                    raise AssertionError(f'The length of the name can be in range [2:32], got {name_ln}; {name!r}.')
            
            data['username'] = name
        
        
        if (avatar is not ...):
            if avatar is None:
                avatar_data = None
            else:
                if not isinstance(avatar, (bytes, bytearray, memoryview)):
                    raise TypeError(f'`avatar` can be passed as `bytes-like` or None, got {avatar.__class__.__name__}.')
                
                if __debug__:
                    extension = get_image_extension(avatar)
                    
                    if self.premium_type.value:
                        valid_icon_types = VALID_ICON_FORMATS_EXTENDED
                    else:
                        valid_icon_types = VALID_ICON_FORMATS
                    
                    if extension not in valid_icon_types:
                        raise AssertionError(f'Invalid avatar type for the client: `{extension}`.')
                
                avatar_data = image_to_base64(avatar)
            
            data['avatar'] = avatar_data
        
        
        if not self.is_bot:
            if __debug__:
                if password is None:
                    raise AssertionError(f'`password` is must for non bots!')
                
                if not isinstance(password, str):
                    raise AssertionError('`password` can be passed as `str` instance, got '
                        f'{password.__class__.__name__}.')
            
            data['password'] = password
            
            
            if (email is not None):
                if __debug__:
                    if not isinstance(email, str):
                        raise AssertionError(f'`email` can be given as `str` instance, got {email.__class__.__name__}.')
                
                data['email'] = email
            
            
            if (new_password is not None):
                if __debug__:
                    if not isinstance(new_password, str):
                        raise AssertionError('`new_password` can be passed as `str` instance, got '
                            f'{new_password.__class__.__name__}.')
                
                data['new_password'] = new_password
            
            
            if house is not ...:
                if house is None:
                    await self.hypesquad_house_leave()
                else:
                    await self.hypesquad_house_change(house)
        
        
        data = await self.http.client_edit(data)
        self._update_no_return(data)
        
        
        if not self.is_bot:
            self.email = data['email']
            try:
                token = data['token']
            except KeyError:
                pass
            else:
                self.token = token
    
    async def client_edit_nick(self, guild, nick, *, reason=None):
        """
        Changes the client's nick at the specified Guild. A nick name's length can be between 1-32. An extra argument
        reason is accepted as well, what will show zp at the respective guild's audit logs.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : `None`, `int` or ``Guild``instance
            The guild where the client's nickname will be changed. If `guild` is given as `None`, then the function
            returns instantly.
        nick : `str` or `None`
            The client's new nickname. Pass it as `None` to remove it. Empty strings are interpretered as `None`.
        reason : `None` or `str`, Optional
            Will show up at the respective guild's audit logs.
        
        Raises
        ------
        TypeError
            - `guild` was not given neither as ``GUild`` or `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            - If the nick's length is over `32`.
            - If the nick was not given neither as `None` or `str` instance.
        Notes
        -----
        No request is done if the client's actual nickname at the guild is same as the method would change it too.
        """
        if guild is None:
            # Canned edit nick in private, ignore it
            return
        
        if isinstance(guild, Guild):
            guild_id = guild.id
        else:
            guild_id = maybe_snowflake(guild)
            if guild_id is None:
                raise TypeError(f'`guild` can be given as `{Guild.__name__}` or `int` instance, got '
                    f'{guild.__class__.__name__}.')
            
            guild = GUILDS.get(guild_id)
        
        # Security debug checks.
        if __debug__:
            if (nick is not None):
                if not isinstance(nick, str):
                    raise AssertionError(f'`nick` can be given as `None` or `str` instance, got '
                        f'{nick.__class__.__name__}.')
                
                nick_ln = len(nick)
                if nick_ln > 32:
                    raise AssertionError(f'`nick` length can be in range [1:32], got {nick_ln}; {nick!r}.')
                
                # Translate empty nick to `None`
                if nick_ln == 0:
                    nick = None
        else:
            # Non debug mode: Translate empty nick to `None`
            if (nick is not None) and (not nick):
                nick = None
        
        
        # Check whether we should edit the nick.
        if guild is None:
            # `guild` can be `None` if `guild` parameter was given as `int`.
            should_edit_nick = True
        else:
            try:
                guild_profile = self.guild_profiles[guild]
            except KeyError:
                # we arent at the guild probably ->  will raise the request for us, if really
                should_edit_nick = True
            else:
                should_edit_nick = (guild_profile.nick != nick)
        
        if should_edit_nick:
            await self.http.client_edit_nick(guild_id, {'nick': nick}, reason)
    
    async def client_connections(self):
        """
        Requests the client's connections.
        
        This method is a coroutine.
        
        Returns
        -------
        connections : `list` of ``Connection`` objects
        
        Raises
        ------
        ConnectionError
            No internet connection.
        
        Notes
        -----
        For a bot account this request will always return an empty list.
        """
        data = await self.http.client_connections()
        return [Connection(connection_data) for connection_data in data]
    
    async def client_edit_presence(self, *, activity=..., status=None, afk=False):
        """
        Changes the client's presence (status and activity). If a parameter is not defined, it will not be changed.
        
        This method is a coroutine.
        
        Parameters
        ----------
        activity : ``ActivityBase`` instance, Optional
            The new activity of the Client.
        status : `str` or ``Status``, Optional
            The new status of the client.
        afk : `bool`, Optional
            Whether the client is afk or not (?). Defaults to `False`.
        
        Raises
        ------
        TypeError:
            - If the status is not `str` or ``Status`` instance.
            - If activity is not ``ActivityBase`` instance, except ``ActivityCustom``.
        ValueError:
            - If the status `str` instance, but not any of the predefined ones.
        AssertionError
            - `afk` was not given as `int` instance.
        """
        if status is None:
            status = self._status
        else:
            status = preconvert_preinstanced_type(status, 'status', Status)
            self._status = status
        
        status = status.value
        
        if activity is ...:
            activity = self._activity
        elif activity is None:
            self._activity = ActivityUnknown
        elif isinstance(activity, ActivityBase) and (not isinstance(activity, ActivityCustom)):
            self._activity = activity
        else:
            raise TypeError(f'`activity` should have been passed as `{ActivityBase.__name__} instance (except '
                f'{ActivityCustom.__name__}), got: {activity.__class__.__name__}.')
        
        if activity is None:
            pass
        elif activity is ActivityUnknown:
            activity = None
        else:
            if self.is_bot:
                activity = activity.botdict()
            else:
                activity = activity.hoomandict()
        
        if status == 'idle':
            since = int(time_now()*1000.)
        else:
            since = 0.0
        
        if __debug__:
            if not isinstance(afk, bool):
                raise AssertionError(f'`afk` can be given as `bool` instance, got {afk.__class__.__name__}.')
        
        data = {
            'op': DiscordGateway.PRESENCE,
            'd' : {
                'game'  : activity,
                'since' : since,
                'status': status,
                'afk'   : afk,
                    },
                }
        
        await self.gateway.send_as_json(data)
    
    async def activate_authorization_code(self, redirect_url, code, scopes):
        """
        Activates a user's oauth2 code.
        
        This method is a coroutine.
        
        Parameters
        ----------
        redirect_url : `str`
            The url, where the activation page redirected to.
        code : `str`
            The code, what is included with the redirect url after a successfull activation.
        scopes : `str` or `list` of `str`
            Scope or a  list of oauth2 scopes to request.
        
        Returns
        -------
        access : ``OA2Access`` or `None`
            If the code, the redirect url or the scopes are invalid, the methods returns `None`.
        
        Raises
        ------
        TypeError
            If `Scopes` wasnt neither as `str` not `list` of `str` instances.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            - If `redirect_url` was not given as `str` instance.
            - If `code` was not given as `str` instance.
            - If `scopes` is empty.
            - If `scopes` contains empty string.
        
        See Also
        --------
        ``parse_oauth2_redirect_url`` : Parses `redirect_url` and the `code` from a full url.
        """
        if __debug__:
            if not isinstance(redirect_url, str):
                raise AssertionError(f'`redirect_url` can be given as `str` instance, got '
                    f'{redirect_url.__class__.__name__}.')
            
            if not isinstance(code, str):
                raise AssertionError(f'`code` can be given as `str` instance, got {code.__class__.__name__}.')
        
        if isinstance(scopes, str):
            if __debug__:
                if not scopes:
                    raise AssertionError(f'`scopes` was given as an empty string.')
        
        elif isinstance(scopes, list):
            if __debug__:
                if not scopes:
                    raise AssertionError(f'`scopes` cannot be empty.')
                
                for index, scope in enumerate(scopes):
                    if not isinstance(scope, str):
                        raise AssertionError(f'`scopes` element `{index}` is not `str` instance, but '
                            f'{scope.__class__.__name__}; got {scopes!r}.')
                    
                    if not scope:
                        raise AssertionError(f'`scopes` element `{index}` is an empty string; got {scopes!r}.')
            
            scopes = ' '.join(scopes)
        
        else:
            raise TypeError(f'`scopes` can be given as `str` or `list` of `str` instances, got '
                f'{scopes.__class__.__name__}; {scopes!r}.')
        
        data = {
            'client_id'     : self.id,
            'client_secret' : self.secret,
            'grant_type'    : 'authorization_code',
            'code'          : code,
            'redirect_uri'  : redirect_url,
            'scope'         : scopes,
                }
        
        data = await self.http.oauth2_token(data, imultidict())
        if len(data) == 1:
            return
        
        return OA2Access(data, redirect_url)
    
    async def owners_access(self, scopes):
        """
        Similar to ``.activate_authorization_code``, but it requests the application's owner's access. It does not
        requires the redirect_url and the code argument either.
        
        This method is a coroutine.
        
        Parameters
        ----------
        scopes : `list` of `str`
            A list of oauth2 scopes to request.
        
        Returns
        -------
        access : ``OA2Access``
            The oauth2 access of the client's application's owner.
        
        Raises
        ------
        TypeError
            If `Scopes` wasnt neither as `str` not `list` of `str` instances.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            - If `redirect_url` was not given as `str` instance.
            - If `code` was not given as `str` instance.
            - If `scopes` is empty.
            - If `scopes` contains empty string.
        
        Notes
        -----
        Does not work if the client's application is owned by a team.
        """
        if isinstance(scopes, str):
            if __debug__:
                if not scopes:
                    raise AssertionError(f'`scopes` was given as an empty string.')
        
        elif isinstance(scopes, list):
            if __debug__:
                if not scopes:
                    raise AssertionError(f'`scopes` cannot be empty.')
                
                for index, scope in enumerate(scopes):
                    if not isinstance(scope, str):
                        raise AssertionError(f'`scopes` element `{index}` is not `str` instance, but '
                            f'{scope.__class__.__name__}; got {scopes!r}.')
                    
                    if not scope:
                        raise AssertionError(f'`scopes` element `{index}` is an empty string; got {scopes!r}.')
            
            scopes = ' '.join(scopes)
        
        else:
            raise TypeError(f'`scopes` can be given as `str` or `list` of `str` instances, got '
                f'{scopes.__class__.__name__}; {scopes!r}.')
        
        data = {
            'grant_type' : 'client_credentials',
            'scope'      : scopes,
                }
        
        headers = imultidict()
        headers[AUTHORIZATION] = BasicAuth(str(self.id), self.secret).encode()
        data = await self.http.oauth2_token(data, headers)
        return OA2Access(data, '')
    
    
    async def user_info(self, *args, **kwargs):
        """
        Deprecated, please use ``.get_user_info`` instead. Will be removed in 2021 february.
        
        This method is a coroutine.
        """
        warnings.warn(
            '`Client.user_info` is deprecated, and will be removed in 2021 february. '
            'Please use `Client.get_user_info` instead.',
            FutureWarning)
        
        return await self.get_user_info(*args, **kwargs)
    
    async def get_user_info(self, access):
        """
        Request the a user's information with oauth2 access token. By default a bot account should be able to request
        every public infomation about a user (but you do not need oauth2 for that). If the access token has email
        or/and identify scopes, then more information should show up like this.
        
        This method is a coroutine.
        
        Parameters
        ----------
        access : ``OA2Access``, ``UserOA2`` or `str` instance
            Oauth2 acess to the respective user or it's access token.
        
        Returns
        -------
        oauth2_user : ``UserOA2``
            The requested user object.
        
        Raises
        ------
        TypeError
            If `access` was not given neither as ``OA2Access``, ``UserOA2``  or `str` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        
        Notes
        -----
        Needs `'email'` or / and `'identify'` scopes granted for more data
        """
        if isinstance(access, (OA2Access, UserOA2)):
            access_token = access.access_token
        elif isinstance(access, str):
            access_token = access
        else:
            raise TypeError(f'`access` can be given as `{OA2Access.__name__}`, `{UserOA2.__name__}` or `str`'
                f'instance, but got {access.__class__.__name__}.')
        
        headers = imultidict()
        headers[AUTHORIZATION] = f'Bearer {access_token}'
        data = await self.http.get_user_info(headers)
        return UserOA2(data, access)
    
    
    async def user_connections(self, access):
        """
        Requests a user's connections. This method will work only if the access token has the `'connections'` scope. At
        the returned list includes the user's hidden connections as well.
        
        This method is a coroutine.
        
        Parameters
        ----------
        access : ``OA2Access``, ``UserOA2`` or `str` instance
            Oauth2 acess to the respective user or it's access token.
        
        Returns
        -------
        connections : `list` of ``Connection``
            The user's connections.
        
        Raises
        ------
        TypeError
            If `access` was not given neither as ``OA2Access``, ``UserOA2``  or `str` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            If the given `access` not grants `'connections'` scope.
        """
        if isinstance(access, (OA2Access, UserOA2)):
            if __debug__:
                if 'connections' not in access.scopes:
                    raise AssertionError(f'The given `access` not grants `\'connections\'` scope, what is required, '
                        f'got {access!r}.')
            
            access_token = access.access_token
        elif isinstance(access, str):
            access_token = access
        else:
            raise TypeError(f'`access` can be given as `{OA2Access.__name__}`, `{UserOA2.__name__}` or `str`'
                f'instance, but got {access.__class__.__name__}.')
        
        headers = imultidict()
        headers[AUTHORIZATION] = f'Bearer {access_token}'
        data = await self.http.user_connections(headers)
        return [Connection(connection_data) for connection_data in data]
    
    
    async def renew_access_token(self, access):
        """
        Renews the access token of an ``OA2Access``.
        
        This method is a coroutine.
        
        Parameters
        ----------
        access : ``OA2Access`` or ``UserOA2``
            Oauth2 acess to the respective user.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            If `access` was not given neither as ``OA2Access`` or ``UserOA2`` instance.
        
        Notes
        -----
        By default access tokens expire after one week.
        """
        if __debug__:
            if not isinstance(access, (OA2Access, UserOA2)):
                raise AssertionError(f'`access` can be given as `{OA2Access.__name__}` or `{UserOA2.__name__}` '
                    f'instance, but got {access.__class__.__name__}.')
        
        redirect_url = access.redirect_url
        if redirect_url:
            data = {
                'client_id'     : self.id,
                'client_secret' : self.secret,
                'grant_type'    : 'refresh_token',
                'refresh_token' : access.refresh_token,
                'redirect_uri'  : redirect_url,
                'scope'         : ' '.join(access.scopes)
                    }
        else:
            data = {
                'client_id'     : self.id,
                'client_secret' : self.secret,
                'grant_type'    : 'client_credentials',
                'scope'         : ' '.join(access.scopes),
                    }
        
        data = await self.http.oauth2_token(data, imultidict())
        
        access._renew(data)
    
    async def guild_user_add(self, guild, access, user=None, *, nick=None, roles=None, mute=False, deaf=False):
        """
        Adds the passed to the guild. The user must have granted you the `'guilds.join'` oauth2 scope.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild`` or `int`
            The guild, where the user is going to be added.
        access: ``OA2Access``, ``UserOA2`` or `str` instance
            The access of the user, who will be addded.
        user : ``Client``, ``User`` or `int` Optional
            Defines which user will be added to the guild. The `access` must refer to this specified user.
            
            This field is optional if access is passed as an ``UserOA2`` object.
        nick : `str`, Optional
            The nickname, which with the user will be added.
        roles : `None` or `list` of (``Role`` or `int`, Optional
            The roles to add the user with.
        mute : `bool`, Optional
            Whether the user should be added as muted.
        deaf : `bool`, Optional
            Whether the user should be added as deafen.
        
        Raises
        ------
        TypeError:
            - If `user` was not given neither as `None`, ``User``, ``Client`` or `int` instance.
            - If `user` was passed as `None` and `access` was passed as ``OA2Access`` or as `str` instance.
            - If `access` was not given as ``OA2Access``, ``UserOA2``, nether as `str` instance.
            - If the given `acess` not grants `'guilds.join'` scope.
            - If `guild` was not given neither as ``Guild``, not `int` instance.
            - If `roles` contain not ``Role``, nor `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            - If `user` and `access` refers to a different user.
            - If the nick's length is over `32`.
            - If the nick was not given neither as `None` or `str` instance.
            - If `mute` was not given as `bool` instance.
            - If `deaf` was not given as `bool` instance.
            - If `roles` was not given neither as `None` or `list`.
        """
        if user is None:
            user_id = 0
        elif isinstance(user, (User, Client)):
            user_id = user.id
        else:
            user_id = maybe_snowflake(user)
            if user_id is None:
                raise TypeError(f'`user` can be given as `None`, `{User.__name__}`, `{Client.__name__}` or `int` '
                    f'instance, got {user.__class__.__name__}.')
        
        
        if isinstance(access, OA2Access):
            access_token = access.access_token
            
            if __debug__:
                if 'guilds.join' not in access.scopes:
                    raise AssertionError(f'The given `access` not grants `\'guilds.join\'` scope, what is required, '
                        f'got {access!r}.')
        
        elif isinstance(access, UserOA2):
            access_token = access.access_token
            if __debug__:
                if 'guilds.join' not in access.scopes:
                    raise AssertionError(f'The given `access` not grants `\'guilds.join\'` scope, what is required, '
                        f'got {scope!r}.')
                
                if user_id and (user_id != access.id):
                    raise AssertionError(f'The given `user` and `access` refers to different users, got user={user!r}, '
                        f'access={access!r}.')
            
            user_id = access.id
        elif isinstance(access, str):
            access_token = access
        else:
            raise TypeError(f'`access` can be given as `{OA2Access.__name__}`, `{UserOA2.__name__}` or `str`'
                f'instance, but got {access.__class__.__name__}.')
        
        
        if not user_id:
            raise TypeError(f'`user` was not detectable neither from `user` nor from `access` parameters, got '
                f'user={user!r}, access={access!r}.')
        
        
        if isinstance(guild, Guild):
            guild_id = guild.id
        else:
            guild_id = maybe_snowflake(guild)
            if guild_id is None:
                raise TypeError(f'`guild` can be given as `{Guild.__name__}` or `int` instance, got '
                    f'{guild.__class__.__name__}.')
        
        
        data = {'access_token': access_token}
        
        
        # Security debug checks.
        if __debug__:
            if (nick is not None):
                if not isinstance(nick, str):
                    raise AssertionError(f'`nick` can be given as `None` or `str` instance, got '
                        f'{nick.__class__.__name__}.')
                
                nick_ln = len(nick)
                if nick_ln > 32:
                    raise AssertionError(f'`nick` length can be in range [0:32], got {nick_ln}; {nick!r}.')
        
        if (nick is not None) and nick:
            data['nick'] = nick
        
        
        if (roles is not None):
            if __debug__:
                if not isinstance(roles, list):
                    raise AssertionError(f'`roles` can be given as `list` or `{Role.__name__}` instances, got '
                        f'{roles.__class__.__name__}.')
            
            if roles:
                role_ids = []
                
                for index, role in enumerate(roles):
                    if isinstance(role, Role):
                        role_id = role.id
                    else:
                        role_id = maybe_snowflake(role)
                        if role_id is None:
                            raise TypeError(f'`roles` element `{index}` is not `{Role.__name__}`, neither `int` '
                                f'instance,  but{role.__class__.__name__}; got {roles!r}.')
                    
                    role_ids.append(role_id)
                
                data['roles'] = role_ids
        
        
        if __debug__:
            if not isinstance(mute, bool):
                raise AssertionError(f'`mute` can be given as `bool` instance, got {mute.__class__.__name__}.')
        
        if mute:
            data['mute'] = mute
        
        
        if __debug__:
            if not isinstance(deaf, bool):
                raise AssertionError(f'`deaf` can be given as `bool` instance, got {deaf.__class__.__name__}.')
        
        if deaf:
            data['deaf'] = deaf
        
        
        await self.http.guild_user_add(guild_id, user_id, data)
    
    async def user_guilds(self, access):
        """
        Requests a user's guilds with it's ``OA2Access``. The user must provide the `'guilds'` oauth2  scope for this
        request to succeed.
        
        This method is a coroutine.
        
        Parameters
        ----------
        access: ``OA2Access``, ``UserOA2`` or `str` instance
            The access of the user, who's guilds will be requested.
        
        Returns
        -------
        guilds_and_permissions : `list` of `tuple` (``Guild``, ``UserGuildPermission``)
            The guilds and the user's permissions in each of them. Not loaded guilds will show up as partial ones.
        
        Raises
        ------
        TypeError
            If `access` was not given neither as ``OA2Access``, ``UserOA2``  or `str` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            If the given `access` not grants `'guilds'` scope.
        """
        if isinstance(access, (OA2Access, UserOA2)):
            if __debug__:
                if 'connections' not in access.scopes:
                    raise AssertionError(f'The given `access` not grants `\'guilds\'` scope, what is required, '
                        f'got {access!r}.')
            
            access_token = access.access_token
        elif isinstance(access, str):
            access_token = access
        else:
            raise TypeError(f'`access` can be given as `{OA2Access.__name__}`, `{UserOA2.__name__}` or `str`'
                f'instance, but got {access.__class__.__name__}.')
        
        headers = imultidict()
        headers[AUTHORIZATION] = f'Bearer {access_token}'
        data = await self.http.user_guilds(headers)
        return [(create_partial_guild(guild_data), UserGuildPermission(guild_data)) for guild_data in data]
    
    async def achievement_get_all(self):
        """
        Requests all the achievements of the client's application and returns them.
        
        This method is a coroutine.
        
        Returns
        -------
        achievements : `list` of ``Achievement`` objects
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        data = await self.http.achievement_get_all(self.application.id)
        return [Achievement(achievement_data) for achievement_data in data]
    
    async def achievement_get(self, achievement_id):
        """
        Requests one of the client's achievements by it's id.
        
        This method is a coroutine.
        
        Parameters
        ----------
        achievement_id : `int`
            The achievement's id.
        
        Returns
        -------
        achievement : ``Achievement``
        
        Raises
        ------
        TypeError
            If `achievement_id` was not given as `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        achievement_id_c = maybe_snowflake(achievement_id)
        if achievement_id_c is None:
            raise TypeError(f'`achievement_id` can be given as `int` instance, got '
                f'{achievement_id.__class__.__name__}.')
        
        data = await self.http.achievement_get(self.application.id, achievement_id_c)
        return Achievement(data)
    
    async def achievement_create(self, name, description, icon, secret=False, secure=False):
        """
        Creates an achievment for the client's application and returns it.
        
        This method is a coroutine.
        
        Parameters
        ----------
        name : `str`
            The achievement's name.
        description : `str`
            The achievement's description.
        icon : `bytes-like`
            The achievement's icon. Can have `'jpg'`, `'png'`, `'webp'` or `'gif'` format.
        secret : `bool`, Optional
            Secret achievements will *not* be shown to the user until they've unlocked them.
        secure : `bool`, Optional
            Secure achievements can only be set via HTTP calls from your server, not by a game client using the SDK.
        
        Returns
        -------
        achievement : ``Achievement``
            The created achievement entity.
        
        Raises
        ------
        TypeError
            If `icon` was not passed as `bytes-like`.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            - If the `icon`'s format is not any of the expected ones.
            - If `name` was not given as `str` instance.
            - If `description` was not gvein as `str` instance.
            - If `secret` was not given as `bool` instance.
            - If `secure` was not given as `bool` instance.
        """
        if __debug__:
            if not isinstance(name, str):
                raise AssertionError(f'`name` can be given as `str` instance, got {name.__class__.__name__}.')
            
            if not isinstance(description, str):
                raise AssertionError(f'`description` can be given as `str` instance, got '
                    f'{description.__class__.__name__}.')
        
        if not isinstance(icon, (bytes, bytearray, memoryview)):
            raise TypeError(f'`icon` can be passed as `bytes-like`, got {icon.__class__.__name__}.')
        
        if __debug__:
            extension = get_image_extension(icon)
            if extension not in VALID_ICON_FORMATS_EXTENDED:
                raise AssertionError(f'Invalid icon type for achievement: `{extension}`.')
        
        icon_data = image_to_base64(icon)
        
        if __debug__:
            if not isinstance(secret, bool):
                raise AssertionError(f'`secret` can be given as `bool` instance, got {secret.__class__.__name__}.')
            
            if not isinstance(secure, bool):
                raise AssertionError(f'`secure` can be given as `bool` instance, got {secure.__class__.__name__}.')
        
        data = {
            'name' : {
                'default' : name,
                    },
            'description' : {
                'default' : description,
                    },
            'secret' : secret,
            'secure' : secure,
            'icon'   : icon_data,
                }
        
        data = await self.http.achievement_create(self.application.id, data)
        return Achievement(data)
    
    async def achievement_edit(self, achievement, name=None, description=None, secret=None, secure=None, icon=None):
        """
        Edits the passed achievemnt with the specified parameters. All parameter is optional.
        
        This method is a coroutine.
        
        Parameters
        ----------
        achievement : ``Achievement`` or `int` instance
            The achievement, what will be edited.
        name : `str`, Optional
            The new name of the achievement.
        description : `str`, Optional
            The achievemnt's new description.
        secret : `bool`, Optional
            The achievement's new secret value.
        secure : `bool`, Optional
            The achievement's new secure value.
        icon : `bytes-like`, Optional
            The achievement's new icon.
        
        Returns
        -------
        achievement : ``Achievement``
            After a successful edit, the passed achievement is updated and returned.
        
        Raises
        ------
        TypeError
            - If ``icon`` was not passed as `bytes-like`.
            - If `achievement` was not given neither as ``Achievement``, neither as `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            - If `name` was not given as `str` instance.
            - If `description` was not given as `str` instance.
            - If `secret` was not given as `bool` instance.
            - If `secure` was not given as `str` instance.
            - If `icon`'s format is not any of the expected ones.
        """
        if isinstance(achievement, Achievement):
            achievement_id = achievement.id
        else:
            achievement_id = maybe_snowflake(achievement)
            if achievement_id is None:
                raise TypeError(f'`achievement` can be given as `int` instance, got {achievement.__class__.__name__}.')
            
            achievement = None
        
        data = {}
        
        if (name is not None):
            if __debug__:
                if not isinstance(name, str):
                    raise AssertionError(f'`name` can be given as `str` instance, got {name.__class__.__name__}.')
            
            data['name'] = {
                'default' : name,
                    }
        
        if (description is not None):
            if __debug__:
                if not isinstance(description, str):
                    raise AssertionError(f'`description` can be given as `str` instance, got '
                        f'{description.__class__.__name__}.')
            
            data['description'] = {
                'default' : description,
                    }
        
        if (secret is not None):
            if __debug__:
                if not isinstance(secret, bool):
                    raise AssertionError(f'`secret` can be given as `bool` instance, got {secret.__class__.__name__}.')
            
            data['secret'] = secret
        
        if (secure is not None):
            if __debug__:
                if not isinstance(secret, bool):
                    raise AssertionError(f'`secret` can be given as `bool` instance, got {secret.__class__.__name__}.')
            
            data['secure'] = secure
        
        if (icon is not None):
            icon_type = icon.__class__
            if not isinstance(icon, (bytes, bytearray, memoryview)):
                raise TypeError(f'`icon` can be passed as `bytes-like`, got {icon_type.__name__}.')
            
            if __debug__:
                extension = get_image_extension(icon)
                if extension not in VALID_ICON_FORMATS_EXTENDED:
                    raise ValueError(f'Invalid icon type for achievemen: `{extension}`.')
            
            data['icon'] = image_to_base64(icon)
        
        data = await self.http.achievement_edit(self.application.id, achievement_id, data)
        if achievement is None:
            achievement = Achievement(data)
        else:
            achievement._update_no_return(data)
        return achievement
    
    async def achievement_delete(self, achievement):
        """
        Deletes the passed achievement.
        
        This method is a coroutine.
        
        Parameters
        ----------
        achievement : ``Achievement`` or `int`
            The achievement to delete.
        
        Raises
        ------
        TypeError
            If `achievement` was not given neither as ``Achievement``, neither as `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        if isinstance(achievement, Achievement):
            achievement_id = achievement.id
        else:
            achievement_id = maybe_snowflake(achievement)
            if achievement_id is None:
                raise TypeError(f'`achievement` can be given as `{Achievement.__name__}` or `int` instance, got '
                    f'{achievement.__class__.__name__}.')
        
        await self.http.achievement_delete(self.application.id, achievement_id)
    
    
    async def user_achievements(self, access):
        """
        Requests the achievements of a user with it's oauth2 access.
        
        This method is a coroutine.
        
        Parameters
        ----------
        access : ``OA2Access``, ``UserOA2`` or `str`.
            The access of the user, who's achievements will be requested.
        
        Returns
        -------
        achievements : `list` of ``Achievement`` objects
        
        Raises
        ------
        TypeError
            If `access` was not given neither as ``OA2Access``, ``UserOA2``  or `str` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        
        Notes
        -----
        This endpoint is unintentionally documented and will never work. For reference:
        ``https://github.com/discordapp/discord-api-docs/issues/1230``.
        
        Always drops `DiscordException UNAUTHORIZED (401): 401: Unauthorized`.
        """
        if isinstance(access, (OA2Access, UserOA2)):
            access_token = access.access_token
        elif isinstance(access, str):
            access_token = access
        else:
            raise TypeError(f'`access` can be given as `{OA2Access.__name__}`, `{UserOA2.__name__}` or `str`'
                f'instance, but got {access.__class__.__name__}.')
        
        
        headers = imultidict()
        headers[AUTHORIZATION] = f'Bearer {access_token}'
        
        data = await self.http.user_achievements(self.application.id, headers)
        return [Achievement(achievement_data) for achievement_data in data]
    
    
    async def user_achievement_update(self, user, achievement, percent_complete):
        """
        Updates the `user`'s achievement with the given percentage. The  achevement should be `secure`. This
        method only updates the achievement's percentage.
        
        This method is a coroutine.
        
        Parameters
        ----------
        user : ``User``, ``Client`` or `int` instance
            The user, who's achievement will be updated.
        achievement : ``Achievement`` or `int` instance
            The achievement, which's state will be updated
        percent_complete : `int`
            The completion percentage of the achievement.
        
        Raises
        ------
        TypeError
            - If `user` was not given neither as ``User``, ``Client`` nor `int` instance.
            - If `achievement` was not given neither as ``Achievement``, neither as `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            - If `percent_complete` was not given as `int` instance.
            - If `percent_complete` is out of range [0:100].
        
        Notes
        -----
        This endpoint cannot grant achievement, but can it even update them?. For reference:
        ``https://github.com/discordapp/discord-api-docs/issues/1230``.
        
        Only secure updates are supported, if they are even.
        - When updating secure achievement: `DiscordException NOT FOUND (404), code=10029: Unknown Entitlement`
        - When updating non secure: `DiscordException FORBIDDEN (403), code=40001: Unauthorized`
        """
        if isinstance(user, (User, Client)):
            user_id = user.id
        else:
            user_id = maybe_snowflake(user)
            if user_id is None:
                raise TypeError(f'`user` can be given as `{User.__name__}`, `{Client.__name__}` or `int` instance, '
                    f'got {user.__class__.__name__}.')
        
        
        if isinstance(achievement, Achievement):
            achievement_id = achievement.id
        else:
            achievement_id = maybe_snowflake(achievement)
            if achievement_id is None:
                raise TypeError(f'`achievement` can be given as `{Achievement.__name__}` or `int` instance, got '
                    f'{achievement.__class__.__name__}.')
        
        if __debug__:
            if not isinstance(percent_complete, int):
                raise AssertionError(f'`percent_complete` can be given as `int` instance, got '
                    f'{percent_complete.__class__.__name__}.')
            
            if percent_complete < 0 or percent_complete > 100:
                raise AssertionError(f'`percent_complete` is out of range [0:100], got {percent_complete!r}.')
        
        data = {'percent_complete': percent_complete}
        await self.http.user_achievement_update(user_id, self.application.id, achievement_id, data)
    
    
    async def application_get(self, application_id):
        """
        Requst a specific application by it's id.
        
        This method is a coroutine.
        
        Parameters
        ----------
        application_id : `int`
            The `id` of the application to request.

        Returns
        -------
        application : ``Application``
        
        Raises
        ------
        TypeError
            If `application_id` was not given as `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        
        Notes
        -----
        This endpoint does not support bot accounts.
        """
        application_id_c = maybe_snowflake(application_id)
        if application_id_c is None:
            raise TypeError(f'`application_id` can be given as `int` instance, got '
                f'{application_id.__class__.__name__}.')
        
        data = await self.http.application_get(application_id_c)
        return Application(data)
    
    
    async def eula_get(self, eula_id):
        """
        Requests the eula with the given id.
        
        This method is a coroutine.
        
        Parameters
        ----------
        eula_id : `int`
            The `id` of the eula to request.

        Returns
        -------
        eula : ``EULA``
        
        Raises
        ------
        TypeError
            If `eula_id` was not given as `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        eula_id_c = maybe_snowflake(eula_id)
        if eula_id_c is None:
            raise TypeError(f'`eula_id` can be given as `int` instance, got {eula_id.__class__.__name__}.')
        
        try:
            eula = EULAS[eula_id_c]
        except KeyError:
            pass
        else:
            return eula
        
        eula_data = await self.http.eula_get(eula_id_c)
        return EULA(eula_data)
    
    async def applications_detectable(self):
        """
        Requst the detectable applications
        
        This method is a coroutine.
        
        Returns
        -------
        applications : `list` of ``Application``
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        applications_data = await self.http.applications_detectable()
        return [Application(application_data) for application_data in applications_data]
    
    
    # loggin
    async def client_login_static(self):
        """
        The first step at loggin in is requesting the client's user data. This method is also used to check whether
        the token of the client is valid.
        
        This method is a coroutine.
        
        Returns
        -------
        response_data : `dict` of (`str` : `Any`)
            Decoded json data got from Discord.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        InvalidToken
            When the token of the client is invalid.
        """
        while True:
            try:
                data = await self.http.client_user()
            except DiscordException as err:
                status = err.status
                if status == 401:
                    raise InvalidToken() from err
                
                if status >= 500:
                    await sleep(2.5, KOKORO)
                    continue
                
                raise
            
            break
        
        return data
    
    # channels
    
    async def channel_group_leave(self, channel):
        """
        Leaves the client from the specified group channel.
        
        This method is a coroutine.
        
        Parameters
        ----------
        channel : ``ChannelGroup`` or `int`
            The channel to leave from.
        
        Raises
        ------
        TypeError
            If `channel` was not given neither as ``ChannelGroup`` nor `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        if isinstance(channel, ChannelGroup):
            channel_id = channel.id
        else:
            channel_id = maybe_snowflake(channel)
            if channel_id is None:
                raise TypeError(f'`channel` can be given as `{ChannelGroup.__name__}`, neither as `int` instance, got '
                    f'{channel.__class__.__name__}.')
        
        await self.http.channel_group_leave(channel_id)
    
    async def channel_group_user_add(self, channel, *users):
        """
        Adds the users to the given group channel.
        
        This method is a coroutine.
        
        Parameters
        ----------
        channel : ``ChannelGroup`` or `int` instance
            The channel to add the `users` to.
        *users : ``User``, ``Client`` or `int` instances
            The users to add to the `channel`.
        
        Raises
        ------
        TypeError
            - If `channel` was not given neither as ``ChannelGroup`` nor `int` instance.
            - If `users` contains non ``User``, ``Client``, neither `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        if isinstance(channel, ChannelGroup):
            channel_id = channel.id
        else:
            channel_id = maybe_snowflake(channel)
            if channel_id is None:
                raise TypeError(f'`channel` can be given as `{ChannelGroup.__name__}`, neither as `int` instance, got '
                    f'{channel.__class__.__name__}.')
        
        user_ids = []
        
        for user in users:
            if isinstance(user, (User, Client)):
                user_id = user.id
            else:
                user_id = maybe_snowflake(user)
                if user_id is None:
                    raise TypeError(f'`users` can be given as `{User.__name__}`, `{Client.__name__}` or `int` '
                        f'instances, but got {user.__class__.__name__}.')
                
            user_ids.append(user_id)
        
        for user_id in user_ids:
            await self.http.channel_group_user_add(channel_id, user_id)

    async def channel_group_user_delete(self, channel, *users):
        """
        Removes the users from the given group channel.
        
        This method is a coroutine.
        
        Parameters
        ----------
        channel : `ChannelGroup`` or `int` instance
            The channel from where the `users` will be removed.
        *users : ``User``, ``Client`` or `int` instances
            The users to remove from the `channel`.
        
        Raises
        ------
        TypeError
            - If `channel` was not given neither as ``ChannelGroup`` nor `int` instance.
            - If `users` contains non ``User``, ``Client``, neither `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        if isinstance(channel, ChannelGroup):
            channel_id = channel.id
        else:
            channel_id = maybe_snowflake(channel)
            if channel_id is None:
                raise TypeError(f'`channel` can be given as `{ChannelGroup.__name__}`, neither as `int` instance, got '
                    f'{channel.__class__.__name__}.')
        
        user_ids = []
        
        for user in users:
            if isinstance(user, (User, Client)):
                user_id = user.id
            else:
                user_id = maybe_snowflake(user)
                if user_id is None:
                    raise TypeError(f'`users` can be given as `{User.__name__}`, `{Client.__name__}` or `int` '
                        f'instances, but got {user.__class__.__name__}.')
            
            user_ids.append(user_id)
        
        for user_id in user_ids:
            await self.http.channel_group_user_delete(channel_id, user_id)
    
    async def channel_group_edit(self, channel, name=..., icon=...):
        """
        Edits the given group channel. Only the provided parameters will be edited.
        
        This method is a coroutine.
        
        Parameters
        ----------
        channel : ``ChannelGroup`` or `int` instance
            The channel to edit.
        name : `None` or `str`, Optional
            The new name of the channel. By passing `None` or an empty string you can remove the actual one.
        icon : `None` or `bytes-like`, Optional
            The new icon of the channel. By passing `None` your can remove the actual one.
        
        Raises
        ------
        TypeError
            - If `channel` was not given neither as ``ChannelGroup`` nor `int` instance.
            - If `name` is neither `None` or `str` instance.
            - If `icon` is neither `None` or `bytes-like`.
        ValueError
            - If `name` is passed as `str`, but it's length is `1`, or over `100`.
            - If `icon` is passed as `bytes-like`, but it's format is not any of the expected formats.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            - If `name` was not given neither as `None` or `str` instance.
            - If `name`'s length is out of range [2:100].
        Notes
        -----
        No request is done if no optional paremeter is provided.
        """
        if isinstance(channel, ChannelGroup):
            channel_id = channel.id
        else:
            channel_id = maybe_snowflake(channel)
            if channel_id is None:
                raise TypeError(f'`channel` can be given as `{ChannelGroup.__name__}`, neither as `int` instance, got '
                    f'{channel.__class__.__name__}.')
        
        data = {}
        
        if (name is not ...):
            if __debug__:
                if (name is not None):
                    if not isinstance(name, str):
                        raise AssertionError(f'`name` can be given as `None` or `str` instance, got '
                            f'{name.__class__.__name__}.')
                    
                    name_ln = len(name)
                    if name_ln > 100 or name_ln == 1:
                        raise AssertionError(f'`name` length can be in range [2:100], got {name_ln}; {name!r}.')
                    
                    # Translate empty nick to `None`
                    if name_ln == 0:
                        name = None
            else:
                # Non debug mode: Translate empty nick to `None`
                if (name is not None) and (not name):
                    name = None
            
            data['name'] = name
        
        if (icon is not ...):
            if icon is None:
                icon_data = None
            else:
                icon_type = icon.__class__
                if not issubclass(icon_type, (bytes, bytearray, memoryview)):
                    raise TypeError(f'`icon` can be passed as `bytes-like`, got {icon_type.__name__}.')
            
                extension = get_image_extension(icon)
                if extension not in VALID_ICON_FORMATS:
                    raise ValueError(f'Invalid icon type: `{extension}`.')
                
                icon_data = image_to_base64(icon)
            
            data['icon'] = icon_data
        
        if data:
            await self.http.channel_group_edit(channel_id, data)
    
    async def channel_group_create(self, *users):
        """
        Creates a group channel with the given users.
        
        This method is a coroutine.
        
        Parameters
        ----------
        *users : ``User``, ``Client`` or `int` instances
            The users to create the channel with.
        
        Returns
        -------
        channel : ``ChannelGroup``
            The created group channel.
        
        Raises
        ------
        TypeError
            If `users` contain not only ``User`, ``Client`` or `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            If the total amount of users is less than `2`.
        
        Notes
        -----
        This endpoint does not support bot accounts.
        """
        user_ids = set()
        
        for user in users:
            if isinstance(user, (User, Client)):
                user_id = user.id
            else:
                user_id = maybe_snowflake(user)
                if user_id is None:
                    raise TypeError(f'`users` can be given as `{User.__name__}`, `{Client.__name__}` or `int` '
                        f'instances, but got {user.__class__.__name__}.')
                
            user_ids.add(user_id)
        
        user_ids.add(self.id)
        
        if __debug__:
            user_ids_ln = len(user_ids)
            if user_ids_ln < 2:
                raise AssertionError(f'`{ChannelGroup.__name__}` can be created at least with at least `2` users, but '
                    f'got only {user_ids_ln}; {users!r}.')
        
        data = {'recipients': user_ids}
        data = await self.http.channel_group_create(self.id, data)
        return ChannelGroup(data, self)
    
    async def channel_private_create(self, user):
        """
        Creates a private channel with the given user. If there is an already cahced private channel with the user,
        returns that.
        
        This method is a coroutine.
        
        Parameters
        ----------
        user : ``User``, ``Client`` or `int` instance
            The user to create the private with.
        
        Returns
        -------
        channel : ``ChannelPrivate``
            The created private channel.
        
        Raises
        ------
        TypeError
            If `user` was not given neither as ``User``, ``Client`` nor `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        if isinstance(user, (User, Client)):
            user_id = user.id
        else:
            user_id = maybe_snowflake(user)
            if user_id is None:
                raise TypeError(f'`user` can be given as `{User.__name__}`, `{Client.__name__}` or `int` instance, '
                    f'got {user.__class__.__name__}.')
        
        try:
            channel = self.private_channels[user_id]
        except KeyError:
            data = await self.http.channel_private_create({'recipient_id': user_id})
            channel = ChannelPrivate(data, self)
        
        return channel
    
    async def channel_private_get_all(self):
        """
        Request the client's private + group channels and returns them in a list. At the case of bot accounts the
        request returns an empty list, so we skip it.
        
        This method is a coroutine.
        
        Returns
        -------
        channnels : `list` of (``ChannelPrivate`` or ``ChannelGroup``) objects
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        channels = []
        if (not self.is_bot):
            data = await self.http.channel_private_get_all()
            for channel_data in data:
                channel = CHANNEL_TYPES[channel_data['type']](data, self)
                channels.append(channel)
        
        return channels

    async def channel_move(self, channel, visual_position, *, category=..., lock_permissions=False, reason=None):
        """
        Moves a guild channel to the given visual position under it's category, or guild. If the algorithm can not
        place the channel exactly on that location, it will place it as close, as it can. If there is nothing to
        move, then the request is skipped.
        
        This method is a coroutine.
        
        Parameters
        ----------
        channel : ``ChannelGuildBase`` instance
            The channel to be moved.
        visual_position : `int`
            The visual position where the channel should go.
        category : `None` or ``ChannelGroup`` or ``Guild``, Optional
            If not set, then the channel will keep it's current parent. If the argument is set ``Guild`` instance or to
            `None`, then the  channel will be moved under the guild itself, Or if passed as ``ChannelCategory.md``,
            then the channel will be moved under it.
        lock_permissions : `bool`, Optional
            If you want to sync the permissions with the new category set it to `True`. Defaults to `False`.
        reason : `None` or `str`, Optional
            Shows up at the respective guild's audit logs.
        
        Raises
        ------
        ValueError
            - If the `channel` would be between guilds.
            - If category channel would be moved under an other category.
        TypeError
            - If `ChannelGuildBase` was not passed as ``ChannelGuildBase`` instance.
            - If `category` was not passed as `None`, or as ``Guild`` or ``ChannelCategory`` instance.
            
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        
        Notes
        -----
        This method also fixes the messy channel positions of Discord to an intuitive one.
        """
        # Check channel type
        if not isinstance(channel, ChannelGuildBase):
            raise TypeError(f'`channel` can be given as `{ChannelGuildBase.__name__}` instance, got '
                f'{channel.__class__.__name__}.')
        
        # Check whether the channel is partial.
        guild = channel.guild
        if guild is None:
            # Cannot move partial channels, leave
            return
        
        # Check category
        if category is ...:
            category = channel.category
        elif category is None:
            category = guild
        elif isinstance(category, Guild):
            if guild is not category:
                raise ValueError(f'Can not move channel between guilds! Channel\'s guild: {guild!r}; Category: '
                    f'{category!r}')
        elif isinstance(category, ChannelCategory):
            if category.guild is not guild:
                raise ValueError(f'Can not move channel between guilds! Channel\'s guild: {guild!r}; Category\'s '
                    f'guild: {category.guild!r}')
        else:
            raise TypeError(f'Invalid type {channel.__class__.__name__}')
        
        # Cannot put category under category
        if isinstance(channel, ChannelCategory) and isinstance(category, ChannelCategory):
            raise ValueError(f'Can not move categroy chanen lunedr category channel. Channel: {channel!r}; Category: '
                    f'{category!r}')
        
        if not isinstance(visual_position, int):
            raise TypeError(f'`visual_position` can be given as `int` instance, got '
                f'{visual_position.__class__.__name__}.')
        
        if not isinstance(lock_permissions, bool):
            raise TypeError(f'`lock_permissions` can be given as `bool` instance, got '
                f'{lock_permissions.__class__.__name__}.')
        
        # Cap at 0
        if visual_position < 0:
            visual_position = 0
        
        # If the channel is where it should be, we can leave.
        if channel.category is category and category.channel_list.index(channel) == visual_position:
            return
        
        # Create a display state, where each channel is listed.
        # Categories are inside of a tuple, where they are the first element of it and their channels are the second.
        display_state = guild.channel_list
        
        for index in range(len(display_state)):
            iter_channel = display_state[index]
            if isinstance(iter_channel, ChannelCategory):
                display_state[index] = iter_channel, iter_channel.channel_list
        
        # Generate a state where the channels are theoretically ordered with tuples
        display_new = []
        for iter_channel in display_state:
            if isinstance(iter_channel, tuple):
                iter_channel, sub_channels = iter_channel
                display_sub_channels = []
                for sub_channel in sub_channels:
                    channel_key = (sub_channel.ORDER_GROUP, sub_channel.position, sub_channel.id, None)
                    display_sub_channels.append(channel_key)
            else:
                display_sub_channels = None
            
            channel_key = (iter_channel.ORDER_GROUP, iter_channel.position, iter_channel.id, display_sub_channels)
            
            display_new.append(channel_key)
        
        # We have 2 display states, we will compare the old to the new one when calculating differences, but we didnt
        # move our channel yet!
        
        # We get from where we will move from.
        old_category = channel.category
        if isinstance(old_category, Guild):
            move_from = display_new
        else:
            old_category_id = old_category.id
            for channel_key in display_new:
                if channel_key[2] == old_category_id:
                    move_from = channel_key[3]
                    break
            
            else:
                # If no breaking was not done, our channel not exists, lol
                return
        
        # We got from which thing we will move from, so we remove first
        
        channel_id = channel.id
        
        for index in range(len(move_from)):
            channel_key = move_from[index]
            
            if channel_key[2] == channel_id:
                channel_key_to_move = channel_key
                del move_from[index]
                break
        
        else:
            # If breaking was not done, our channel not exists, lol
            return
        
        # We get to where we will move to.
        if isinstance(category, Guild):
            move_to = display_new
        else:
            new_category_id = category.id
            for channel_key in display_new:
                if channel_key[2] == new_category_id:
                    move_to = channel_key[3]
                    break
            
            else:
                # If no breaking was not done, our channel not exists, lol
                return
        
        # Move, yayyy
        move_to.insert(visual_position, channel_key_to_move)
        # Reorder
        move_to.sort(key=lambda channel_key_: channel_key_[0])
        
        # Now we resort every channel in the guild and categories, mostly for security issues
        to_sort_all = [display_new]
        for channel_key in display_new:
            display_sub_channels = channel_key[3]
            if display_sub_channels is not None:
                to_sort_all.append(display_sub_channels)
        
        ordered = []
        
        for to_sort in to_sort_all:
            expected_channel_order_group = 0
            channel_position = 0
            for sort_key in to_sort:
                channel_order_group = sort_key[0]
                channel_id = sort_key[2]
                
                if channel_order_group != expected_channel_order_group:
                    expected_channel_order_group = channel_order_group
                    channel_position = 0
                
                ordered.append((channel_position, channel_id))
                channel_position += 1
                continue
        
        bonus_data = {'lock_permissions': lock_permissions}
        if category is guild:
            bonus_data['parent_id'] = None
        else:
            bonus_data['parent_id'] = category.id
        
        data = []
        channels = guild.channels
        for position, channel_id in ordered:
            channel_ = channels[channel_id]
            
            if channel is channel_:
                data.append({'id': channel_id, 'position': position, **bonus_data})
                continue
            
            if channel_.position != position:
                data.append({'id': channel_id, 'position': position})
        
        await self.http.channel_move(guild.id, data, reason)
    
    async def channel_edit(self, channel, *, name=None, topic=None, nsfw=None, slowmode=None, user_limit=None,
            bitrate=None, type_=None, reason=None):
        """
        Edits the given guild channel. Different channel types accept different parameters, so make sure to not pass
        out of place parameters. Only the passed parameters will be edited of the channel.
        
        This method is a coroutine.
        
        Parameters
        ----------
        channel : ``ChannelGuildBase`` or `int` instance
            The channel to edit.
        name : `str`, Optional
            The `channel`'s new name.
        topic : `str`, Optional
            The new topic of the `channel`.
        nsfw : `bool`, Optional
            Whether the `channel` will be nsfw or not.
        slowmode : `int`, Optional
            The new slowmode value of the `channel`.
        user_limit : `int`, Optional
            The new user limit of the `channel`.
        bitrate : `int`, Optional
            The new bitrate of the `channel`.
        type_ : `int`, Optional
            The `channel`'s new type value.
        reason : `None` or `str`, Optional
            Shows up at the respective guild's audit logs.
        
        Raises
        ------
        TypeError
            If the given `channel` is not ``ChannelGuildBase`` or `int` instance.
        AssertionError
            - If `name` was not given as `str` instance.
            - If `name`'s length is under `2` or over `100`.
            - If `topic` was not given as `str` instance.
            - If `topic`'s length is over `1024`.
            - If `topic` was given, but the given channel is not ``ChannelText`` instance.
            - If `type_` was given, but the given channel is not ``ChannelText`` instance.
            - If `type_` was not given as `int` instance.
            - If `type_` cannot be interchanged to the given value.
            - If `nsfw` was given meanwhile the channel is not ``ChannelText`` or ``ChannelStore`` instance.
            - If `nsfw` was not given as `bool`.
            - If `slowmode` was given, but the channel is not ``ChannelText`` instance.
            - If `slowmode` was not given as `int` instance.
            - If `slowmode` was given, but it's value is less than `0` or greater than `21600`.
            - If `bitrate` was given, but the channel is not ``ChannelVoice`` instance.
            - If `bitrate` was not given as `int` instance.
            - If `bitrate`'s value is out of the expected range.
            - If `user_limit` was given, but the channel is not ``ChannelVoice`` instance.
            - If `user_limit` was not given as `int` instance.
            - If `user_limit`' was given, but is out of the expected [0:99] range.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        if isinstance(channel, ChannelGuildBase):
            channel_id = channel.id
        else:
            channel_id = maybe_snowflake(channel)
            if channel_id is None:
                raise TypeError(f'`channel` parameter can be given as {ChannelGuildBase.__name__} or `int` instance, '
                    f'got {channel.__class__.__name__}.')
            
            channel = None
        
        data = {}
        
        if (name is not None):
            if __debug__:
                if not isinstance(name, str):
                    raise AssertionError(f'`name` can be given as `str` instance, got {name.__class__.__name__}.')
                
                name_ln = len(name)
                
                if name_ln < 2 or name_ln > 100:
                    raise AssertionError(f'`name` length can be in range [2:100], got {name_ln}; {name!r}.')
            
            data['name'] = name
        
        
        if (topic is not None):
            if __debug__:
                if (channel is not None):
                    if not isinstance(channel, ChannelText):
                        raise AssertionError(f'`topic` is a valid parameter only for {ChannelText.__name__} '
                            f'instances, got {channel.__class__.__name__}.')
                
                if not isinstance(topic, str):
                    raise AssertionError(f'`topic` can be given as `str` instance, got {topic.__class__.__name__}.')
                
                topic_ln = len(topic)
                
                if topic_ln > 1024:
                    raise AssertionError(f'`topic` length can be in range [0:1024], got {topic_ln}; {topic!r}.')
                
            data['topic'] = topic
        
        
        if (type_ is not None):
            if __debug__:
                if (channel is not None):
                    if not isinstance(channel, ChannelText):
                        raise AssertionError(f'`type_` is a valid parameter only for `{ChannelText.__name__}` '
                            f'instances, but got {channel.__class__.__name__}.')
                
                if not isinstance(type_, int):
                    raise AssertionError(f'`type_` can be given as `int` instance, got {type_.__class__.__name__}.')
                
                if type_ not in ChannelText.INTERCHANGE:
                    raise AssertionError(f'`type_` can be interchanged to `{ChannelText.INTERCHANGE}`, got {type_!r}.')
            
            data['type'] = type_
        
        
        if (nsfw is not None):
            if __debug__:
                if (channel is not None):
                    if not isinstance(channel, (ChannelText, ChannelStore)):
                        raise AssertionError(f'`nsfw` is a valid parameter only for `{ChannelText.__name__}` and '
                            f'`{ChannelStore.__name__}` instances, but got {channel.__class__.__name__}.')
                
                if not isinstance(nsfw, bool):
                    raise AssertionError(f'`nsfw` can be given as `bool` instance, got {nsfw.__class__.__name__}.')
            
            data['nsfw'] = nsfw
        
        
        if (slowmode is not None):
            if __debug__:
                if (channel is not None):
                    if not isinstance(channel, ChannelText):
                        raise AssertionError(f'`slowmode` is a valid parameter only for `{ChannelText.__name__}` '
                            f'instances, but got {channel.__class__.__name__}.')
                    
                if not isinstance(slowmode, int):
                    raise AssertionError('`slowmode` can be given as `int` instance, got '
                        f'{slowmode.__class__.__name__}.')
                
                if slowmode < 0 or slowmode > 21600:
                    raise AssertionError(f'`slowmode` can be in range [0:21600], got: {slowmode!r}.')
            
            data['rate_limit_per_user'] = slowmode
        
        
        if (bitrate is not None):
            if __debug__:
                if (channel is not None):
                    if not isinstance(channel, ChannelVoice):
                        raise AssertionError(f'`bitrate` is a valid parameter only for `{ChannelVoice.__name__}` '
                            f'instances, but got {channel.__class__.__name__}.')
                    
                if not isinstance(bitrate, int):
                    raise AssertionError('`bitrate` can be given as `int` instance, got '
                        f'{bitrate.__class__.__name__}.')
                
                # Get max bitrate
                if channel is None:
                    bitrate_limit = 384000
                else:
                    guild = channel.guild
                    if guild is None:
                        bitrate_limit = 384000
                    else:
                        bitrate_limit = guild.bitrate_limit
                
                if bitrate < 8000 or bitrate > bitrate_limit:
                    raise AssertionError(f'`bitrate` is out of the expected [8000:{bitrate_limit}] range, got '
                        f'{bitrate!r}.')
            
            data['bitrate'] = bitrate
        
        
        if (user_limit is not None):
            if __debug__:
                if (channel is not None):
                    if not isinstance(channel, ChannelVoice):
                        raise AssertionError(f'`user_limit` is a valid parameter only for `{ChannelVoice.__name__}` '
                            f'instances, but got {channel.__class__.__name__}.')
                
                if user_limit < 0 or user_limit > 99:
                    raise AssertionError('`user_limit`\'s value is out of the expected [0:99] range, got '
                        f'{user_limit!r}.')
            
            data['user_limit'] = user_limit
        
        
        await self.http.channel_edit(channel_id, data, reason)
    
    
    async def channel_create(self, guild, name, type_=ChannelText, *, reason=None, **kwargs):
        """
        Creates a new channel at the given `guild`. If the channel is successfully created returns it.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild``
            The guild where the channel will be created.
        name : `str`
            The created channel's name.
        type_ : `int` or ``ChannelGuildBase`` subclass, Optional
            The type of the created channel. Defaults to ``ChannelText``.
        reason : `None` or `str`, Optional
            Shows up at the `guild`'s audit logs.
        **kwargs : Keyword arguments
            Additional keyword arguments to describe the created channel.
        
        Other Parameters
        ----------------
        overwrites : `list` of ``cr_p_overwrite_object`` returns, Optional
            A list of permission overwrites of the channel. The list should contain json serializable permission
            overwrites made by the ``cr_p_overwrite_object`` function.
        topic : `str`, Optional
            The channel's topic.
        nsfw : `bool`, Optional
            Whether the channel is marked as nsfw.
        slowmode : int`, Optional
            The channel's slowmode value.
        bitrate : `int`, Optional
            The channel's bitrate.
        user_limit : `int`, Optional
            The channel's user limit.
        category : `None`, ``ChannelCategory``, ``Guild`` or `int`, Optional
            The channel's category. If the category is under a guild, leave it empty.
        
        Returns
        -------
        channel : `None` or ``ChannelGuildBase`` instance
            The created channel. Returns `None` if the respective `guild` is not cached.
        
        Raises
        ------
        TypeError
            - If `guild` was not given as ``Guild`` or `int` instance.
            - If `type_` was not passed as `int` or as ``ChannelGuildBase`` instance.
            - If `category` was not given as `None`, ``ChannelCategory``, ``Guild`` or `int` instance.
        AssertionError
            - If `type_` was given as `int`, and is less than `0`.
            - If `type_` was given as `int` and exceeds the defined channel type limit.
            - If `name` was not given as `str` instance.
            - If `name`'s length is under `2` or over `100`.
            - If `overwrites` was not given as `None`, neither as `list` of `dict`-s.
            - If `topic` was not given as `str` instance.
            - If `topic`'s length is over `1024`.
            - If `topic` was given, but the respective channel type is not ``ChannelText``.
            - If `nsfw` was given meanwhile the respective channel type is not ``ChannelText`` or ``ChannelStore``.
            - If `nsfw` was not given as `bool`.
            - If `slowmode` was given, but the respective channel type is not ``ChannelText``.
            - If `slowmode` was not given as `int` instance.
            - If `slowmode` was given, but it's value is less than `0` or greater than `21600`.
            - If `bitrate` was given, but the respective channel type is not ``ChannelVoice``.
            - If `bitrate` was not given as `int` instance.
            - If `bitrate`'s value is out of the expected range.
            - If `user_limit` was given, but the respective channel type is not ``ChannelVoice``.
            - If `user_limit` was not given as `int` instance.
            - If `user_limit`' was given, but is out of the expected [0:99] range.
            - If `category` was given, but the respective channel type cannto be put under other categories.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        if isinstance(guild, Guild):
            guild_id = guild.id
        else:
            guild_id = maybe_snowflake(guild)
            if guild_id is None:
                raise TypeError(f'`guild` can be given as `{Guild.__name__}` or `int` instance, got '
                    f'{guild.__class__.__name__}.')
            
            guild = GUILDS.get(guild_id)
        
        
        data = cr_pg_channel_object(name, type_, **kwargs, guild=guild)
        data = await self.http.channel_create(guild_id, data, reason)
        
        if (guild is not None):
            return CHANNEL_TYPES[data['type']](data, self, guild)
    
    
    async def channel_delete(self, channel, reason=None):
        """
        Deletes the specified guild channel.
        
        This method is a coroutine.
        
        Parameters
        ----------
        channel : ``ChannelGuildBase`` or `int` instance
            The channel to delete.
        reason : `None` or `str`, Optional
            Shows up at the respective guild's audit logs.
        
        Raises
        ------
        TypeError
            If the given `channel` is not ``ChannelGuildBase`` or `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        
        Notes
        -----
        If a category channel is deleted, it's subchannels will not be removed, instead they will move under the guild.
        """
        if isinstance(channel, ChannelGuildBase):
            channel_id = channel.id
        else:
            channel_id = maybe_snowflake(channel)
            if channel_id is None:
                raise TypeError(f'`channel` parameter can be given as {ChannelGuildBase.__name__} or `int` instance, '
                    f'got {channel.__class__.__name__}.')
        
        await self.http.channel_delete(channel_id, reason)
    
    async def channel_follow(self, source_channel, target_channel):
        """
        Follows the `source_channel` with the `target_channel`. Returns the webhook, what will crosspost the published
        messages.
        
        This method is a coroutine.
        
        Parameters
        ----------
        source_channel : ``ChannelText`` or `int` instance
            The channel what will be followed. Must be an announcements (type 5) channel.
        target_channel : ``ChannelText`` or `int`instance
            The target channel where the webhook messages will be sent. Can be any guild text channel type.
        
        Returns
        -------
        webhook : ``Webhook``
            The webhook what will crosspost the published messages. This webhook has no `.token` set.
        
        Raises
        ------
        TypeError
            - If the `source_channel` was not given neither as ``ChannelText`` nor `int` instance.
            - If the `target_channel` was not given neither as ``ChannelText`` nor `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            - If `source_channel` is not announcement channel.
        """
        if isinstance(source_channel, ChannelText):
            if __debug__:
                if source_channel.type != 5:
                    raise AssertionError(f'`source_channel` must be type 5 (announcements) channel, got '
                        f'`{source_channel}`.')
            
            source_channel_id = source_channel.id
        
        else:
            source_channel_id = maybe_snowflake(source_channel)
            if source_channel_id is None:
                raise TypeError(f'`source_channel` can be given as {ChannelText.__name__} or `int` instance, got '
                    f'{source_channel.__class__.__name__}.')
            
            source_channel = ChannelText.precreate(source_channel_id)
        
        if isinstance(target_channel, ChannelText):
            target_channel_id = target_channel.id
        else:
            target_channel_id = maybe_snowflake(target_channel)
            if target_channel_id is None:
                raise TypeError(f'`channel` can be given as {ChannelText.__name__} or `int` instance, got '
                    f'{target_channel.__class__.__name__}.')
            
            target_channel = ChannelText.precreate(target_channel_id)
        
        data = {
            'webhook_channel_id': target_channel_id,
                }
        
        data = await self.http.channel_follow(source_channel_id, data)
        webhook = await Webhook._from_follow_data(data, source_channel, target_channel, self)
        return webhook
    
    # messages
    
    async def _maybe_get_channel(self, channel_id):
        """
        Method for creating a channel from `channel_id`. Used by ``.message_logs`` and familiar methods to detect
        and create channel type from id.
        
        The method should be called only after successfull data request.
        
        This method is a coroutine.
        
        Parameters
        ----------
        channel_id : `int`
            The channel's id.
        
        Returns
        -------
        channel : ``ChannelTextBase`` instance
        """
        # First try to get from cache.
        if not self.is_bot:
            # Private channel maybe?
            await self.channel_private_get_all()
            
            try:
                channel = CHANNELS[channel_id]
            except KeyError:
                pass
            else:
                return channel
        
        # If we do not find the channel, not it is private (probably), we create a guild text channel.
        # The exception case of real users is pretty small, so we can ignore it.
        channel = ChannelText.precreate(channel_id)
        return channel
    
    async def message_logs(self, channel, limit=100, *, after=None, around=None, before=None):
        """
        Requests messages from the given text channel. The `after`, `around` and the `before` arguments are mutually
        exclusive and they can be passed as `int`, or as a ``DiscordEntitiy`` instance or as a `datetime` object.
        If there is at least 1 message overlap between the received and the loaded messages, the wrapper will chain
        the channel's message history up. If this happens the channel will get on a queue to have it's messages again
        limited to the default one, but requesting old messages more times, will cause it to extend.
        
        This method is a coroutine.
        
        Parameters
        ----------
        channel : ``ChannelTextBase`` or `int` instance
            The channel from where we want to request the messages.
        limit : `int`, Optiomal
            The amount of messages to request. Can be between 1 and 100.
        after : `int`, ``DiscordEntity`` or `datetime`, Optional
            The timestamp after the requested messages were created.
        around : `int`, ``DiscordEntity`` or `datetime`, Optional
            The timestamp around the requested messages were created.
        before : `int`, ``DiscordEntity`` or `datetime`, Optional
            The timestamp before the requested messages were created.
        
        Returns
        -------
        messages : `list` of ``Message`` objects
        
        Raises
        ------
        TypeError
            - If `channel` was not given neither as ``ChannelTextBase`` nor `int` instance.
            - If `after`, `around` or `before` was passed with an unexpected type.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            - If `limit` was not given as `int` instance.
            - If `limit` is out of range [1:100].
        
        See Also
        --------
        - ``.message_logs_fromzero`` : Familiar to this method, but it requests only the newest messages of the channel
            and makes sure they are chained up with the channel's message history.
        - ``.message_at_index`` : A toplevel method to get a message at the specified index at the given channel.
            Usually used to load the channel's message history to that point.
        - ``.messages_in_range`` : A toplevel method to get all the messages till the specified index at the given
            channel.
        - ``.message_iterator`` : An iterator over a channel's message history.
        """
        if isinstance(channel, ChannelTextBase):
            channel_id = channel.id
        
        else:
            channel_id = maybe_snowflake(channel)
            if channel_id is None:
                raise TypeError(f'`channel` can be given as `{ChannelTextBase.__name__}` or `int` instance, got '
                    f'{channel.__class__.__name__}.')
            
            channel = CHANNELS.get(channel_id)
        
        if __debug__:
            if not isinstance(limit, int):
                raise AssertionError(f'`limit` can be given as `int` instance, got {limit.__class__.__name__}.')
            
            if limit < 1 or limit > 100:
                raise AssertionError(f'`limit` is out from the expected [1:100] range, got {limit!r}.')
        
        data = {'limit': limit}
        
        if (after is not None):
            data['after'] = log_time_converter(after)
        
        if (around is not None):
            data['around'] = log_time_converter(around)
        
        if (before is not None):
            data['before'] = log_time_converter(before)
        
        data = await self.http.message_logs(channel_id, data)
        
        if channel is None:
            channel = await self._maybe_get_channel(channel_id)
        
        return channel._process_message_chunk(data)
    
    # If you have 0-1-2 messages at a channel, and you wanna store the messages. The other wont store it, because it
    # wont see anything what allows channeling.
    async def message_logs_fromzero(self, channel, limit=100):
        """
        If the `channel` has `1` or less messages loaded use this method instead of ``.message_logs`` to request the
        newest messages there, because this method makes sure, the returned messages will be chained at the
        channel's message history.
        
        This method is a coroutine.
        
        Parameters
        ----------
        channel : ``ChannelTextBase`` instance
            The channel from where we want to request the messages.
        limit : `int`, Optiomal
            The amount of messages to request. Can be between 1 and 100.
        
        Returns
        -------
        messages : `list` of ``Message`` objects
        
        Raises
        ------
        TypeError
            If `channel` was not given neither as ``ChannelTextBase`` nor `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            - If `limit` was not given as `int` instance.
            - If `limit` is out of range [1:100].
        """
        if isinstance(channel, ChannelTextBase):
            channel_id = channel.id
        
        else:
            channel_id = maybe_snowflake(channel)
            if channel_id is None:
                raise TypeError(f'`channel` can be given as `{ChannelTextBase.__name__}` or `int` instance, got '
                    f'{channel.__class__.__name__}.')
            
            channel = CHANNELS.get(channel_id)
        
        if __debug__:
            if not isinstance(limit, int):
                raise AssertionError(f'`limit` can be given as `int` instance, got {limit.__class__.__name__}.')
            
            if limit < 1 or limit > 100:
                raise AssertionError(f'`limit` is out from the expected [1:100] range, got {limit!r}.')
        
        data = {'limit': limit, 'before': 9223372036854775807}
        data = await self.http.message_logs(channel_id, data)
        if data:
            if channel is None:
                channel = await self._maybe_get_channel(channel_id)
            
            channel._create_new_message(data[0])
            messages = channel._process_message_chunk(data)
        else:
            messages = []
        
        return messages
    
    async def message_get(self, channel, message_id):
        """
        Requests a specific message by it's id at the given `channel`.
        
        This method is a coroutine.
        
        Parameters
        ----------
        channel : ``ChannelTextBase`` or `int` instance
            The channel from where we want to request the message.
        message_id : `int`
            The message's id.
        
        Returns
        -------
        message : ``Message``
        
        Raises
        ------
        TypeError
            If `channel` was not given neither as ``ChannelTextBase`` nor `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        if isinstance(channel, ChannelTextBase):
            channel_id = channel.id
        
        else:
            channel_id = maybe_snowflake(channel)
            if channel_id is None:
                raise TypeError(f'`channel` can be given as `{ChannelTextBase.__name__}` or `int` instance, got '
                    f'{channel.__class__.__name__}.')
            
            channel = CHANNELS.get(channel_id)
        
        data = await self.http.message_get(channel_id, message_id)
        
        if channel is None:
            channel = await self._maybe_get_channel(channel_id)
        
        return channel._create_unknown_message(data)
    
    async def message_create(self, channel, content=None, *, embed=None, file=None, allowed_mentions=..., tts=False,
            nonce=None):
        """
        Creates and returns a message at the given `channel`. If there is nothing to send, then returns `None`.
        
        This method is a coroutine.
        
        Parameters
        ----------
        channel : ``ChannelTextBase`` instance, `int` instance, ``Message``, ``MessageRepr`` or ``MessageReference``
            The text channel where the message will be sent, or the message on what you want to reply.
        content : `str`, ``EmbedBase``, `Any`, Optional
            The message's content if given. If given as `str` or empty string, then no content will be sent, meanwhile
            if any other non `str` or ``EmbedBase`` instance is given, then will be casted to string.
            
            If given as ``EmbedBase`` instance, then is sent as the message's embed.
            
        embed : ``EmbedBase`` instance or `list` of ``EmbedBase`` instances, Optional
            The embedded content of the message.
            
            If `embed` and `content` parameters are both given as  ``EmbedBase`` instance, then `TypeError` is raised.
            
            If embeds are given as a list, then the first embed is picked up.
        file : `Any`, Optional
            A file to send. Check ``._create_file_form`` for details.
        allowed_mentions : `None`,  `str`, ``UserBase``, ``Role``, `list` of (`str`, ``UserBase``, ``Role`` ), Optional
            Which user or role can the message ping (or everyone). Check ``._parse_allowed_mentions`` for details.
        tts : `bool`, Optional
            Whether the message is text-to-speech.
        nonce : `str`, Optional
            Used for optimisting message sending. Will shop up at the message's data.
        
        Returns
        -------
        message : ``Message`` or `None`
            Returns `None` if there is nothing to send.
        
        Raises
        ------
        TypeError
            - If `embed` was given as `list`, but it contains not only ``EmbedBase`` instances.
            - If `allowed_mentions` contains an element of invalid type.
            - `content` parameter was given as ``EmbedBase`` instance, meanwhile `embed` parameter was given as well.
            - If ivalid file type would be sent.
            - If `channel`'s type is incorrect.
        ValueError
            - If `allowed_mentions`'s elements' type is correct, but one of their value is invalid.
            - If more than `10` files would be sent.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        
        See Also
        --------
        ``.webhook_message_create`` : Sending a message with a ``Webhook``.
        """
        
        # Channel check order:
        # 1.: ChannChannelTextBaseelText -> channel
        # 2.: Message -> channel + reply
        # 3.: int (str) -> channel
        # 4.: MessageRepr -> channel + reply
        # 5.: MessageReference -> channel + reply
        # 6.: raise
        
        if isinstance(channel, ChannelTextBase):
            message_id = None
            channel_id = channel.id
        elif isinstance(channel, Message):
            message_id = channel.id
            channel = channel.channel
            channel_id = channel.id
        else:
            channel_id = maybe_snowflake(channel)
            if (channel_id is not None):
                message_id = None
                channel = CHANNELS.get(channel_id)
            elif isinstance(channel, MessageRepr):
                message_id = channel.id
                channel = channel.channel
                channel_id = channel.id
            elif isinstance(channel, MessageReference):
                channel_id = channel.channel_id
                message_id = channel.message_id
                channel = CHANNELS.get(channel_id)
            else:
                raise TypeError(f'`channel` can be given as `{ChannelTextBase.__name__}`, `{Message.__name__}`, '
                    f'`{MessageRepr.__name__}` or as `{MessageReference.__name__}` instance, got '
                    f'{channel.__class__.__name__}.')
        
        # Embed check order:
        # 1.: None
        # 2.: Embed
        # 3.: list of Embed -> embed[0] or None
        # 4.: raise
        
        if embed is None:
            pass
        elif isinstance(embed, EmbedBase):
            pass
        elif isinstance(embed, (list, tuple)):
            if embed:
                if __debug__:
                    for index, element in enumerate(embed):
                        if isinstance(element, EmbedBase):
                            continue
                        
                        raise TypeError(f'`embed` was given as a `list`, but it\'s element under index `{index}` '
                            f'is not `{EmbedBase.__name__}` instance, but {embed_element.__class__.__name__}`, got: '
                            f'{embed.__class__.__name__}.')
                
                embed = embed[0]
            else:
                embed = None
        else:
            raise TypeError(f'`embed` was not given as `{EmbedBase.__name__}` instance, neither as a list of '
                f'{EmbedBase.__name__} instances, got {embed.__class__.__name__}.')
        
        # Content check order:
        # 1.: None
        # 2.: str
        # 3.: Embed - > embed = content
        # 4.: list of Embed -> Embed = content[0]
        # 5.: object -> str(content)
        
        if content is None:
            pass
        elif isinstance(content, str):
            if not content:
                content = None
        elif isinstance(content, EmbedBase):
            if __debug__:
                if (embed is not None):
                    raise TypeError(f'Multiple embeds were given, got content={content!r}, embed={embed!r}.')
            
            embed = content
            content = None
        else:
            # Check for list of embeds as well.
            if isinstance(content, (list, tuple)):
                if content:
                    for element in content:
                        if isinstance(element, EmbedBase):
                            continue
                        
                        is_list_of_embeds = False
                        break
                    else:
                        is_list_of_embeds = True
                else:
                    is_list_of_embeds = False
            else:
                is_list_of_embeds = False
            
            if is_list_of_embeds:
                if __debug__:
                    if (embed is not None):
                        raise TypeError(f'Multiple embeds were given, got content={content!r}, embed={embed!r}.')
                
                embed = content[0]
                content = None
            else:
                content = str(content)
                if not content:
                    content = None
        
        # Build payload
        message_data = {}
        contains_content = False
        
        if (content is not None):
            message_data['content'] = content
            contains_content = True
        
        if (embed is not None):
            message_data['embed'] = embed.to_data()
            contains_content = True
        
        if tts:
            message_data['tts'] = True
        
        if (nonce is not None):
            message_data['nonce'] = nonce
        
        if (allowed_mentions is not ...):
            message_data['allowed_mentions'] = self._parse_allowed_mentions(allowed_mentions)
        
        if (message_id is not None):
            message_data['message_reference'] = {'message_id': message_id}
        
        if file is None:
            to_send = message_data
        else:
            to_send = self._create_file_form(message_data, file)
            if to_send is None:
                to_send = message_data
            else:
                contains_content = True
        
        if not contains_content:
            return None
        
        data = await self.http.message_create(channel_id, to_send)
        if (channel is not None):
            return channel._create_new_message(data)
    
    @staticmethod
    def _create_file_form(data, file):
        """
        Creates a `multipart/form-data` form from the message's data and from the file data. If there is no files to
        send, will return `None` to tell the caller, that nothing is added to the overall data.
        
        Parameters
        ----------
        data : `dict` of `Any`
            The data created by the ``.message_create`` method.
        file : `dict` of (`file-name`, `io`) items, `list` of (`file-name`, `io`) elements, tuple (`file-name`, `io`), `io`
            The files to send.
        
        Returns
        -------
        form : `None` or `Formdata`
            Returns a `Formdata` of the files and from the message's data. If there are no files to send, returns `None`
            instead.
        
        Raises
        ------
        ValueError
            When more than `10` file is registered to send.
        
        Notes
        -----
        Accepted `io` types with check order are:
        - ``BodyPartReader`` instance
        - `bytes`, `bytearray`, `memoryview` instance
        - `str` instance
        - `BytesIO` instance
        - `StringIO` instance
        - `TextIOBase` instance
        - `BufferedReader`, `BufferedRandom` instance
        - `IOBase` instance
        - ``AsyncIO`` instance
        - `async-iterable`
        
        Raises `TypeError` at the case of invalid `io` type.
        
        There are two predefined datatypes specialized to send files:
        - ``ReuBytesIO``
        - ``ReuAsyncIO``
        
        If a buffer is sent, then when the request is done, it is closed. So if the request fails, we would not be
        able to resend the file, except if we have a datatype, what instead of closing on `.close()` just seeks to
        `0` (or later if needed) on close, instead of really closing instantly. These datatypes implement a
        `.real_close()` method, but they do `real_close` on `__exit__` as well.
        """
        form = Formdata()
        form.add_field('payload_json', to_json(data))
        files = []
        
        # checking structure
        
        # case 1 dict like
        if hasattr(type(file), 'items'):
            files.extend(file.items())
        
        # case 2 tuple => file, filename pair
        elif isinstance(file, tuple):
            files.append(file)
        
        # case 3 list like
        elif isinstance(file, (list, deque)):
            for element in file:
                if type(element) is tuple:
                    name, io = element
                else:
                    io = element
                    name = ''
                
                if not name:
                    #guessing name
                    name = getattr(io, 'name', '')
                    if name:
                        _, name = splitpath(name)
                    else:
                        name = str(random_id())
                
                files.append((name, io),)
        
        #case 4 file itself
        else:
            name = getattr(file, 'name', '')
            #guessing name
            if name:
                _, name = splitpath(name)
            else:
                name = str(random_id())
            
            files.append((name, file),)
        
        # checking the amount of files
        # case 1 one file
        if len(files) == 1:
            name, io = files[0]
            form.add_field('file', io, filename=name, content_type='application/octet-stream')
        # case 2, no files -> return None, we should use the already existing data
        elif len(files) == 0:
            return None
        # case 3 maximum 10 files
        elif len(files) < 11:
            for index, (name, io) in enumerate(files):
                form.add_field(f'file{index}s', io, filename=name, content_type='application/octet-stream')
        
        # case 4 more than 10 files
        else:
            raise ValueError('You can send maximum 10 files at once.')
        
        return form
    
    @staticmethod
    def _parse_allowed_mentions(allowed_mentions):
        """
        If `allowed_mentions` is passed as `None`, then returns a `dict`, what will cause all mentions to be disabled.
        
        If passed as an `iterable`, then it's elements will be checked. They can be either type `str`
        (any value from `('everyone', 'users', 'roles')`), ``UserBase`` or ``Role`` instances.
        
        Passing `everyone` will allow the message to mention `@everyone` (permissions can overwrite this behaviour).
        
        Passing `'users'` will allow the message to mention all the users, meanwhile passing ``UserBase`` instances
        allow to mentioned the respective users. Using `users` and ``UserBase`` instances is mutually exclusive,
        and the wrapper will register only `users` to avoid getting ``DiscordException``.
        
        `'roles'` and ``Role`` instances follow the same rules as `'users'` and the ``UserBase`` instances.
        
        By passing `'!replied_user'` you can disable mentioning the replied user, or by passing`'replied_user'` you can
        re-enable mentioning the replied user.
        
        Parameters
        ----------
        allowed_mentions : `None`,  `str`, ``UserBase``, ``Role``, `list` of (`str`, ``UserBase``, ``Role`` )
            Which user or role can the message ping (or everyone).
        
        Returns
        -------
        allowed_mentions : `dict` of (`str`, `Any`) items
        
        Raises
        ------
        TypeError
            If `allowed_mentions` contains an element of invalid type.
        ValueError
            If `allowed_mentions` contains en element of correct type, but an invalid value.
        """
        if (allowed_mentions is None):
            return {'parse': []}
        
        if isinstance(allowed_mentions, list):
            if (not allowed_mentions):
                return {'parse': []}
        else:
            allowed_mentions = [allowed_mentions]
        
        allow_replied_user = 0
        allow_everyone = 0
        allow_users = 0
        allow_roles = 0
        
        allowed_users = None
        allowed_roles = None
        
        for element in allowed_mentions:
            if isinstance(element, str):
                if element == '!replied_user':
                    allow_replied_user = -1
                    continue
                
                if element == 'replied_user':
                    allow_replied_user = 1
                    continue
                
                if element == 'everyone':
                    allow_everyone = 1
                    continue
                
                if element == 'users':
                    allow_users = 1
                    continue
                
                if element == 'roles':
                    allow_roles = 1
                    continue
                
                raise ValueError(f'`allowed_mentions` contains a not valid `str` element: `{element!r}`. Type`str` '
                    f'elements can be one of: (\'everyone\', \'users\', \'roles\').')
            
            if isinstance(element, UserBase):
                if allowed_users is None:
                    allowed_users = []
                
                allowed_users.append(element.id)
                continue
            
            if isinstance(element, Role):
                if allowed_roles is None:
                    allowed_roles = []
                
                allowed_roles.append(element.id)
                continue
            
            raise TypeError(f'`allowed_mentions` contains an element of an invalid type: `{element!r}`. The allowed '
                f'types are: `str`, `Role` and any `UserBase` instances.')
        
        
        result = {}
        parse_all_of = None
        
        if allow_replied_user:
            result['replied_user'] = (allow_replied_user > 0)
        
        if allow_everyone:
            if parse_all_of is None:
                parse_all_of = []
                result['parse'] = parse_all_of
            
            parse_all_of.append('everyone')
        
        if allow_users:
            if parse_all_of is None:
                parse_all_of = []
                result['parse'] = parse_all_of
            
            parse_all_of.append('users')
        else:
            if (allowed_users is not None):
                result['users'] = allowed_users
        
        if allow_roles:
            if parse_all_of is None:
                parse_all_of = []
                result['parse'] = parse_all_of
            
            parse_all_of.append('roles')
        else:
            if (allowed_roles is not None):
                result['roles'] = allowed_roles
        
        return result
    
    async def message_delete(self, message, reason=None):
        """
        Deletes the given message.
        
        This method is a coroutine.
        
        Parameters
        ----------
        message : ``Message``
            The message to delete.
        reason : `None` or `str`, Optional
            Shows up at the respective guild's audit logs.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        
        Notes
        -----
        The ratelimit group is different for own or for messages newer than 2 weeks than for message's of others,
        which are older than 2 weeks.
        """
        if message.deleted:
            return
        
        if (message.author is self) or (message.id > int((time_now()-1209590.)*1000.-DISCORD_EPOCH)<<22):
            # own or new
            coro = self.http.message_delete(message.channel.id, message.id, reason)
        else:
            coro = self.http.message_delete_b2wo(message.channel.id, message.id, reason)
        
        await coro
        # If the coro raises, do not switch `message.deleted` to `True`.
        message.deleted = True
        
    
    async def message_delete_multiple(self, messages, reason=None):
        """
        Deletes the given messages. The messages needs to be from the same channel.
        
        This method is a coroutine.
        
        Parameters
        ----------
        messages : `list` of ``Message`` objects
            The messages to delete.
        reason : `None` or `str`, Optional
            Shows up at the respective guild's audit logs.

        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        
        Notes
        -----
        This method uses up 3 different ratelimit groups parallelly to maximalize the deletion speed.
        """
        if not messages:
            return
        
        channel = messages[0].channel
        channel_id = channel.id

        if not isinstance(channel, ChannelGuildBase):
            # Bulk delete is available only at guilds. At private or group channel you can delete only yours tho.
            for message in messages:
                await self.http.message_delete(channel_id, message.id, reason)
            
            return
        
        message_group_new = deque()
        message_group_old = deque()
        message_group_old_own = deque()
        
        bulk_delete_limit = int((time_now()-1209600.)*1000.-DISCORD_EPOCH)<<22 # 2 weeks
        
        for message in messages:
            if message.deleted:
                continue
            
            message_id = message.id
            own = (message.author == self)
            
            if message_id > bulk_delete_limit:
                message_group_new.append((own, message_id),)
                continue
            
            if own:
                group = message_group_old_own
            else:
                group = message_group_old
            
            group.append(message_id)
            continue
        
        tasks = []
        
        delete_mass_task = None
        delete_new_task = None
        delete_old_task = None
        
        while True:
            if delete_mass_task is None:
                message_limit = len(message_group_new)
                
                # 0 is all good, but if it is more, lets check them
                if message_limit:
                    message_ids = []
                    message_count = 0
                    limit = int((time_now()-1209590.)*1000.-DISCORD_EPOCH)<<22 # 2 weeks - 10s
                    
                    while message_group_new:
                        own, message_id = message_group_new.popleft()
                        if message_id > limit:
                            message_ids.append(message_id)
                            message_count += 1
                            if message_count == 100:
                                break
                            continue
                        
                        if (message_id+20971520000) < limit:
                            continue
                        
                        # If the message is really older than the limit, with ingoring the 10 second, then we move it.
                        if own:
                            group = message_group_old_own
                        else:
                            group = message_group_old
                        
                        group.appendleft(message_id)
                        continue
                    
                    if message_count:
                        if message_count == 1:
                            if (delete_new_task is None):
                                message_id = message_ids[0]
                                delete_new_task = Task(self.http.message_delete(channel_id, message_id, None), KOKORO)
                                tasks.append(delete_new_task)
                        else:
                            delete_mass_task = Task(self.http.message_delete_multiple(channel_id,
                                {'messages': message_ids}, None), KOKORO)
                            tasks.append(delete_mass_task)
            
            if delete_old_task is None:
                if message_group_old:
                    message_id = message_group_old.popleft()
                    delete_old_task = Task(self.http.message_delete_b2wo(channel_id, message_id, reason), KOKORO)
                    tasks.append(delete_old_task)
            
            if delete_new_task is None:
                if message_group_new:
                    group = message_group_new
                elif message_group_old_own:
                    group = message_group_old_own
                else:
                    group = None
                
                if (group is not None):
                    message_id = message_group_old_own.popleft()
                    delete_new_task = Task(self.http.message_delete(channel_id, message_id, reason), KOKORO)
                    tasks.append(delete_new_task)
            
            if not tasks:
                # It can happen, that there are no more tasks left,  at that case we check if there is more message
                # left. Only at `message_group_new` can be anymore message, because there is a time intervallum of 10
                # seconds, what we do not move between categories.
                if not message_group_new:
                    break
                
                # We really have at least 1 message at that interval.
                own, message_id = message_group_new.popleft()
                # We will delete that message with old endpoint if not own, to make
                # Sure it will not block the other endpoint for 2 minutes with any chance.
                if own:
                    delete_new_task = Task(self.http.message_delete(channel_id, message_id, None), KOKORO)
                else:
                    delete_old_task = Task(self.http.message_delete_b2wo(channel_id, message_id, None), KOKORO)
                
                tasks.append(delete_old_task)
            
            done, pending = await WaitTillFirst(tasks, KOKORO)
            
            for task in done:
                tasks.remove(task)
                try:
                    result = task.result()
                except (DiscordException, ConnectionError):
                    for task in tasks:
                        task.cancel()
                    raise
                
                if task is delete_mass_task:
                    delete_mass_task = None
                    continue
                
                if task is delete_new_task:
                    delete_new_task = None
                    continue
                
                if task is delete_old_task:
                    delete_old_task = None
                    continue
                 
                # Should not happen
                continue
    
    # deletes from more channel
    async def message_delete_multiple2(self, messages, reason=None):
        """
        Similar to ``.message_delete_multiple`, but it accepts messages from different channels. Groups them up by
        channel and creates ``.message_delete_multiple`` tasks for them. Returns when all the task are finished.
        If any exception was rasised meanwhile, then returns each of them in a list.
        
        This method is a coroutine.
        
        Parameters
        ----------
        messages : `list` of ``Message`` objects
            The messages to delete.
        reason : `None` or `str`, Optional
            Shows up at the respective guild's audit logs.

        Returns
        -------
        exceptions : `None`, `list` of (`ConnectionError` or ``DiscordException``) instances
        """
        delete_system = {}
        for message in messages:
            channel_id = message.channel.id
            try:
                delete_system[channel_id].append(message)
            except KeyError:
                delete_system[channel_id] = [message]
        
        tasks = []
        for messages in delete_system.values():
            task=Task(self.message_delete_multiple(messages, reason), KOKORO)
            tasks.append(task)
        
        await WaitTillAll(tasks, KOKORO)
        
        exceptions = []
        for task in tasks:
            exception = task.exception()
            if exception is None:
                continue
            
            exceptions.append(exceptions)
            if  __debug__:
                task.__silence__()
        
        if exceptions:
            return exceptions
        
    async def message_delete_sequence(self, channel, after=None, before=None, limit=None, filter=None, reason=None):
        """
        Deletes messages between an intervallum determined by `before` and `after`. They can be passed as `int`, or as
        a ``DiscordEntitiy`` instance or as a `datetime` object.
        
        If the client has no `manage_messages` permission at the channel, then returns instantly.
        
        This method is a coroutine.
        
        Parameters
        ----------
        channel : ``ChannelTextBase`` instance
            The channel, where the deletion should take place.
        after : `int`, ``DiscordEntity`` or `datetime`, Optional
            The timestamp after the messages were created, which will be deleted.
        before : `int`, ``DiscordEntity`` or `datetime`, Optional
            The timestamp before the messages were created, which will be deleted.
        limit : `int`, Optional
            The maximal amount of messages to delete.
        filter : `callable`, Optional
            A callable filter, what should accept a message object as argument and return either `True` or `False`.
        reason : `None` or `str`, Optional
            Shows up at the respective guild's audit logs.
        
        Raises
        ------
        TypeError
            If `after` or `before` was passed with an unexpected type.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        
        Notes
        -----
        This method uses up 4 different ratelimit groups parallelly to maximalize the request and the deletion speed.
        """
        # Check permissions
        permissions = channel.cached_permissions_for(self)
        if not permissions.can_manage_messages:
            return
        
        before = 9223372036854775807 if before is None else log_time_converter(before)
        after = 0 if after is None else log_time_converter(after)
        limit = 9223372036854775807 if limit is None else limit
        
        # Check for reversed intervals
        if before < after:
            return
        
        # Check if we are done already
        if limit <= 0:
            return
        
        message_group_new = deque()
        message_group_old = deque()
        message_group_old_own = deque()
        
        # Check if we can request more messages
        if channel.message_history_reached_end or (not permissions.can_read_message_history):
            should_request = False
        else:
            should_request = True
        
        last_message_id = before
        
        messages_ = channel.messages
        if (messages_ is not None) and messages_:
            before_index = message_relativeindex(messages_, before)
            after_index = message_relativeindex(messages_, after)
            if before_index != after_index:
                time_limit = int((time_now()-1209600.)*1000.-DISCORD_EPOCH)<<22
                while True:
                    if before_index == after_index:
                        break
                    
                    message_ = messages_[before_index]
                    before_index += 1
                    
                    if (filter is not None):
                        if not filter(message_):
                            continue
                    
                    last_message_id = message_.id
                    own = (message_.author is self)
                    if last_message_id > time_limit:
                        message_group_new.append((own, last_message_id,),)
                    else:
                        if own:
                            group = message_group_old_own
                        else:
                            group = message_group_old
                        group.append(last_message_id)
                    
                    # Check if we reached the limit
                    limit -= 1
                    if limit:
                        continue
                    
                    should_request = False
                    break
        
        tasks = []
        
        get_mass_task = None
        delete_mass_task = None
        delete_new_task = None
        delete_old_task = None
        
        channel_id = channel.id
        
        while True:
            if should_request and (get_mass_task is None):
                request_data = {
                    'limit': 100,
                    'before': last_message_id,
                        }
                
                get_mass_task = Task(self.http.message_logs(channel_id, request_data), KOKORO)
                tasks.append(get_mass_task)
            
            if (delete_mass_task is None):
                message_limit = len(message_group_new)
                # If there are more messages, we are waiting for other tasks
                if message_limit:
                    time_limit = int((time_now()-1209590.)*1000.-DISCORD_EPOCH)<<22 # 2 weeks -10s
                    collected = 0
                    
                    while True:
                        if collected == message_limit:
                            break
                        
                        if collected == 100:
                            break
                        
                        own, message_id = message_group_new[collected]
                        if message_id < time_limit:
                            break
                        
                        collected += 1
                        continue
                    
                    if collected == 0:
                        pass
                    
                    elif collected == 1:
                        # Delete the message if we dont delete a new message already
                        if (delete_new_task is None):
                            # We collected 1 message -> We cannot use mass delete on this.
                            own, message_id = message_group_new.popleft()
                            delete_new_task = Task(self.http.message_delete(channel_id, message_id, reason=reason),
                                KOKORO)
                            tasks.append(delete_new_task)
                    else:
                        message_ids = []
                        while collected:
                            collected -= 1
                            own, message_id = message_group_new.popleft()
                            message_ids.append(message_id)
                        
                        delete_mass_task = Task(self.http.message_delete_multiple(channel_id, {'messages': message_ids},
                            reason=reason), KOKORO)
                        tasks.append(delete_mass_task)
                    
                    # After we checked what is at this group, lets move the others from it's end, if needed ofc
                    message_limit = len(message_group_new)
                    if message_limit:
                        # timelimit -> 2 week
                        time_limit = time_limit-20971520000
                        
                        while True:
                            # Cannot start at index = len(...), so we instantly do -1
                            message_limit -= 1
                            
                            own, message_id = message_group_new[message_limit]
                            # Check if we should not move -> leave
                            if message_id > time_limit:
                                break
                            
                            del message_group_new[message_limit]
                            if own:
                                group = message_group_old_own
                            else:
                                group = message_group_old
                                
                            group.appendleft(message_id)
                            
                            if message_limit:
                                continue
                            
                            break
            
            if (delete_new_task is None):
                # Check old own messages only, mass delete speed is pretty good by itself.
                if message_group_old_own:
                    message_id = message_group_old_own.popleft()
                    delete_new_task = Task(self.http.message_delete(channel_id, message_id, reason=reason), KOKORO)
                    tasks.append(delete_new_task)
            
            if (delete_old_task is None):
                if message_group_old:
                    message_id = message_group_old.popleft()
                    delete_old_task = Task(self.http.message_delete_b2wo(channel_id, message_id, reason=reason), KOKORO)
                    tasks.append(delete_old_task)
            
            if not tasks:
                # It can happen, that there are no more tasks left, at that case we check if there is more message
                # left. Only at `message_group_new` can be anymore message, because there is a time intervallum of
                # 10 seconds, what we do not move between categories.
                if not message_group_new:
                    break
                
                # We really have at least 1 message at that interval.
                own, message_id = message_group_new.popleft()
                # We will delete that message with old endpoint if not own, to make sure it will not block the other
                # endpoint for 2 minutes with any chance.
                if own:
                    delete_new_task = Task(self.http.message_delete(channel_id, message_id, reason=reason), KOKORO)
                    task = delete_new_task
                else:
                    delete_old_task = Task(self.http.message_delete_b2wo(channel_id, message_id, reason=reason), KOKORO)
                    task = delete_old_task
                
                tasks.append(task)
            
            done, pending = await WaitTillFirst(tasks, KOKORO)
            
            for task in done:
                tasks.remove(task)
                try:
                    result = task.result()
                except:
                    for task in tasks:
                        task.cancel()
                    raise
                
                if task is get_mass_task:
                    get_mass_task = None
                    
                    received_count = len(result)
                    if received_count < 100:
                        should_request = False
                        
                        # We got 0 messages, move on the next task
                        if received_count == 0:
                            continue
                    
                    # We dont really care about the limit, because we check message id when we delete too.
                    time_limit = int((time_now()-1209600.)*1000.-DISCORD_EPOCH)<<22 # 2 weeks
                    
                    for message_data in result:
                        if (filter is None):
                            last_message_id = int(message_data['id'])
    
                            # Did we reach the after limit?
                            if last_message_id < after:
                                should_request = False
                                break
                            
                            # If filter is `None`, we just have to decide, if we were the author or nope.
                            
                            # Try to get user id, first start it with trying to get author data. The default author_id
                            # will be 0, because thats sure not the id of the client.
                            try:
                                author_data = message_data['author']
                            except KeyError:
                                author_id = 0
                            else:
                                # If we have author data, lets select the user's data from it
                                try:
                                    user_data = author_data['user']
                                except KeyError:
                                    user_data = author_data
                                
                                try:
                                    author_id = user_data['id']
                                except KeyError:
                                    author_id = 0
                                else:
                                    author_id = int(author_id)
                        else:
                            message_ = channel._create_unknown_message(message_data)
                            last_message_id = message_.id
                            
                            # Did we reach the after limit?
                            if last_message_id < after:
                                should_request = False
                                break
                            
                            if not filter(message_):
                                continue
                            
                            author_id = message_.author.id
                        
                        own = (author_id == self.id)
                        
                        if last_message_id > time_limit:
                            message_group_new.append((own, last_message_id,),)
                        else:
                            if own:
                                group = message_group_old_own
                            else:
                                group = message_group_old
                            
                            group.append(last_message_id)
                        
                        # Did we reach the amount limit?
                        limit -= 1
                        if limit:
                            continue
                        
                        should_request = False
                        break
                
                if task is delete_mass_task:
                    delete_mass_task = None
                    continue
                
                if task is delete_new_task:
                    delete_new_task = None
                    continue
                
                if task is delete_old_task:
                    delete_old_task = None
                    continue
                 
                # Should not happen
                continue
    
    async def multi_client_message_delete_sequence(self, channel, after=None, before=None, limit=None, filter=None,
            reason=None):
        """
        Deletes messages between an intervallum determined by `before` and `after`. They can be passed as `int`, or as
        a ``DiscordEntitiy`` instance or as a `datetime` object.
        
        Not like ``.message_delete_sequence``, this method uses up all he clients at the respective channel to delete
        messages an not only the one from what it was called from.
        
        If non of the clients have `manage_messages` permission, then returns instantly.
        
        This method is a coroutine.
        
        Parameters
        ----------
        channel : ``ChannelTextBase`` instance
            The channel, where the deletion should take place.
        after : `int`, ``DiscordEntity`` or `datetime`, Optional
            The timestamp after the messages were created, which will be deleted.
        before : `int`, ``DiscordEntity`` or `datetime`, Optional
            The timestamp before the messages were created, which will be deleted.
        limit : `int`, Optional
            The maximal amount of messages to delete.
        filter : `callable`, Optional
            A callable filter, what should accept a message object as argument and return either `True` or `False`.
        reason : `None` or `str`, Optional
            Shows up at the respective guild's audit logs.
        
        Raises
        ------
        TypeError
            If `after` or `before` was passed with an unexpected type.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        
        Notes
        -----
        This method uses up to 4 different endpoint groups too as ``.message_delete_sequence``, but tries to
        pararellize the them between more clients as well.
        """
        # Check permissions
        sharders = []
        
        for client in channel.clients:
            sharder = MultiClientMessageDeleteSequenceSharder(client, channel)
            if sharder is None:
                continue
            
            sharders.append(sharder)
        
        if not sharders:
            return
        
        for sharder in sharders:
            if sharder.can_manage_messages:
                break
        else:
            return
        
        before = 9223372036854775807 if before is None else log_time_converter(before)
        after = 0 if after is None else log_time_converter(after)
        limit = 9223372036854775807 if limit is None else limit
        
        # Check for reversed intervals
        if before < after:
            return
        
        # Check if we are done already
        if limit <= 0:
            return
        
        message_group_new = deque()
        message_group_old = deque()
        message_group_old_own = deque()
        
        # Check if we can request more messages
        if channel.message_history_reached_end:
            should_request = False
        else:
            for sharder in sharders:
                if sharder.can_read_message_history:
                    should_request = True
                    break
            else:
                should_request = False
        
        last_message_id = before
        
        is_own_getter = {}
        for index in range(len(sharders)):
            is_own_getter[sharders[index].client.id] = index
        
        messages_ = channel.messages
        if (messages_ is not None) and messages_:
            before_index = message_relativeindex(messages_, before)
            after_index = message_relativeindex(messages_, after)
            if before_index != after_index:
                time_limit = int((time_now()-1209600.)*1000.-DISCORD_EPOCH)<<22
                while True:
                    if before_index == after_index:
                        break
                    
                    message_ = messages_[before_index]
                    before_index += 1
                    
                    if (filter is not None):
                        if not filter(message_):
                            continue
                    
                    last_message_id = message_.id
                    whos = is_own_getter.get(message_.author.id, -1)
                    if last_message_id > time_limit:
                        message_group_new.append((whos, last_message_id,),)
                    else:
                        if whos == -1:
                            message_group_old.append(last_message_id)
                        else:
                            message_group_old_own.append((whos, last_message_id,),)
                    
                    # Check if we reached the limit
                    limit -= 1
                    if limit:
                        continue
                    
                    should_request = False
                    break
        
        tasks = []
        # Handle requesting together, since we need to know, till where the last request yielded.
        get_mass_task = None
        # Loop the sharders when requesting, so ratelimits are used up.
        get_mass_task_next = 0
        
        channel_id = channel.id
        
        while True:
            if should_request and (get_mass_task is None):
                # Will break since `should_request` is set to `True` only if at least of the sharders have
                # `read_message_history` permission
                while True:
                    if get_mass_task_next >= len(sharders):
                        get_mass_task_next = 0
                    
                    sharder = sharders[get_mass_task_next]
                    if sharder.can_read_message_history:
                        break
                    
                    get_mass_task_next += 1
                    continue
                
                request_data = {
                    'limit': 100,
                    'before': last_message_id,
                        }
                
                get_mass_task = Task(sharder.client.http.message_logs(channel_id, request_data), KOKORO)
                tasks.append(get_mass_task)
            
            for sharder in sharders:
                if (sharder.can_manage_messages) and (sharder.delete_mass_task is None):
                    message_limit = len(message_group_new)
                    # If there are more messages, we are waiting for other tasks
                    if message_limit:
                        time_limit = int((time_now()-1209590.)*1000.-DISCORD_EPOCH)<<22 # 2 weeks -10s
                        collected = 0
                        
                        while True:
                            if collected == message_limit:
                                break
                            
                            if collected == 100:
                                break
                            
                            whos, message_id = message_group_new[collected]
                            if message_id < time_limit:
                                break
                            
                            collected += 1
                            continue
                        
                        if collected == 0:
                            pass
                        
                        elif collected == 1:
                            # Delete the message if we dont delete a new message already
                            for sub_sharder in sharders:
                                if (sub_sharder.can_manage_messages) and (sharder.delete_new_task is None):
                                    # We collected 1 message -> We cannot use mass delete on this.
                                    whos, message_id = message_group_new.popleft()
                                    delete_new_task = Task(sub_sharder.client.http.message_delete(channel_id,
                                        message_id, reason=reason), KOKORO)
                                    sub_sharder.delete_new_task = delete_new_task
                                    tasks.append(delete_new_task)
                                    break
                        else:
                            message_ids = []
                            while collected:
                                collected -= 1
                                whos, message_id = message_group_new.popleft()
                                message_ids.append(message_id)
                            
                            delete_mass_task = Task(sharder.client.http.message_delete_multiple(channel_id,
                                {'messages': message_ids}, reason=reason), KOKORO)
                            sharder.delete_mass_task = delete_mass_task
                            tasks.append(delete_mass_task)
                        
                        # After we checked what is at this group, lets move the others from it's end, if needed ofc
                        message_limit = len(message_group_new)
                        if message_limit:
                            # timelimit -> 2 week
                            time_limit = time_limit-20971520000
                            
                            while True:
                                # Cannot start at index = len(...), so we instantly do -1
                                message_limit -= 1
                                
                                whos, message_id = message_group_new[message_limit]
                                # Check if we should not move -> leave
                                if message_id > time_limit:
                                    break
                                
                                del message_group_new[message_limit]
                                if whos == -1:
                                    message_group_old.appendleft(message_id)
                                else:
                                    message_group_old_own.appendleft((whos, message_group_old,),)
                                
                                if message_limit:
                                    continue
                                
                                break
            
            # Check old own messages only, mass delete speed is pretty good by itself.
            if message_group_old_own:
                # Check who's is the last message. And delete with it. These speed is pretty fast.
                # I doubt it needs further speedup, since deleting not own messages are the bottleneck of message
                # deletions.
                whos, message_id = message_group_old_own[0]
                sharder = sharders[whos]
                if sharder.delete_new_task is None:
                    del message_group_old_own[0]
                    delete_new_task = Task(sharder.client.http.message_delete(channel_id, message_id,
                        reason=reason), KOKORO)
                    sharder.delete_new_task = delete_new_task
                    tasks.append(delete_new_task)
            
            if message_group_old:
                for sharder in sharders:
                    if (sharder.delete_old_task is None):
                        message_id = message_group_old.popleft()
                        delete_old_task = Task(sharder.client.http.message_delete_b2wo(channel_id, message_id,
                            reason=reason), KOKORO)
                        sharder.delete_old_task = delete_old_task
                        tasks.append(delete_old_task)
                        
                        if not message_group_old:
                            break
            
            if not tasks:
                # It can happen, that there are no more tasks left, at that case we check if there is more message
                # left. Only at `message_group_new` can be anymore message, because there is a time intervallum of
                # 10 seconds, what we do not move between categories.
                if not message_group_new:
                    break
                
                # We really have at least 1 message at that interval.
                whos, message_id = message_group_new.popleft()
                # We will delete that message with old endpoint if not own, to make sure it will not block the other
                # endpoint for 2 minutes with any chance.
                if whos == -1:
                    for sharder in sharders:
                        if sharder.can_manage_messages:
                            task = Task(sharder.client.http.message_delete_b2wo(channel_id, message_id,
                                reason=reason), KOKORO)
                            sharder.delete_old_task = task
                            break
                else:
                    sharder = sharders[whos]
                    task = Task(sharder.client.http.message_delete(channel_id, message_id, reason=reason), KOKORO)
                    sharder.delete_new_task = task
                
                tasks.append(task)
            
            done, pending = await WaitTillFirst(tasks, KOKORO)
            
            for task in done:
                tasks.remove(task)
                try:
                    result = task.result()
                except:
                    for task in tasks:
                        task.cancel()
                    raise
                
                if task is get_mass_task:
                    get_mass_task = None
                    
                    received_count = len(result)
                    if received_count < 100:
                        should_request = False
                        
                        # We got 0 messages, move on the next task
                        if received_count == 0:
                            continue
                    
                    # We dont really care about the limit, because we check message id when we delete too.
                    time_limit = int((time_now()-1209600.)*1000.-DISCORD_EPOCH)<<22 # 2 weeks
                    
                    for message_data in result:
                        if (filter is None):
                            last_message_id = int(message_data['id'])
                            
                            # Did we reach the after limit?
                            if last_message_id < after:
                                should_request = False
                                break
                            
                            # If filter is `None`, we just have to decide, if we were the author or nope.
                            
                            # Try to get user id, first start it with trying to get author data. The default author_id
                            # will be 0, because thats sure not the id of the client.
                            try:
                                author_data = message_data['author']
                            except KeyError:
                                author_id = 0
                            else:
                                # If we have author data, lets select the user's data from it
                                try:
                                    user_data = author_data['user']
                                except KeyError:
                                    user_data = author_data
                                
                                try:
                                    author_id = user_data['id']
                                except KeyError:
                                    author_id = 0
                                else:
                                    author_id = int(author_id)
                        else:
                            message_ = channel._create_unknown_message(message_data)
                            last_message_id = message_.id
                            
                            # Did we reach the after limit?
                            if last_message_id < after:
                                should_request = False
                                break
                            
                            if not filter(message_):
                                continue
                            
                            author_id = message_.author.id
                        
                        whos = is_own_getter.get(author_id, -1)
                        
                        if last_message_id > time_limit:
                            message_group_new.append((whos, last_message_id,),)
                        else:
                            if whos == -1:
                                message_group_old.append(last_message_id)
                            else:
                                message_group_old_own.append((whos, last_message_id,),)
                        
                        # Did we reach the amount limit?
                        limit -= 1
                        if limit:
                            continue
                        
                        should_request = False
                        break
                
                for sharder in sharders:
                    if task is sharder.delete_mass_task:
                        sharder.delete_mass_task = None
                        break
                    
                    if task is sharder.delete_new_task:
                        sharder.delete_new_task = None
                        break
                    
                    if task is sharder.delete_old_task:
                        sharder.delete_old_task = None
                        break
                
                # Else case should happen.
                continue
    
    async def message_edit(self, message, content=..., *, embed=..., allowed_mentions=..., suppress=...):
        """
        Edits the given `message`.
        
        This method is a coroutine.
        
        Parameters
        ----------
        message : ``Message``, ``MessageRepr``
            The message to edit.
        content : `str`, ``EmbedBase`` or `Any`, Optional
            The new content of the message.
            
            If given as `str` then the message's content will be edited with it. If given as any non ``EmbedBase``
            instance, then it will be cased to string first.
            
            By passing it as empty string, you can remove the message's content.
            
            If given as ``EmbedBase`` instance, then the message's embeds will be edited with it.
        embed : `None`, ``EmbedBase`` instance or `list` of ``EmbedBase`` instances, Optional
            The new embedded content of the message. By passing it as `None`, you can remove the old.
            
            If `embed` and `content` parameters are both given as  ``EmbedBase`` instance, then `TypeError` is raised.
            
            If embeds are given as a list, then the first embed is picked up.
        allowed_mentions : `None`,  `str`, ``UserBase``, ``Role``, `list` of (`str`, ``UserBase``, ``Role`` ), Optional
            Which user or role can the message ping (or everyone). Check ``._parse_allowed_mentions``
            for details.
        suppress : `bool`, Optional
            Whether the message's embeds should be suppressed or unsuppressed.
        
        Raises
        ------
        TypeError
            - If `embed` was given as `list`, but it contains not only ``EmbedBase`` instances.
            - If `allowed_mentions` contains an element of invalid type.
            - `content` parameter was given as ``EmbedBase`` instance, meanwhile `embed` parameter was given as well.
            - If `message`'s type is incorrect.
        ValueError
            If `allowed_mentions` contains an element of invalid type.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            If the message was not send by the client.
        See Also
        --------
        - ``.message_suppress_embeds`` : For suppressing only the embeds of the message.
        - ``.webhook_message_edit`` : Editing messages sent by webhooks.
        
        Notes
        -----
        Do not updates he given message object, so dispatch event parsers can still calculate differences when received.
        """
        
        # Message check order
        # 1.: Message
        # 2.: MessageRepr
        #
        # Message cannot be detected by id, only cached ones, so ignore that case.
        
        if isinstance(message, Message):
            if __debug__:
                if message.author.id != self.id:
                    raise AssertionError('The message was not send by the client.')
            message_id = message.id
        elif isinstance(message, MessageRepr):
            message_id = message.id
        elif message is None:
            raise TypeError('`message` was given as `None`. Make sure to use `Client.message_create` with giving '
                'content and using a cached channel.')
        else:
            raise TypeError(f'`message` should have be given as `Message` or as `MessageRepr`, got '
                f'`{message.__class__.__name__}`.')
        
        # Embed check order:
        # 1.: Elipsis
        # 2.: None
        # 3.: Embed
        # 4.: list of Embed -> embed[0] or None
        # 5.: raise
        
        if embed is ...:
            pass
        elif embed is None:
            pass
        elif isinstance(embed, EmbedBase):
            pass
        elif isinstance(embed, (list, tuple)):
            if embed:
                if __debug__:
                    for index, element in enumerate(embed):
                        if isinstance(element, EmbedBase):
                            continue
                        
                        raise TypeError(f'`embed` was given as a `list`, but it\'s element under index `{index}` '
                            f'is not `{EmbedBase.__name__}` instance, but {embed_element.__class__.__name__}`, got: '
                            f'{embed.__class__.__name__}.')
                
                embed = embed[0]
            else:
                embed = None
        else:
            raise TypeError(f'`embed` was not given as `{EmbedBase.__name__}` instance, neither as a list of '
                f'{EmbedBase.__name__} instances, got {embed.__class__.__name__}.')
        
        # Content check order:
        # 1.: Elipsis
        # 2.: None
        # 3.: str
        # 4.: Embed -> embed = content
        # 5.: list of Embed -> embed = content[0]
        # 6.: object -> str(content)
        
        if content is ...:
            pass
        elif content is None:
            content = ''
        elif isinstance(content, str):
            pass
        elif isinstance(content, EmbedBase):
            if __debug__:
                if (embed is not ...):
                    raise TypeError(f'Multiple embeds were given, got content={content!r}, embed={embed!r}.')
            
            embed = content
            content = ...
        else:
            # Check for list of embeds as well.
            if isinstance(content, (list, tuple)):
                if content:
                    for element in content:
                        if isinstance(element, EmbedBase):
                            continue
                        
                        is_list_of_embeds = False
                        break
                    else:
                        is_list_of_embeds = True
                else:
                    is_list_of_embeds = False
            else:
                is_list_of_embeds = False
            
            if is_list_of_embeds:
                if __debug__:
                    if (embed is not ...):
                        raise TypeError(f'Multiple embeds were given, got content={content!r}, embed={embed!r}.')
                
                embed = content[0]
                content = ...
            else:
                content = str(content)
        
        # Build payload
        message_data = {}
        
        if (content is not ...):
            message_data['content'] = content
        
        if (embed is not ...):
            if (embed is not None):
                embed = embed.to_data()
            
            message_data['embed'] = embed
        
        if (allowed_mentions is not ...):
            message_data['allowed_mentions'] = self._parse_allowed_mentions(allowed_mentions)
        
        if (suppress is not ...):
            flags = message.flags
            if suppress:
                flags |= 0b00000100
            else:
                flags &= 0b11111011
            message_data['flags'] = flags
        
        await self.http.message_edit(message.channel.id, message_id, message_data)
    
    async def message_suppress_embeds(self, message, suppress=True):
        """
        Suppresses or unsuppressed the given message's embeds.
        
        This method is a coroutine.
        
        Parameters
        ----------
        message : ``Message`` object
            The message, what's embeds will be (un)suppressed.
        suppress : `bool`, Optional
            Whether the message's embeds would be suppressed or unsuppressed.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        await self.http.message_suppress_embeds(message.channel.id, message.id, {'suppress': suppress})
    
    async def message_crosspost(self, message):
        """
        Crossposts the given message. The message's channel must be an announcements (type 5) channel.
        
        This method is a coroutine.
        
        Parameters
        ----------
        message : ``Message`` object
            The message to crosspost.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        await self.http.message_crosspost(message.channel.id, message.id)
    
    async def message_pin(self, message):
        """
        Pins the given message.
        
        This method is a coroutine.
        
        Parameters
        ----------
        message : ``Message`` object
            The message to pin.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        await self.http.message_pin(message.channel.id, message.id)
    
    async def message_unpin(self, message):
        """
        Unpins the given message.
        
        This method is a coroutine.
        
        Parameters
        ----------
        message : ``Message`` object
            The message to unpin.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        await self.http.message_unpin(message.channel.id, message.id)

    async def channel_pins(self, channel):
        """
        Returns the pinned messages at the given channel.
        
        This method is a coroutine.
        
        Parameters
        ----------
        channel : ``ChannelTextBase`` or `int` instance
            The channel from were the pinned messages will be requested.
        
        Returns
        -------
        messages : `list` of ``Message`` objects
            The pinned messages at the given channel.
        
        Raises
        ------
        TypeError
            If `channel` was not given neither as ``ChannelTextBase`` nor `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        if isinstance(channel, ChannelTextBase):
            channel_id = channel.id
        
        else:
            channel_id = maybe_snowflake(channel)
            if channel_id is None:
                raise TypeError(f'`channel` can be given as `{ChannelTextBase.__name__}` or `int` instance, got '
                    f'{channel.__class__.__name__}.')
            
            channel = CHANNELS.get(channel_id)
        
        data = await self.http.channel_pins(channel_id)
        
        if channel is None:
            channel = await self._maybe_get_channel(channel_id)
        
        return [channel._create_unknown_message(message_data) for message_data in data]


    async def _load_messages_till(self, channel, index):
        """
        An internal function to load the messages at the given channel till the given index. Should not be called if
        the channel reached it's message history's end.
        
        This method is a coroutine.
        
        Parameters
        ----------
        channel : ``ChannelTextBase`` instance
            The channel from where the messages will be requested.
        index : `int`
            Till which index the messages should be requested at the given channel.
        
        Returns
        -------
        result_state : `int`
            can return the following variables describing a state:
            
            +-----------+---------------------------------------------------------------------------+
            | Value     | Description                                                               |
            +-----------+---------------------------------------------------------------------------+
            | 0         | Success.                                                                  |
            +-----------+---------------------------------------------------------------------------+
            | 1         | `index` could not be reached, there is no more messages at the channel.   |
            +-----------+---------------------------------------------------------------------------+
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        while True:
            messages = channel.messages
            if messages is None:
                ln = 0
            else:
                ln = len(channel.messages)
            
            loadto = index-ln
            
            # we want to load it till the exact index, so if `loadto` is `0`, thats not enough!
            if loadto < 0:
                result_state = 0
                break
            
            if loadto < 98:
                planned = loadto+2
            else:
                planned = 100
            
            if ln:
                result = await self.message_logs(channel, planned, before=messages[ln-2].id)
            else:
                result = await self.message_logs_fromzero(channel, planned)
            
            if len(result) < planned:
                channel.message_history_reached_end = True
                result_state = 1
                break
        
        channel._turn_message_keep_limit_on_at += index
        return result_state
    
    async def message_at_index(self, channel, index):
        """
        Returns the message at the given channel at the specific index. Can be used to load `index` amount of messages
        at the channel.
        
        This method is a coroutine.
        
        Parameters
        ----------
        channel : ``ChannelTextBase`` or `int` instance.
            The channel from were the messages will be requested.
        index : `int`
            The index of the target message.
        
        Returns
        -------
        message : ``Message`` object
        
        Raises
        ------
        TypeError
            If `channel` was not given neither as ``ChannelTextBase`` nor `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            - If `index` was not given as `int` instance.
            - If `index` is out of range [0:].
        """
        if __debug__:
            if not isinstance(index, int):
                raise AssertionError(f'`index` can be given as `int` instance, got {index.__class__.__name__}.')
            
            if index < 0:
                raise AssertionError(f'`index` is out from the expected [0:] range, got {index!r}.')
    
        if isinstance(channel, ChannelTextBase):
            pass
        else:
            channel_id = maybe_snowflake(channel)
            if channel_id is None:
                raise TypeError(f'`channel` can be given as `{ChannelTextBase.__name__}` or `int` instance, got '
                    f'{channel.__class__.__name__}.')
            
            channel = CHANNELS.get(channel_id)
            
            if channel is None:
                messages = await self.message_logs_fromzero(channel_id, min(index+1, 100))
                
                if messages:
                    channel = messages[0].channel
                else:
                    raise IndexError(index)
        
        messages = channel.messages
        if (messages is not None) and (index < len(messages)):
            raise IndexError(index)
        
        if channel.message_history_reached_end:
            raise IndexError(index)
        
        if await self._load_messages_till(channel, index):
            raise IndexError(index)
        
        # access it again, because it might be modified
        messages = channel.messages
        if messages is None:
            raise IndexError(index)
        
        return messages[index]
    
    async def messages_in_range(self, channel, start=0, end=100):
        """
        Returns a list of the message between the `start` - `end` area. If the client has no permission to request
        messages, or there are no messages at the given area returns an empty list.
        
        This method is a coroutine.
        
        Parameters
        ----------
        channel : ``ChannelTextBase`` or `int` instance
            The channel from were the messages will be requested.
        start : `int`, Optional
            The first message's index at the channel to be requested. Defaults to `0`.
        end : `int`
            The last message's index at the channel to be requested. Deffaults to `100`.
        
        Returns
        -------
        messages : `list` of ``Message`` objects
        
        Raises
        ------
        TypeError
            If `channel` was not given neither as ``ChannelTextBase`` nor `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            - If `start` was not given as `int` instance.
            - If `start` is out of range [0:].
            - If `end` was not given as `int` instance.
            - If `end` is out of range [0:].
        """
        if __debug__:
            if not isinstance(start, int):
                raise AssertionError(f'`start` can be given as `int` instance, got {start.__class__.__name__}.')
            
            if start < 0:
                raise AssertionError(f'`start` is out from the expected [0:] range, got {start!r}.')
        
            if not isinstance(end, int):
                raise AssertionError(f'`end` can be given as `int` instance, got {end.__class__.__name__}.')
            
            if end < 0:
                raise AssertionError(f'`end` is out from the expected [0:] range, got {end!r}.')
        
        if isinstance(channel, ChannelTextBase):
            pass
        else:
            channel_id = maybe_snowflake(channel)
            if channel_id is None:
                raise TypeError(f'`channel` can be given as `{ChannelTextBase.__name__}` or `int` instance, got '
                    f'{channel.__class__.__name__}.')
            
            channel = CHANNELS.get(channel_id)
            
            if channel is None:
                messages = await self.message_logs_fromzero(channel_id, min(end+1, 100))
                
                if messages:
                    channel = messages[0].channel
                else:
                    return []
        
        if end <= start:
            return []
        
        messages = channel.messages
        if messages is None:
            ln = 0
        else:
            ln = len(messages)
        
        if (end >= ln) and (not channel.message_history_reached_end) and \
               channel.cached_permissions_for(self).can_read_message_history:
            
            try:
                await self._load_messages_till(channel, end)
            except BaseException as err:
                if isinstance(err, DiscordException) and err.code in (
                    ERROR_CODES.unknown_message, # message deleted
                    ERROR_CODES.unknown_channel, # message's channel deleted
                    ERROR_CODES.invalid_access, # client removed
                    ERROR_CODES.invalid_permissions, # permissions changed meanwhile
                    ERROR_CODES.invalid_message_send_user, # user has dm-s disallowed
                        ):
                    pass
                else:
                    raise
        
        result = []
        messages = channel.messages
        if (messages is not None):
            for index in range(start, min(end, len(messages))):
                result.append(messages[index])
        
        return result
    
    async def message_iterator(self, channel, chunksize=99):
        """
        Returns an asynchronous message iterator over the given text channel.
        
        This method is a coroutine.
        
        Parameters
        ----------
        channel : ``ChannelTextBase``  or `int` instance
            The channel from were the messages will be requested.
        chunksize : `int`, Optional
            The amount of messages to request when the currently loaded history is exhausted. For message chaining
            it is preferably `99`.
        
        Returns
        -------
        message_iterator : ``MessageIterator``
        
        Raises
        ------
        TypeError
            If `channel` was not given neither as ``ChannelTextBase`` nor `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            - If `chunksize` was not given as `int` instance.
            - If `chunksize` is out of range [1:].
        """
        return await MessageIterator(self, channel, chunksize)
    
    async def typing(self, channel):
        """
        Sends a typing event to the given channel.
        
        This method is a coroutine.
        
        Parameters
        ----------
        channel : ``ChannelTextBase`` or `int` instance
            The channel where typing will be triggered.
        
        Raises
        ------
        TypeError
            If `channel` was not given neither as ``ChannelTextBase`` nor `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        
        Notes
        -----
        The client will be shown up as typing for 8 seconds, or till it sends a message at the respective channel.
        """
        if isinstance(channel, ChannelTextBase):
            channel_id = channel.id
        else:
            channel_id = maybe_snowflake(channel)
            if channel_id is None:
                raise TypeError(f'`channel` can be given as `{ChannelTextBase.__name__}` instance, got'
                    f'{channel.__class__.__name__}.')
        
        await self.http.typing(channel_id)

    # With context
    def keep_typing(self, channel, timeout=300.):
        """
        Returns a ``Typer`` object, what will keep sending typing events at the given channel. It can be used as a
        context manager.
        
        Parameters
        ----------
        channel ``ChannelTextBase`` or `int` instance
            The channel where typing will be triggered.
        timeout : `float`, Optional
            The maximal duration for the ``Typer`` to keep typing.
        
        Returns
        -------
        typer : ``Typer``
        
        Raises
        ------
        TypeError
            If `channel` was not given neither as ``ChannelTextBase`` nor `int` instance.
        """
        if isinstance(channel, ChannelTextBase):
            channel_id = channel.id
        else:
            channel_id = maybe_snowflake(channel)
            if channel_id is None:
                raise TypeError(f'`channel` can be given as `{ChannelTextBase.__name__}` instance, got'
                    f'{channel.__class__.__name__}.')
        
        return Typer(self, channel_id, timeout)
    
    # Reactions:
    
    async def reaction_add(self, message, emoji):
        """
        Adds a reaction on the given message.
        
        This method is a coroutine.
        
        Parameters
        ----------
        message : ``Message``, ``MessageRepr`` or ``MessageReference``
            The message on which the reaction will be put on.
        emoji : ``Emoji``
            The emoji to react with
        
        Raises
        ------
        TypeError
            If `message` was not given neither as ``Message``, ``MessageRepr`` nor ``MessageReference`` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        if isinstance(message, Message):
            message_id = message.id
            channel_id = message.channel.id
        elif isinstance(message, MessageRepr):
            message_id = message.id
            channel_id = message.channel.id
        elif isinstance(message, MessageReference):
            channel_id = message.channel_id
            message_id = message.message_id
        else:
            raise TypeError(f'`message` can be given as  `{Message.__name__}`, `{MessageRepr.__name__}` or as '
                f'`{MessageReference.__name__}` instance, got {message!r}.')
        
        await self.http.reaction_add(channel_id, message_id, emoji.as_reaction)
    
    async def reaction_delete(self, message, emoji, user):
        """
        Removes the specified reaction of the user from the given message.
        
        This method is a coroutine.
        
        Parameters
        ----------
        message : ``Message``, ``MessageRepr`` or ``MessageReference``
            The message from which the reaction will be removed.
        emoji : ``Emoji``
            The emoji to remove.
        user : ``Client``, ``User`` or `int` instance
            The user, who's reaction will be removed.
        
        Raises
        ------
        TypeError
            - If `message` was not given neither as ``Message``, ``MessageRepr`` nor ``MessageReference`` instance.
            - If `user` was not given neither as ``User``, ``Client`` nor `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        if isinstance(message, Message):
            message_id = message.id
            channel_id = message.channel.id
        elif isinstance(message, MessageRepr):
            message_id = message.id
            channel_id = message.channel.id
        elif isinstance(message, MessageReference):
            channel_id = message.channel_id
            message_id = message.message_id
        else:
            raise TypeError(f'`message` can be given as  `{Message.__name__}`, `{MessageRepr.__name__}` or as '
                f'`{MessageReference.__name__}` instance, got {message!r}.')
        
        if isinstance(user, (User, Client)):
            user_id = user.id
        else:
            user_id = maybe_snowflake(user)
            if user_id is None:
                raise TypeError(f'`user` can be given as `{User.__name__}`, `{Client.__name__}` or `int` instance, '
                    f'got {user.__class__.__name__}.')
        
        if user_id == self.id:
            await self.http.reaction_delete_own(channel_id, message_id, emoji.as_reaction)
        else:
            await self.http.reaction_delete(channel_id, message_id, emoji.as_reaction, user_id)
    
    async def reaction_delete_emoji(self, message, emoji):
        """
        Removes all the reaction of the specified emoji from the given message.
        
        This method is a coroutine.
        
        Parameters
        ----------
        message : ``Message``, ``MessageRepr`` or ``MessageReference``
            The message from which the reactions will be removed.
        emoji : ``Emoji`` object
            The reaction to remove.
        
        Raises
        ------
        TypeError
            If `message` was not given neither as ``Message``, ``MessageRepr`` nor ``MessageReference`` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        if isinstance(message, Message):
            message_id = message.id
            channel_id = message.channel.id
        elif isinstance(message, MessageRepr):
            message_id = message.id
            channel_id = message.channel.id
        elif isinstance(message, MessageReference):
            channel_id = message.channel_id
            message_id = message.message_id
        else:
            raise TypeError(f'`message` can be given as  `{Message.__name__}`, `{MessageRepr.__name__}` or as '
                f'`{MessageReference.__name__}` instance, got {message!r}.')
        
        await self.http.reaction_delete_emoji(channel_id, message_id, emoji.as_reaction)
    
    async def reaction_delete_own(self, message, emoji):
        """
        Removes the specified reaction of the client from the given message.
        
        This method is a coroutine.
        
        Parameters
        ----------
        message : ``Message``, ``MessageRepr`` or ``MessageReference``
            The message from which the reaction will be removed.
        emoji : ``Emoji`` object
            The emoji to remove.
        
        Raises
        ------
        TypeError
            If `message` was not given neither as ``Message``, ``MessageRepr`` nor ``MessageReference`` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        if isinstance(message, Message):
            message_id = message.id
            channel_id = message.channel.id
        elif isinstance(message, MessageRepr):
            message_id = message.id
            channel_id = message.channel.id
        elif isinstance(message, MessageReference):
            channel_id = message.channel_id
            message_id = message.message_id
        else:
            raise TypeError(f'`message` can be given as  `{Message.__name__}`, `{MessageRepr.__name__}` or as '
                f'`{MessageReference.__name__}` instance, got {message!r}.')
        
        await self.http.reaction_delete_own(channel_id, message_id, emoji.as_reaction)
    
    async def reaction_clear(self, message):
        """
        Removes all the reactions from the given message.
        
        This method is a coroutine.
        
        Parameters
        ----------
        message : ``Message``, ``MessageRepr`` or ``MessageReference``
            The message from which the reactions will be cleared.
        
        Raises
        ------
        TypeError
            If `message` was not given neither as ``Message``, ``MessageRepr`` nor ``MessageReference`` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        if isinstance(message, Message):
            message_id = message.id
            channel_id = message.channel.id
        elif isinstance(message, MessageRepr):
            message_id = message.id
            channel_id = message.channel.id
        elif isinstance(message, MessageReference):
            channel_id = message.channel_id
            message_id = message.message_id
        else:
            raise TypeError(f'`message` can be given as  `{Message.__name__}`, `{MessageRepr.__name__}` or as '
                f'`{MessageReference.__name__}` instance, got {message!r}.')
        
        await self.http.reaction_clear(channel_id, message_id)
    
    # before is not supported
    
    async def reaction_users(self, message, emoji, limit=None, after=None):
        """
        Requests the users, who reacted on the given message with the given emoji.
        
        If the message has no reacters at all or no reacters with that emoji, returns an empty list. If we know the
        emoji's every reacters we query the parameters from that.
        
        This method is a coroutine.
        
        Parameters
        ----------
        message : ``Message``, ``MessageRepr`` or ``MessageReference``
            The message, what's reactions will be requested.
        emoji : ``Emoji`` object
            The emoji, what's reacters will be requested.
        limit : `None` `int`
            The amount of users to request. Can be in range [1:100]. Defaults to 25 by Discord.
        after : `int`, ``DiscordEntity`` or `datetime`, Optional
            The timestamp after the message's reacters were created.
        
        Returns
        -------
        users : `list` of (``Client``, ``User``)
        
        Raises
        ------
        TypeError
            - If `message` was not given neither as ``Message``, ``MessageRepr`` nor ``MessageReference`` instance.
            - If `after` was passed with an unexpected type.
        ValueError
            If `limit` was passed as `int`, but is under `1` or over `100`.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            - If `limit` was not given neither as `None` or `int` instance.
            - If `limit` is out of range [1:100]
        
        Notes
        -----
        `before` argument is not supported by Discord.
        """
        if limit is None:
            limit = 25
        else:
            if __debug__:
                if not isinstance(limit, int):
                    raise AssertionError(f'`limit` can be given as `None` or `int` instance, got '
                        f'{limit.__class__.__name__}.')
                
                if limit < 1 or limit > 100:
                    raise AssertionError(f'`limit` can be between in range [1:100], got `{limit!r}`.')
        
        if isinstance(message, Message):
            message_id = message.id
            channel_id = message.channel.id
            reactions = message.reactions
        elif isinstance(message, MessageRepr):
            message_id = message.id
            channel_id = message.channel.id
            reactions = None
        elif isinstance(message, MessageReference):
            channel_id = message.channel_id
            message_id = message.message_id
            reactions = None
        else:
            raise TypeError(f'`message` can be given as  `{Message.__name__}`, `{MessageRepr.__name__}` or as '
                f'`{MessageReference.__name__}` instance, got {message!r}.')
        
        if (reactions is not None):
            try:
                line = reactions[emoji]
            except KeyError:
                return []
            
            if not line.unknown:
                after = 0 if after is None else log_time_converter(after)
                # before = 9223372036854775807 if before is None else log_time_converter(before)
                users = line.filter_after(limit, after)
                return users
        
        data = {}
        if limit != 25:
            data['limit'] = limit
        
        if (after is not None):
            data['after'] = log_time_converter(after)
        
        # if (before is not None):
        #     data['before'] = log_time_converter(before)
        
        data = await self.http.reaction_users(channel_id, message_id, emoji.as_reaction, data)
        
        users = [User(user_data) for user_data in data]
        
        if (reactions is not None):
            reactions._update_some_users(emoji, users)
        
        return users
    
    
    async def reaction_users_all(self, message, emoji):
        """
        Requests the all the users, which reacted on the message with the given message.
        
        If the message has no reacters at all or no reacters with that emoji returns an empty list. If the emoji's
        every reacters are known, then do requests are done.
        
        This method is a coroutine.
        
        Parameters
        ----------
        message : ``Message``, ``MessageRepr`` or ``MessageReference``
            The message, what's reactions will be requested.
        emoji : ``Emoji`` object
            The emoji, what's reacters will be requested.
        
        Returns
        -------
        users : `list` of (``Client`` or ``User``) objects
        
        Raises
        ------
        TypeError
            If `message` was not given neither as ``Message``, ``MessageRepr`` nor ``MessageReference`` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        if isinstance(message, Message):
            message_id = message.id
            channel_id = message.channel.id
            reactions = message.reactions
        elif isinstance(message, MessageRepr):
            message_id = message.id
            channel_id = message.channel.id
            reactions = None
        elif isinstance(message, MessageReference):
            channel_id = message.channel_id
            message_id = message.message_id
            reactions = None
        else:
            raise TypeError(f'`message` can be given as  `{Message.__name__}`, `{MessageRepr.__name__}` or as '
                f'`{MessageReference.__name__}` instance, got {message!r}.')
        
        if (reactions is not None):
            reactions = message.reactions
            if not reactions:
                return []
            
            try:
                line = reactions[emoji]
            except KeyError:
                return []
            
            if not line.unknown:
                users = list(line)
                return users
        
        data = {'limit': 100, 'after': 0}
        users = []
        reaction = emoji.as_reaction
            
        while True:
            user_datas = await self.http.reaction_users(channel_id, message_id, reaction, data)
            users.extend(User(user_data) for user_data in user_datas)
            
            if len(user_datas) < 100:
                break
            
            data['after'] = users[-1].id
        
        if (reactions is not None):
            reactions._update_all_users(emoji, users)
        
        return users
    
    
    async def reaction_load_all(self, message):
        """
        Requests all the reacters for every emoji on the given message.
        
        Like the other reaction getting methods, this method prefers using the internal cache as well over doing a
        request.
        
        This method is a coroutine.
        
        Parameters
        ----------
        message : ``Message``, ``MessageRepr`` or ``MessageReference``
            The message, what's reactions will be requested.
        
        Returns
        -------
        message : ``Message``
        
        Raises
        ------
        TypeError
            If `message` was not given neither as ``Message``, ``MessageRepr`` nor ``MessageReference`` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        if isinstance(message, Message):
            message_id = message.id
            channel_id = message.channel.id
        else:
            if isinstance(message, MessageRepr):
                message_id = message.id
                channel_id = message.channel.id
            elif isinstance(message, MessageReference):
                channel_id = message.channel_id
                message_id = message.message_id
            else:
                raise TypeError(f'`message` can be given as  `{Message.__name__}`, `{MessageRepr.__name__}` or as '
                    f'`{MessageReference.__name__}` instance, got {message!r}.')
            
            message = await self.message_get(channel_id, message_id)
        
        reactions = message.reactions
        if reactions:
            users = []
            data = {'limit': 100}
            
            for emoji, line in reactions.items():
                if not line.unknown:
                    continue
                
                reaction = emoji.as_reaction
                data['after'] = 0
                
                while True:
                    user_datas = await self.http.reaction_users(channel_id, message_id, reaction, data)
                    users.extend(User(user_data) for user_data in user_datas)
                    
                    if len(user_datas) < 100:
                        break
                    
                    data['after'] = users[-1].id
                
                message.reactions._update_all_users(emoji, users)
                users.clear()
        
        return message
    
    # Guild
    
    async def guild_preview(self, guild):
        """
        Requests the preview of a public guild.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild`` or `int`
            The id of the guild, what's preview will be requested
        
        Returns
        -------
        preview : ``GuildPreview``
        
        Raises
        ------
        TypeError
            If `guild` was not given neither as ``Guild`` nor `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        if isinstance(guild, Guild):
            guild_id = guild.id
        
        else:
            guild_id = maybe_snowflake(guild)
            if guild_id is None:
                raise TypeError(f'`guild` can be given as `{Guild.__name__}` or `int` instance, got '
                    f'{guild.__class__.__name__}.')
        
        data = await self.http.guild_preview(guild_id)
        return GuildPreview(data)
    
    
    async def guild_user_delete(self, guild, user, reason=None):
        """
        Removes the given user from the guild.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild`` or `int`
            The guild from where the user will be removed.
        user : ``User``, ``Client`` or `int` instance
            The user to delete from the guild.
        reason : `None` or `str`, Optional
            Shows up at the guild's audit logs.
        
        Raises
        ------
        TypeError
            - If `guild` was not given neither as ``Guild`` nor `int` instance.
            - If `user` was not given neither as ``User``, ``Client``, nnor `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        if isinstance(guild, Guild):
            guild_id = guild.id
        
        else:
            guild_id = maybe_snowflake(guild)
            if guild_id is None:
                raise TypeError(f'`guild` can be given as `{Guild.__name__}` or `int` instance, got '
                    f'{guild.__class__.__name__}.')
        
        
        if isinstance(user, (User, Client)):
            user_id = user.id
        
        else:
            user_id = maybe_snowflake(user)
            if user_id is None:
                raise TypeError(f'`user` can be given as `{User.__name__}`, `{Client.__name__}` or `int` instance, got '
                    f'{user.__class__.__name__}.')
        
        
        await self.http.guild_user_delete(guild_id, user_id, reason)
    
    
    async def welcome_screen_get(self, guild):
        """
        Requests the given guild's welcome screen.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild`` or `int`
            The guild, what's welcome screen will be requested.
        
        Returns
        -------
        welcome_screen : `None` or ``WelcomeScreen``
        
        Raises
        ------
        TypeError
            If `guild` was not given neither as ``Guild`` nor `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        
        Notes
        -----
        If the guild has no welcome screen enabled, will not do any request.
        """
        if isinstance(guild, Guild):
            guild_id = guild.id
        
        else:
            guild_id = maybe_snowflake(guild)
            if guild_id is None:
                raise TypeError(f'`guild` can be given as `{Guild.__name__}` or `int` instance, got '
                    f'{guild.__class__.__name__}.')
            
            guild = None
        
        
        if (guild is None) or (GuildFeature.welcome_screen in guild.features):
            welcome_screen_data = await self.http.welcome_screen_get(guild_id)
            if welcome_screen_data is None:
                welcome_screen = None
            else:
                welcome_screen = WelcomeScreen.from_data(welcome_screen_data)
        else:
            welcome_screen = None
        
        return welcome_screen
    
    async def welcome_screen_edit(self, guild, *, enabled=..., description=..., welcome_channels=...):
        """
        Edits the givne guild's welcome screen.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild`` or `int`
            The guild, what's welcome screen will be edited.
        enabled : `bool`, Optional
            Whether the guild's welcome screen should be enabled.
        description : `None` or `str`, Optional
            The welcome screen's new description. It's length can be in range [0:140].
        welcome_channels : `None`, ``WelcomeChannel`` or  (`tuple` or `list`) of ``WelcomeChannel``
            The channels mentioned on the welcome screen.
        
        Returns
        -------
        welcome_screen : `None or ``WelcomeScreen``
            The updated welcome screen. Always returns `None` if no change was propagated.
        
        Raises
        ------
        TypeError
            - If `guild` was not given neither as ``Guild`` nor `int` instance.
            - If `welcome_channels` was not given neither as `None`, ``WelcomeChannel`` nor as (`tuple` or `list`) of
                ``WelcomeChannel`` instances.
            - If `welcome_channels` contains a non ``WelcomeChannel`` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            - If `enabled` was nto given as `bool` instance.
            - If `description` was not given neither as `None` or `str` instance.
            - If `description`'s length is out of range [0:140].
            - If `welcome_channels`'s length is out of range [0:5].
        """
        if isinstance(guild, Guild):
            guild_id = guild.id
        
        else:
            guild_id = maybe_snowflake(guild)
            if guild_id is None:
                raise TypeError(f'`guild` can be given as `{Guild.__name__}` or `int` instance, got '
                    f'{guild.__class__.__name__}.')
        
        data = {}
        
        if (enabled is not ...):
            if __debug__:
                if not isinstance(enabled, bool):
                    raise AssertionError(f'`enabled` can be given as `bool` instance, got '
                        f'{enabled.__class__.__name__}.')
            
            data['enabled'] = enabled
        
        if (description is not ...):
            if __debug__:
                if (description is not None):
                    if not isinstance(description, str):
                        raise AssertionError(f'`description` can be given as `None` or `str` instance, got '
                            f'{description.__class__.__name__}.')
                
                    description_ln = len(description)
                    if description_ln > 300:
                        raise AssertionError(f'`description` length can be in range [0:140], got {description_ln!r}; '
                            f'{description!r}.')
                
            if (description is not None) and (not description):
                description = None
            
            data['description'] = description
        
        if (welcome_channels is not ...):
            welcome_channel_datas = []
            if welcome_channel_datas is None:
                pass
            elif isinstance(welcome_channels, WelcomeChannel):
                welcome_channel_datas.append(welcome_channels.to_data())
            elif isinstance(welcome_channels, (list, tuple)):
                if __debug__:
                    welcome_channels_ln = len(welcome_channels)
                    if welcome_channels > 5:
                        raise AssertionError(f'`welcome_channels` length can be in range [0:5], got '
                            f'{welcome_channels_ln!r}; {welcome_channels!r}.')
                
                for index, welcome_channel in enumerate(welcome_channels):
                    if not isinstance(welcome_channel, WelcomeChannel):
                        raise TypeError(f'Welcome channel `{index}` was not given as `{WelcomeChannel.__name__}` '
                            f'instance, got {welcome_channel.__class__.__name__}; {welcome_channel!r}.')
                    
                    welcome_channel_datas.append(welcome_channel.to_data())
            else:
                raise TypeError(f'`welcome_channels` can be given as `None`, `{WelcomeChannel.__name__}` or as '
                    f'(`list` or `tuple`) of `{WelcomeChannel.__name__} instances, got '
                    f'{welcome_channels.__class__.__name__}.')
            
            data['welcome_channels'] = welcome_channel_datas
        
        if data:
            data = await self.http.welcome_screen_edit(guild_id, data)
            if data:
                welcome_screen = WelcomeScreen.from_data(data)
            else:
                welcome_screen = None
        else:
            welcome_screen = None
        
        return welcome_screen
    
    
    async def verification_screen_get(self, guild):
        """
        Requests the given guild's verification screen.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild`` or `int`
            The guild, what's verification screen will be requested.

        Returns
        -------
        verification_screen : `None` or ``VerificationScreen``
        
        Raises
        ------
        TypeError
            If `guild` was not given neither as ``Guild`` nor `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        
        Notes
        -----
        If the guild has no verification screen enabled, will not do any request.
        """
        if isinstance(guild, Guild):
            guild_id = guild.id
        
        else:
            guild_id = maybe_snowflake(guild)
            if guild_id is None:
                raise TypeError(f'`guild` can be given as `{Guild.__name__}` or `int` instance, got '
                    f'{guild.__class__.__name__}.')
            
            guild = None
        
        if (guild is None) or (GuildFeature.verification_screen in guild.features):
            verification_screen_data = await self.http.verification_screen_get(guild_id)
            if verification_screen_data is None:
                verification_screen = None
            else:
                verification_screen = VerificationScreen.from_data(verification_screen_data)
        else:
            verification_screen = None
        
        return verification_screen
    
    
    async def verification_screen_edit(self, guild, *, enabled=..., description=..., steps=...):
        """
        Requests the given guild's verification screen.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild`` or `int`
            The guild, what's verification screen will be requested.
        enabled : `bool`, Optional
            Whether the guild should have verification screen enabled.
        description : `None` or `str`, Optional
            The guild's new description showed on the verification screen. It's length can be in range [0:300].
        steps : `None`, ``VerificationScreenStep`` or  (`tuple` or `list`) of ``VerificationScreenStep``, Optional
            The new steps of the verification screen.
        
        Returns
        -------
        verification_screen : `None` or ``VerificationScreen``
            The updated verification screen. Always returns `None` if no change was propagated.
        
        Raises
        ------
        TypeError
            - If `guild` was not given neither as ``Guild`` nor `int` instance.
            - If `steps` was not given neither as `None`, ``VerificationScreenStep`` nor as (`tuple` or `list`) of
                ``VerificationScreenStep`` instances.
            - If `steps` contains a non ``VerificationScreenStep`` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            - If `enabled` was not given as `bool` instance.
            - If `description` was not given neither as `None` or `str` instance.
            - If `description`'s length is out of range [0:300].
        
        Notes
        -----
        When editing steps, `DiscordException Internal Server Error (500): 500: Internal Server Error` will be dropped.
        """
        if isinstance(guild, Guild):
            guild_id = guild.id
        
        else:
            guild_id = maybe_snowflake(guild)
            if guild_id is None:
                raise TypeError(f'`guild` can be given as `{Guild.__name__}` or `int` instance, got '
                    f'{guild.__class__.__name__}.')
        
        data = {}
        
        if (enabled is not ...):
            if __debug__:
                if not isinstance(enabled, bool):
                    raise AssertionError(f'`enabled` can be given as `bool` instance, got '
                        f'{enabled.__class__.__name__}.')
            
            data['enabled'] = enabled
        
        if (description is not ...):
            if __debug__:
                if (description is not None):
                    if not isinstance(description, str):
                        raise AssertionError(f'`description` can be given as `None` or `str` instance, got '
                            f'{description.__class__.__name__}.')
                    
                    description_ln = len(description)
                    if description_ln > 300:
                        raise AssertionError(f'`description` length can be in range [0:300], got {description_ln!r}; '
                            f'{description!r}.')
            
            if (description is not None) and (not description):
                description = None
            
            data['description'] = description
        
        if (steps is not ...):
            step_datas = []
            if steps is None:
                pass
            elif isinstance(steps, VerificationScreenStep):
                step_datas.append(steps.to_data())
            elif isinstance(steps, (list, tuple)):
                for index, step in enumerate(steps):
                    if not isinstance(step, VerificationScreenStep):
                        raise TypeError(f'`step` element `{index}` was not given as '
                            f'`{VerificationScreenStep.__name__}` instance, got {step.__class__.__name__}; {step!r}.')
                    
                    step_datas.append(step.to_data())
            else:
                raise TypeError(f'`steps` can be given as `None`, `{VerificationScreenStep.__name__}` or as '
                    f'(`list` or `tuple`) of `{VerificationScreenStep.__name__} instances, got '
                    f'{steps.__class__.__name__}.')
            
            data['form_fields'] = step_datas
        
        if data:
            data['version'] = datetime.now().isoformat()
            data = await self.http.verification_screen_edit(guild_id, data)
            if data is None:
                verification_screen = None
            else:
                verification_screen = VerificationScreen.from_data(data)
        else:
            verification_screen = None
        
        return verification_screen
    
    async def guild_ban_add(self, guild, user, delete_message_days=0, reason=None):
        """
        Bans the given user from the guild.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild`` or `int`
            The guild from where the user will be banned.
        user : ``User``, ``Client`` or `int` instance
            The user to ban from the guild.
        delete_message_days : `int`, optional
            How much days back the user's messages should be deleted. Can be in range [0:7].
        reason : `None` or `str`, Optional
            Shows up at the guild's audit logs.
        
        Raises
        ------
        TypeError
            - If `guild` was not given neither as ``Guild`` nor `int` instance.
            - If `user` was not given neither as ``User``, ``Client``, nnor `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            - `delete_message_days` was not given as `int` instance.
            - `delete_message_days` is out of range [0:delete_message_days].
        """
        if isinstance(guild, Guild):
            guild_id = guild.id
        
        else:
            guild_id = maybe_snowflake(guild)
            if guild_id is None:
                raise TypeError(f'`guild` can be given as `{Guild.__name__}` or `int` instance, got '
                    f'{guild.__class__.__name__}.')
        
        
        if isinstance(user, (User, Client)):
            user_id = user.id
        
        else:
            user_id = maybe_snowflake(user)
            if user_id is None:
                raise TypeError(f'`user` can be given as `{User.__name__}`, `{Client.__name__}` or `int` instance, got '
                    f'{user.__class__.__name__}.')
        
        
        if __debug__:
            if not isinstance(delete_message_days, int):
                raise AssertionError('`delete_message_days` can be given as `int` instance, got '
                    f'{delete_message_days.__class__.__name__}')
        
        data = {}
        
        if delete_message_days:
            if __debug__:
                if delete_message_days < 1 or delete_message_days > 7:
                    raise AssertionError(f'`delete_message_days` can be in range [0:7], got {delete_message_days!r}.')
            
            data['delete_message_days'] = delete_message_days
        
        await self.http.guild_ban_add(guild_id, user_id, data, reason)
    
    
    async def guild_ban_delete(self, guild, user, reason=None):
        """
        Unbans the user from the given guild.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild`` or `int`
            The guild from where the user will be unbanned.
        user : ``User``, ``Client`` or `int` instance
            The user to unban at the guild.
        reason : `None` or `str`, Optional
            Shows up at the guild's audit logs.
        
        Raises
        ------
        TypeError
            - If `guild` was not given neither as ``Guild`` nor `int` instance.
            - If `user` was not given neither as ``User``, ``Client``, nnor `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        if isinstance(guild, Guild):
            guild_id = guild.id
        
        else:
            guild_id = maybe_snowflake(guild)
            if guild_id is None:
                raise TypeError(f'`guild` can be given as `{Guild.__name__}` or `int` instance, got '
                    f'{guild.__class__.__name__}.')
        
        
        if isinstance(user, (User, Client)):
            user_id = user.id
        
        else:
            user_id = maybe_snowflake(user)
            if user_id is None:
                raise TypeError(f'`user` can be given as `{User.__name__}`, `{Client.__name__}` or `int` instance, got '
                    f'{user.__class__.__name__}.')
        
        await self.http.guild_ban_delete(guild_id, user_id, reason)
    
    
    async def guild_sync(self, guild):
        """
        Syncs a guild by it's id with the wrapper. Used internally if desync is detected when parsing dispatch events.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild`` or `int`
            The guild to sync.

        Returns
        -------
        guild : ``Guild``
        
        Raises
        ------
        TypeError
            If `guild` was not given neither as ``Guild`` nor `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        # sadly guild_get does not returns channel and voice state data at least we can request the channels
        if isinstance(guild, Guild):
            guild_id = guild.id
        
        else:
            guild_id = maybe_snowflake(guild)
            if guild_id is None:
                raise TypeError(f'`guild` can be given as `{Guild.__name__}` or `int` instance, got '
                    f'{guild.__class__.__name__}.')
            
            guild = GUILDS.get(guild_id)
        
        if guild is None:
            data = await self.http.guild_get(guild_id)
            channel_datas = await self.http.guild_channels(guild_id)
            data['channels'] = channel_datas
            user_data = await self.http.guild_user_get(guild_id, self.id)
            data['members'] = [user_data]
            guild = Guild(data, self)
        else:
            data = await self.http.guild_get(guild_id)
            guild._sync(data)
            channel_datas = await self.http.guild_channels(guild_id)
            guild._sync_channels(channel_datas)
            
            user_data = await self.http.guild_user_get(guild_id, self.id)
            try:
                profile = self.guild_profiles[guild]
            except KeyError:
                self.guild_profiles[guild] = GuildProfile(user_data, guild)
                if guild not in guild.clients:
                    guild.clients.append(self)
            else:
                profile._update_no_return(user_data, guild)
        
        return guild

##    # Disable user syncing, takes too much time
##    async def _guild_sync_postprocess(self, guild):
##        for client in CLIENTS:
##            try:
##                user_data = await self.http.guild_user_get(guild.id, client.id)
##           except (DiscordException, ConnectionError):
##                continue
##            try:
##                profile=client.guild_profiles[guild]
##            except KeyError:
##                client.guild_profiles[guild]=GuildProfile(user_data, guild)
##                if client not in guild.clients:
##                    guild.clients.append(client)
##            else:
##                profile._update_no_return(user_data, guild)
##
##        if not CACHE_USER:
##            return
##
##        old_ids=set(guild.users)
##        data={'limit':1000,'after':'0'}
##        while True:
##            user_datas = await self.http.guild_users(guild.id, data)
##            for user_data in user_datas:
##                user=User._create_and_update(user_data, guild)
##                try:
##                    old_ids.remove(user.id)
##                except KeyError:
##                    pass
##             if len(user_datas)<1000:
##                 break
##             data['after']=user_datas[999]['user']['id']
##        del data
##
##        for id_ in old_ids:
##            try:
##               user=guild.users.pop(id_)
##           except KeyError:
##               continue #huh?
##           try:
##               del user.guild_profiles[guild]
##           except KeyError:
##               pass #huh??
    
    async def guild_leave(self, guild):
        """
        The client leaves the given guild.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild`` or `int`
            The guild from where the client will leave.
        
        Raises
        ------
        TypeError
            If `guild` was not given neither as ``Guild`` nor `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        if isinstance(guild, Guild):
            guild_id = guild.id
        
        else:
            guild_id = maybe_snowflake(guild)
            if guild_id is None:
                raise TypeError(f'`guild` can be given as `{Guild.__name__}` or `int` instance, got '
                    f'{guild.__class__.__name__}.')
        
        await self.http.guild_leave(guild_id)
    
    
    async def guild_delete(self, guild):
        """
        Deletes the given guild. The client must be the owner of the guild.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild`` or `int`
            The guild to delete.
        
        Raises
        ------
        TypeError
            If `guild` was not given neither as ``Guild`` nor `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        if isinstance(guild, Guild):
            guild_id = guild.id
        
        else:
            guild_id = maybe_snowflake(guild)
            if guild_id is None:
                raise TypeError(f'`guild` can be given as `{Guild.__name__}` or `int` instance, got '
                    f'{guild.__class__.__name__}.')
        
        await self.http.guild_delete(guild_id)
    
    
    async def guild_create(self, name, icon=None, roles=None, channels=None, afk_channel_id=None,
            system_channel_id=None, afk_timeout=None, region=VoiceRegion.eu_central,
            verification_level=VerificationLevel.medium, message_notification=MessageNotificationLevel.only_mentions,
            content_filter=ContentFilterLevel.disabled):
        """
        Creates a guild with the given parameter. A user account cant be member of 100 guilds maximum and a bot
        account can create a guild only if it is member of less than 10 guilds.
        
        This method is a coroutine.
        
        Parameters
        ----------
        name : `str`
            The name of the new guild.
        icon : `None` or `bytes-like`, Optional
            The icon of the new guild.
        roles : `None` or `list` of ``cr_p_role_object`` returns, Optional
            A list of roles of the new guild. It should contain json serializable roles made by the
            ``cr_p_role_object`` function.
        channels : `None` or `list` of ``cr_pg_channel_object`` returns, Optional
            A list of channels of the new guild.  It should contain json serializable channels made by the
            ``cr_p_role_object`` function.
        afk_channel_id : `int`, Optional
            The id of the guild's afk channel. The id should be one of the channel's id from `channels`.
        system_channel_id: `int`, Optional
            The id of the guild's system channel. The id should be one of the channel's id from `channels`.
        afk_timeout : `int`, Optional
            The afk timeout for the users at the guild's afk channel.
        region : ``VoiceRegion`` or `str`, Optional
            The voice region of the new guild.
        verification_level : ``VerificationLevel`` or `int` instance, Optional
            The verification level of the new guild.
        message_notification : ``MessageNotificationLevel`` or `int`, Optional
            The message notification level of the new guild.
        content_filter : ``ContentFilterLevel`` or `int`, Optional
            The content filter level of the guild.
        
        Returns
        -------
        guild : ``Guild`` object
            A partial guild made from the received data.
        
        Raises
        ------
        TypeError
            - If `icon` is neither `None` or `bytes-like`.
            - If `region` was not given neither as ``VoiceRegion`` nor `str` instance.
            - If `verification_level` was not given neither as ``VerificationLevel`` not `int` instance.
            - If `content_filter` was not given neither as ``ContentFilterLevel`` not `int` instance.
            - If `message_notification` was not given neither as ``MessageNotificationLevel`` nor `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            - If the client cannot create more guilds.
            - If `name` was not given as `str` instance.
            - If the `name`'s length is out of range [2:100].
            - If `icon` is passed as `bytes-like`, but it's format is not a valid image format.
            - if `afk-timeout` was not given as `int` instance.
            - If `afk_timeout` was passed and not as one of: `60, 300, 900, 1800, 3600`.
        """
        if __debug__:
            if len(self.guild_profiles) > (9 if self.is_bot else 99):
                if self.is_bot:
                    message = 'Bots cannot create a new server if they have 10 or more.'
                else:
                    message = 'Hooman cannot have more than 100 guilds.'
                raise AssertionError(message)
        
        
        if __debug__:
            if not isinstance(name, str):
                raise AssertionError(f'`name` can be given as `str` instance, got {name.__class__.__name__}.')
            
            name_ln = len(name)
            if name_ln < 2 or name_ln > 100:
                raise AssertionError(f'`name` length can be in range [2:100], got {name_ln}')
        
        
        if icon is None:
            icon_data = None
        else:
            icon_type = icon.__class__
            if not issubclass(icon_type, (bytes, bytearray, memoryview)):
                raise TypeError(f'`icon` can be passed as `bytes-like`, got {icon_type.__name__}.')
            
            if __debug__:
                extension = get_image_extension(icon)
                if extension not in VALID_ICON_FORMATS:
                    raise AssertionError(f'Invalid icon type: `{extension}`.')
            
            icon_data = image_to_base64(icon)
        
        
        if isinstance(region, VoiceRegion):
            region_value = region.value
        elif isinstance(region, str):
            region_value = region
        else:
            raise TypeError(f'`region` can be given either as `{VoiceRegion.__name__}` or `str` instance, got '
                f'{region.__class__.__name__}.')
        
        
        if isinstance(verification_level, VerificationLevel):
            verification_level_value = verification_level.value
        elif isinstance(verification_level, int):
            verification_level_value = verification_level
        else:
            raise TypeError(f'`verification_level` can be given either as {VerificationLevel.__name__} or `int` '
                f'instance, got {verification_level.__class__.__name__}.')
        
        
        if isinstance(message_notification, MessageNotificationLevel):
            message_notification_value = message_notification.value
        elif isinstance(message_notification, int):
            message_notification_value = message_notification
        else:
            raise TypeError(f'`message_notification` can be given either as `{MessageNotificationLevel.__name__}`'
                f' or `int` instance, got {message_notification.__class__.__name__}.')
        
        
        if isinstance(content_filter, ContentFilterLevel):
            content_filter_value = content_filter.value
        elif isinstance(content_filter, int):
            content_filter_value = content_filter
        else:
            raise TypeError(f'`content_filter` can be given either as {ContentFilterLevel.__name__} or `int` '
                f'instance, got {content_filter.__class__.__name__}.')
        
        if roles is None:
            roles = []
        
        if channels is None:
            channels = []
        
        data = {
            'name'                          : name,
            'icon'                          : icon_data,
            'region'                        : region_value,
            'verification_level'            : verification_level_value,
            'default_message_notifications' : message_notification_value,
            'explicit_content_filter'       : content_filter_value,
            'roles'                         : roles,
            'channels'                      : channels,
                }
        
        if (afk_channel_id is not None):
            if __debug__:
                if not isinstance(afk_channel_id, int):
                    raise AssertionError(f'`afk_channel_id` can be given as `int` instance, got '
                        f'{afk_channel_id.__class__.__name__}.')
            
            data['afk_channel_id'] = afk_channel_id
        
        if (system_channel_id is not None):
            if __debug__:
                if not isinstance(system_channel_id, int):
                    raise AssertionError(f'`system_channel_id` can be given as `int` instance, got '
                        f'{system_channel_id.__class__.__name__}.')
            
            data['system_channel_id'] = system_channel_id
        
        if (afk_timeout is not None):
            if __debug__:
                if not isinstance(afk_timeout, int):
                    raise AssertionError('`afk_timeout` can be given as `int` instance, got '
                        f'{afk_timeout.__class__.__name__}.')
                
                if afk_timeout not in (60, 300, 900, 1800, 3600):
                    raise AssertionError(f'`afk_timeout` should be 60, 300, 900, 1800, 3600 seconds!, got '
                        f'`{afk_timeout!r}`')
            
            data['afk_timeout'] = afk_timeout
        
        data = await self.http.guild_create(data)
        # we can create only partial, because the guild data is not completed usually
        return create_partial_guild(data)
    
    async def guild_prune(self, guild, days, roles=None, count=False, reason=None):
        """
        Kicks the members of the guild which were inactive since x days.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild`` or `int` instance
            Where the pruning will be executed.
        days : `int`
            The amount of days since atleast the users need to inactive. Can be in range [1:30].
        roles : `None` or `list` of (`Role` or `int` instances), Optional
            By default pruning will kick only the users without any roles, but it can defined which roles to include.
        count : `bool`, Optional
            Whether the method should return how much user were pruned, but if the guild is large it will be set to
            `False` anyways. Defaults to `False`.
        reason : `None` or `str`, Optional
            Will show up at the guild's audit logs.
        
        Returns
        -------
        count : `None` or `int`
            The number of pruned users or `None` if `count` is set to `False`.
        
        Raises
        ------
        TypeError
            - If `guild` was not given neither as ``Guild`` nor `int` instance.
            - If `roles` contain not ``Role``, neither `int` element.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            - If `roles` was given neither as `None` or as `list`.
            - If `count` was not given as `bool` instance.
            - If `days` was not given as `int` instance.
            - If `days` is out of range [1:30].
        
        See Also
        --------
        ``.guild_prune_estimate`` : Returns how much user would be pruned if ``.guild_prune`` would be called.
        """
        if isinstance(guild, Guild):
            guild_id = guild.id
        
        else:
            guild_id = maybe_snowflake(guild)
            if guild_id is None:
                raise TypeError(f'`guild` can be given as `{Guild.__name__}` or `int` instance, got '
                    f'{guild.__class__.__name__}.')
            
            guild = GUILDS.get(guild_id)
        
        if __debug__:
            if not isinstance(count, bool):
                raise AssertionError(f'`count` can be given as `bool` instance, got {count.__class__.__name__}.')
        
        if count and (guild is not None) and guild.is_large:
            count = False
        
        if __debug__:
            if not isinstance(days, int):
                raise AssertionError(f'`days can be given as `int` instance, got {days.__class__.__name__}.')
            
            if days < 1 or days > 30:
                raise AssertionError(f'`days can be in range [1:30], got {days!r}.')
        
        data = {
            'days': days,
            'compute_prune_count': count,
                }
        
        if (roles is not None):
            if __debug__:
                if not isinstance(roles, list):
                    raise AssertionError(f'`roles` can be given as `None` or `list` of `{Role.__name__}` and `int`'
                          f'instances, got {roles.__class__.__name__}; {roles!r}.')
            
            role_ids = set()
            for index, role in enumerate(roles):
                if isinstance(role, Role):
                    role_id = role.id
                else:
                    role_id = maybe_snowflake(role)
                    if role_id is None:
                        raise TypeError(f'`roles` index {index} was expected to be {Role.__name__} or `in` instance,'
                            f'but got {role.__class__.__name__}.')
                
                role_ids.add(role_id)
            
            if role_ids:
                data['include_roles'] = role_ids
        
        data = await self.http.guild_prune(guild_id, data, reason)
        return data.get('pruned')
    
    
    async def guild_prune_estimate(self, guild, days, roles=None):
        """
        Returns the amount users, who would been pruned, if ``.guild_prune`` would be called.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild`` or `int` instance.
            Where the counting of prunable users will be done.
        days : `int`
            The amount of days since atleast the users need to inactive. Can be in range [1:30].
        roles : `None` or `list` of ``Role`` objects, Optional
            By default pruning would kick only the users without any roles, but it can be defined which roles to
            include.
        
        Returns
        -------
        count : `int`
            The amount of users who would be pruned.
        
        Raises
        ------
        TypeError
            - If `guild` was not given neither as ``Guild`` nor `int` instance.
            - If `roles` contain not ``Role``, neither `int` element.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            - If `roles` was given neither as `None` or as `list`.
            - If `days` was not given as `int` instance.
            - If `days` is out of range [1:30].
        """
        if isinstance(guild, Guild):
            guild_id = guild.id
        
        else:
            guild_id = maybe_snowflake(guild)
            if guild_id is None:
                raise TypeError(f'`guild` can be given as `{Guild.__name__}` or `int` instance, got '
                    f'{guild.__class__.__name__}.')
        
        if __debug__:
            if not isinstance(days, int):
                raise AssertionError(f'`days can be given as `int` instance, got {days.__class__.__name__}.')
            
            if days < 1 or days > 30:
                raise AssertionError(f'`days can be in range [1:30], got {days!r}.')
        
        data = {
            'days': days,
                }
        
        if (roles is not None):
            if __debug__:
                if not isinstance(roles, list):
                    raise AssertionError(f'`roles` can be given as `None` or `list` of `{Role.__name__}` and `int`'
                          f'instances, got {roles.__class__.__name__}; {roles!r}.')
            
            role_ids = set()
            for index, role in enumerate(roles):
                if isinstance(role, Role):
                    role_id = role.id
                else:
                    role_id = maybe_snowflake(role)
                    if role_id is None:
                        raise TypeError(f'`roles` index {index} was expected to be {Role.__name__} or `in` instance,'
                            f'but got {role.__class__.__name__}.')
                
                role_ids.add(role_id)
            
            if role_ids:
                data['include_roles'] = role_ids
        
        data = await self.http.guild_prune_estimate(guild_id, data)
        return data.get('pruned')
    
    async def guild_edit(self, guild, *, name=None, icon=..., invite_splash=..., discovery_splash=..., banner=...,
            afk_channel=..., system_channel=..., rules_channel=..., public_updates_channel=..., owner=None, region=None,
            afk_timeout=None, verification_level=None, content_filter=None, message_notification=None, description=...,
            preferred_locale=None, system_channel_flags=None, add_feature=None, remove_feature=None, reason=None):
        """
        Edis the guild with the given parameters.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild`` or `int`
            The guild to edit.
        name : `str`, Optional
            The guild's new name.
        icon : `None` or `bytes-like`, Optional
            The new icon of the guild. Can be `'jpg'`, `'png'`, `'webp'` image's raw data. If the guild has
            `ANIMATED_ICON` feature, it can be `'gif'` as well. By passing `None` you can remove the current one.
        invite_splash : `None` or `bytes-like`, Optional
            The new invite splash of the guild. Can be `'jpg'`, `'png'`, `'webp'` image's raw data. The guild must have
            `INVITE_SPLASH` feature. By passing it as `None` you can remove the current one.
        discovery_splash : `None` or `bytes-like`, Optional
            The new splash of the guild. Can be `'jpg'`, `'png'`, `'webp'` image's raw data. The guild must have
            `DISCOVERABLE` feature. By passing it as `None` you can remove the current one.
        banner : `None` or `bytes-like`, Optional
            The new splash of the guild. Can be `'jpg'`, `'png'`, `'webp'` image's raw data. The guild must have
            `BANNER` feature. By passing it as `None` you can remove the current one.
        afk_channel : `None`, ``ChannelVoice`` or `int`, Optional
            The new afk channel of the guild. You can remove the current one by passing is as `None`.
        system_channel : `None`, ``ChannelText`` or `int`, Optional
            The new system channel of the guild. You can remove the current one by passing is as `None`.
        rules_channel : `None`, ``ChannelText`` or `int`, Optional
            The new rules channel of the guild. The guild must be a Community guild. You can remove the current
            one by passing is as `None`.
        public_updates_channel : `None`, ``ChannelText`` or `int`, Optional
            The new public updates channel of the guild. The guild must be a Community guild. You can remove the
            current one by passing is as `None`.
        owner : ``User``, ``Client`` or `int`, Optional
            The new owner of the guild. You must be the owner of the guild to transfer ownership.
        region : ``VoiceRegion``, Optional
            The new voice region of the guild.
        afk_timeout : `int`, Optional
            The new afk timeout for the users at the guild's afk channel.
            
            Can be one of: `60, 300, 900, 1800, 3600`.
        verification_level : ``VerificationLevel`` or `int`, Optional
            The new verification level of the guild.
        content_filter : ``ContentFilterLevel`` or `int`, Optional
            The new content filter level of the guild.
        message_notification : ``MessageNotificationLevel``, Optional
            The new message notification level of the guild.
        description : `None` or `str` instance, Optional
            The new description of the guild. By passing `None`, or an empty string you can remove the current one. The
            guild must be a Community guild.
        preferred_locale : `str`, Optional
            The guild's preferred locale. The guild must be a Community guild.
        system_channel_flags : ``SystemChannelFlag``, Optional
            The guild's system channel's new flags.
        add_feature : (`str`, ``GuildFeature``) or (`iterable` of (`str`, ``GuildFeature``)), Optional
            Guild feature(s) to add to the guild.
            
            If `guild` is given as an id, then `add_feature` should contain all the features of the guild to set.
        remove_feature : (`str`, ``GuildFeature``) or (`iterable` of (`str`, ``GuildFeature``)), Optional
            Guild feature(s) to remove from the guild's.
        reason : `None` or `str`, Optional
            Shows up at the guild's audit logs.
        
        Raises
        ------
        TypeError
            - If `guild` was not given neither as ``Guild`` or `str` instance.
            - If `icon`, `invite_splash`, `discovery_splash`, `banner` is neither `None` or `bytes-like`.
            - If `add_feature` or `remove_feature` was not given neither as `str`, as ``GuildFeature`` or as as
                `iterable` of `str` or ``GuildFeature`` instances.
            - If `afk_channel` was given, but not as `None`, ``ChannelVoice``, neither as `int` instance.
            - If `system_channel`, `rules_channel` or `public_updates_channel` was given, but not as `None`,
                ``ChannelText``, neither as `int` instance.
            - If `owner` was not given neither as ``User``, ``Client`` or `int` instance.
            - If `region` wasg iven neither as ``VoiceRegion`` or `str` instance.
            - If `verification_level` was not given neither as ``VerificationLevel`` or `int` instance.
            - If `content_filter` was not given neither as ``ContentFilterLevel`` or `int` instance.
            - If `description` was not given either as `None` or `str` instance.
        AssertionError
            - If `icon`, `invite_splash`, `discovery_splash` or `banner` was passed as `bytes-like`, but it's format
                is not any of the expected formats.
            - If `banner` was given meanwhile the guild has no `BANNER` feature.
            - If `rules_channel`, `description`, `preferred_locale` or `public_updates_channel` was passed meanwhile
                the guild is not Community guild.
            - If `owner` was passed meanwhile the client is not the owner of the guild.
            - If `afk_timeout` was passed and not as one of: `60, 300, 900, 1800, 3600`.
            - If `name` is shorter than `2` or longer than `100` characters.
            - If `discovery_splash` was given meanwhile the guild is not discoverable.
            - If `invite_splash` was passed meanwhile the guild has no `INVITE_SPLASH` feature.
            - If `name` was not given as `str` instance.
            - If `afk_timeout` was not given as `int` instance.
            - If `system_channel_flags` was not given as `SystemChannelFlag` or as other `int` instance.
            - If `preferred_locale` was not given as `str` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        data = {}
        
        if isinstance(guild, Guild):
            guild_id = guild.id
        else:
            guild_id = maybe_snowflake(guild)
            if guild_id is None:
                raise TypeError(f'`guild` can be given as `{Guild.__name__}` or `int` instance, got '
                    f'{guild.__class__.__name__}.')
            
            guild = None
        
        
        if (name is not None):
            if __debug__:
                if not isinstance(name, str):
                    raise AssertionErrror(f'`name` can be given as `str` instance, got {name.__class__.__name__}.')
                
                name_ln = len(name)
                if name_ln < 2 or name_ln > 100:
                    raise ValueError(f'Guild\'s name\'s length can be between 2-100, got {name_ln}: {name!r}.')
            
            data['name'] = name
        
        
        if (icon is not ...):
            if icon is None:
                icon_data = None
            else:
                if not isinstance(icon, (bytes, bytearray, memoryview)):
                    raise TypeError(f'`icon` can be passed as `None` or `bytes-like`, got {icon.__class__.__name__}.')
                
                if __debug__:
                    extension = get_image_extension(icon)
                    
                    if guild is None:
                        valid_icon_types = VALID_ICON_FORMATS_EXTENDED
                    else:
                        if GuildFeature.animated_icon in guild.features:
                            valid_icon_types = VALID_ICON_FORMATS_EXTENDED
                        else:
                            valid_icon_types = VALID_ICON_FORMATS
                    
                    if extension not in valid_icon_types:
                        raise AssertionError(f'Invalid icon type for the guild: `{extension}`.')
                
                icon_data = image_to_base64(icon)
            
            data['icon'] = icon_data
        
        
        if (banner is not ...):
            if __debug__:
                if (guild is not None) and (GuildFeature.banner not in guild.features):
                    raise AssertionError('The guild has no `BANNER` feature, meanwhile `banner` is given.')
            
            if banner is None:
                banner_data = None
            else:
                if not isinstance(banner, (bytes, bytearray, memoryview)):
                    raise TypeError(f'`banner` can be passed as `None` or `bytes-like`, got '
                        f'{banner.__class__.__name__}.')
                
                if __debug__:
                    extension = get_image_extension(banner)
                    if extension not in VALID_ICON_FORMATS:
                        raise AssertionError(f'Invalid banner type: `{extension}`.')
                
                banner_data = image_to_base64(banner)
            
            data['banner'] = banner_data
        
        
        if (invite_splash is not ...):
            if __debug__:
                if (guild is not None) and (GuildFeature.invite_splash not in guild.features):
                    raise AssertionError('The guild has no `INVITE_SPLASH` feature, meanwhile `invite_splash` is '
                        f'given.')
            
            if invite_splash is None:
                invite_splash_data = None
            else:
                if not isinstance(invite_splash, (bytes, bytearray, memoryview)):
                    raise TypeError(f'`invite_splash` can be passed as `bytes-like`, got '
                        f'{invite_splash.__class__.__name__}.')
                
                if __debug__:
                    extension = get_image_extension(invite_splash)
                    if extension not in VALID_ICON_FORMATS:
                        raise AssertionError(f'Invalid invite splash type: `{extension}`.')
                
                invite_splash_data = image_to_base64(invite_splash)
            
            data['splash'] = invite_splash_data
        
        
        if (discovery_splash is not ...):
            if __debug__:
                if (guild is not None) and (GuildFeature.discoverable not in guild.features):
                    raise AssertionError('The guild is not discoverable, but `discovery_splash` was given.')
            
            if discovery_splash is None:
                discovery_splash_data = None
            else:
                if not isinstance(discovery_splash_type, (bytes, bytearray, memoryview)):
                    raise TypeError(f'`discovery_splash` can be passed as `bytes-like`, got '
                        f'{discovery_splash.__class__.__name__}.')
                
                if __debug__:
                    extension = get_image_extension(discovery_splash)
                    if extension not in VALID_ICON_FORMATS:
                        raise AssertionError(f'Invalid discovery_splash type: `{extension}`.')
                
                discovery_splash_data = image_to_base64(discovery_splash)
            
            data['discovery_splash'] = discovery_splash_data
        
        
        if (afk_channel is not ...):
            if afk_channel is None:
                afk_channel_id = None
            elif isinstance(afk_channel, ChannelVoice):
                afk_channel_id = afk_channel.id
            else:
                afk_channel_id = maybe_snowflake(afk_channel)
                if afk_channel_id is None:
                    raise TypeError(f'`afk_channel` can be given as `None`, `{ChannelVoice.__name__}` or `int` '
                        f'instance, got {afk_channel.__class__.__name__}.')
            
            data['afk_channel_id'] = afk_channel_id
        
        
        if (system_channel is not ...):
            if system_channel is None:
                system_channel_id = None
            elif isinstance(system_channel, ChannelText):
                system_channel_id = system_channel.id
            else:
                system_channel_id = maybe_snowflake(system_channel)
                if system_channel_id is None:
                    raise TypeError(f'`system_channel` can be given as `None`, `{ChannelText.__name__}` or `int` '
                        f'instance, got {system_channel.__class__.__name__}.')
            
            data['system_channel_id'] = system_channel_id
        
        
        if (rules_channel is not ...):
            if __debug__:
                if (guild is not None) and (not COMMUNITY_FEATURES.intersection(guild.features)):
                    raise AssertionError('The guild is not Community guild and `rules_channel` was given.')
            
            if rules_channel is None:
                rules_channel_id = None
            elif isinstance(rules_channel, ChannelText):
                rules_channel_id = rules_channel.id
            else:
                rules_channel_id = maybe_snowflake(rules_channel)
                if rules_channel_id is None:
                    raise TypeError(f'`rules_channel` can be given as `None`, `{ChannelText.__name__}` or `int` '
                        f'instance, got {rules_channel.__class__.__name__}.')
            
            data['rules_channel_id'] = rules_channel_id
        
        
        if (public_updates_channel is not ...):
            if __debug__:
                if (guild is not None) and (not COMMUNITY_FEATURES.intersection(guild.features)):
                    raise AssertionError('The guild is not Community guild and `public_updates_channel` was given.')
            
            if public_updates_channel is None:
                public_updates_channel_id = None
            elif isinstance(public_updates_channel, ChannelText):
                public_updates_channel_id = public_updates_channel.id
            else:
                public_updates_channel_id = maybe_snowflake(public_updates_channel)
                if public_updates_channel_id is None:
                    raise TypeError(f'`public_updates_channel` can be given as `None`, `{ChannelText.__name__}` or '
                        f'`int` instance, got {public_updates_channel.__class__.__name__}.')
            
            data['public_updates_channel_id'] = public_updates_channel_id
        
        
        if (owner is not None):
            if __debug__:
                if (guild is not None) and (guild.owner_id != self.id):
                    raise AssertionError('You must be owner to transfer ownership.')
            
            if isinstance(owner, (User, Client)):
                owner_id = owner.id
            else:
                owner_id = maybe_snowflake(owner)
                if owner_id is None:
                    raise TypeError(f'`owner` can be given as `{UseBase.__name__}` instance or as `int`, got '
                        f'{owner.__class__.__name__}.')
            
            
            data['owner_id'] = owner_id
        
        
        if (region is not None):
            if isinstance(region, VoiceRegion):
                region_value = region.value
            elif isinstance(region, str):
                region_value = region
            else:
                raise TypeError(f'`region` can be given either as `{VoiceRegion.__name__}` or `str` instance, got '
                    f'{region.__class__.__name__}.')
            
            data['region'] = region_value
        
        
        if (afk_timeout is not None):
            if __debug__:
                if not isinstance(afk_timeout, int):
                    raise AssertionError('`afk_timeout` can be given as `int` instance, got '
                        f'{afk_timeout.__class__.__name__}.')
                
                if afk_timeout not in (60, 300, 900, 1800, 3600):
                    raise AssertionError(f'Afk timeout should be one of (60, 300, 900, 1800, 3600) seconds, got '
                        f'`{afk_timeout!r}`.')
            
            data['afk_timeout'] = afk_timeout
        
        
        if (verification_level is not None):
            if isinstance(verification_level, VerificationLevel):
                verification_level_value = verification_level.value
            elif isinstance(verification_level, int):
                verification_level_value = verification_level
            else:
                raise TypeError(f'`verification_level` can be given either as {VerificationLevel.__name__} or `int` '
                    f'instance, got {verification_level.__class__.__name__}.')
            
            data['verification_level'] = verification_level_value
        
        
        if (content_filter is not None):
            if isinstance(content_filter, ContentFilterLevel):
                content_filter_value = content_filter.value
            elif isinstance(content_filter, int):
                content_filter_value = content_filter
            else:
                raise TypeError(f'`content_filter` can be given either as {ContentFilterLevel.__name__} or `int` '
                    f'instance, got {content_filter.__class__.__name__}.')
            
            data['explicit_content_filter'] = content_filter_value
        
        
        if (message_notification is not None):
            if isinstance(message_notification, MessageNotificationLevel):
                message_notification_value = message_notification.value
            elif isinstance(message_notification, int):
                message_notification_value = message_notification
            else:
                raise TypeError(f'`message_notification` can be given either as `{MessageNotificationLevel.__name__}`'
                    f' or `int` instance, got {message_notification.__class__.__name__}.')
            
            data['default_message_notifications'] = message_notification_value
        
        
        if (description is not ...):
            if __debug__:
                if (guild is not None) and (not COMMUNITY_FEATURES.intersection(guild.features)):
                    raise AssertionError('The guild is not Community guild and `description` was given.')
            
            if description is None:
                pass
            elif isinstance(description, str):
                if not description:
                    description = None
            else:
                raise TypeError('`description` can be either given as `None` or `str` instance, got '
                    f'{description.__class__.__name__}.')
            
            data['description'] = description
        
        
        if (preferred_locale is not None):
            if __debug__:
                if (guild is not None) and (not COMMUNITY_FEATURES.intersection(guild.features)):
                    raise AssertionError('The guild is not Community guild and `preferred_locale` was given.')
                
                if not isinstance(preferred_locale, str):
                    raise AssertionError('`preferred_locale` can be given as `str` instance, got '
                        f'{preferred_locale.__class__.__name__}.')
            
            data['preferred_locale'] = preferred_locale
        
        
        if (system_channel_flags is not None):
            if __debug__:
                if not isinstance(system_channel_flags, int):
                    raise AssertionError(f'`system_channel_flags` can be given as `{SystemChannelFlag.__name__}` '
                        f'or `int` instance, got {system_channel_flags.__class__.__name__}')
            
            data['system_channel_flags'] = system_channel_flags
        
        
        if (add_feature is not None) or (remove_feature is not None):
            # Collect actual
            features = set()
            if (guild is not None):
                for feature in guild.features:
                    features.add(feature.value)
            
            # Collect added
            # Use GOTO
            while True:
                if add_feature is None:
                    break
                
                if isinstance(add_feature, GuildFeature):
                    feature = add_feature.value
                elif isinstance(add_feature, str):
                    feature = add_feature
                else:
                    iter_func = getattr(type(add_feature), '__iter__', None)
                    if iter_func is None:
                        raise TypeError(f'`add_feature` can be given as `str`, as `{GuildFeature.__name__}` or as '
                            f'`iterable` of (`str` or `{GuildFeature.__name__}`), got '
                            f'{add_feature.__class__.__name__}.')
                    
                    for index, feature in enumerate(iter_func(add_feature)):
                        if isinstance(feature, GuildFeature):
                            feature = feature.value
                        elif isinstance(feature, str):
                            pass
                        else:
                            raise TypeError(f'`add_feature` was given as `iterable` so it expected to have '
                                f'`{GuildFeature.__name__}` or `str` elements, but element `{index!r}` is '
                                f'{feature.__class__.__name__}; {feature!r}.')
                        
                        features.add(feature)
                        continue
                    
                    break # End GOTO
                
                features.add(feature)
                break # End GOTO
            
            # Collect removed
            
            while True:
                if remove_feature is None:
                    break
                
                if isinstance(remove_feature, GuildFeature):
                    feature = remove_feature.value
                elif isinstance(remove_feature, str):
                    feature = remove_feature
                else:
                    iter_func = getattr(type(remove_feature), '__iter__', None)
                    if iter_func is None:
                        raise TypeError(f'`remove_feature` can be given as `str`, as `{GuildFeature.__name__}` or as '
                            f'`iterable` of (`str` or `{GuildFeature.__name__}`), got '
                            f'{remove_feature.__class__.__name__}.')
                    
                    for index, feature in enumerate(iter_func(remove_feature)):
                        if isinstance(feature, GuildFeature):
                            feature = feature.value
                        elif isinstance(feature, str):
                            pass
                        else:
                            raise TypeError(f'`remove_feature` was given as `iterable` so it expected to have '
                                f'`{GuildFeature.__name__}` or `str` elements, but element `{index!r}` is '
                                f'{feature.__class__.__name__}; {feature!r}.')
                        
                        features.discard(feature)
                        continue
                    
                    break # End GOTO
                
                features.discard(feature)
                break # End GOTO
            
            data['features'] = features
        
        
        await self.http.guild_edit(guild_id, data, reason)
    
    async def guild_bans(self, guild):
        """
        Returns the guild's bans.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild`` object
            The guild, what's bans will be requested
        
        Returns
        -------
        bans : `list` of `tuple` ((``Client`` or ``User`` object), (`None` or `str`)) elements
            User, reason pairs for each ban entry.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        data = await self.http.guild_bans(guild.id)
        return [(User(ban_data['user']), ban_data.get('reason', None)) for ban_data in data]
    
    async def guild_ban_get(self, guild, user_id):
        """
        Returns the guild's ban entry for the given user id.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild`` object
            The guild where the user banned.
        user_id : `int`
            The user's id, who's entry is requested.

        Returns
        -------
        user : ``Client`` or ``User`` object
        reason : `None` or `str`
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        data = await self.http.guild_ban_get(guild.id, user_id)
        return User(data['user']), data.get('reason')
    
    async def guild_widget_get(self, guild_or_id):
        """
        Returns the guild's widget.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild_or_id : ``Guild`` or `int`
            The guild or the guild's id, what's widget will be requested.
        
        Returns
        -------
        guild_widget : `None` or ``GuildWidget``
            If the guild has it's widget disabled returns `None` instead.
        
        Raises
        ------
        TypeError
            If `guild_or_id` was not passed as ``Guild`` or `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        if type(guild_or_id) is Guild:
            guild_id = guild_or_id.id
        elif type(guild_or_id) is int:
            guild_id = guild_or_id
        else:
            raise TypeError(f'Excepted `{Guild.__name__}` or `int` (id), got `{guild_or_id!r}`')
        
        try:
            data = await self.http.guild_widget_get(guild_id)
        except DiscordException as err:
            if err.response.status == 403: #Widget Disabled -> return None
                return
            raise
        
        return GuildWidget(data)
    
    async def guild_discovery_get(self, guild):
        """
        Requests and returns the guild's discovery metadata.
        
        The client must have `manage_guild` permission to execute this method.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild``
            The guild what's discovery will be requested.
        
        Returns
        -------
        guild_discovery : ``GuildDiscovery``
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        guild_discovery_data = await self.http.guild_discovery_get(guild.id)
        return GuildDiscovery(guild_discovery_data, guild)
    
    async def guild_discovery_edit(self, guild_or_discovery, primary_category=..., keywords=..., emoji_discovery=...):
        """
        Edits the guild's discovery metadata.
        
        The client must have `manage_guild` permission to execute this method.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild_or_discovery : ``Guild`` or ``GuildDiscovery``
            The guild what's discovery metadata will be edited or an existing discovery metadata object.
        primary_category : `None` or ``DiscoveryCategory`` or `int`, Optional
            The guild discovery's new primary category's id. Can be given as a ``DiscoveryCategory`` object as well.
            If given as `None`, then resets the guild discovery's primary category id to it's default, what is `0`.
        keywords : `None` or (`iterable` of `str`), Optional
            The guild discovery's new keywords. Can be given as `None` to reset to the default value, what is `None`,
            or as an `iterable` of strings.
        emoji_discovery : `None`, `bool` or `int` (`0`, `1`), Optional
            Whether the guild info should be shown when the respective guild's emojis are clicked. If passed as `None`
            then will reset the guild discovery's `emoji_discovery` value to it's default, what is `True`.
        
        Returns
        -------
        guild_discovery : ``GuildDiscovery``
            Updated guild discovery object.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        TypeError
            - If `guild_or_discovery` was neither passed as type ``Guild`` or ``GuildDiscovery``.
            - If `primary_category_id` was not given neither as `None`, `int` or as ``DiscoveryCategory`` instance.
            - If `keywords` was not passed neither as `None` or `iterable` of `str`.
            - If `emoji_discovery` was not passed neither as `None`, `bool` or `int` (`0`, `1`).
        ValueError
            - If `primary_category_id` was given as not primary ``DiscoveryCategory`` object.
            - If `emoji_discovery` was given as `int` instance, but not as `0` or `1`.
        DiscordException
            If any exception was received from the Discord API.
        """
        if type(guild_or_discovery) is Guild:
            guild_id = guild_or_discovery.id
        elif type(guild_or_discovery) is GuildDiscovery:
            guild_id = guild_or_discovery.guild.id
        else:
            raise TypeError(f'`guild_or_discovery` can be `{Guild.__name__}` or `{GuildDiscovery.__name__}` instance, '
                f'got {guild_or_discovery.__class__.__name__}.')
        
        data = {}
        
        if (primary_category is not ...):
            if (primary_category is None):
                primary_category_id = None
            else:
                primary_category_type = primary_category.__class__
                if primary_category_type is DiscoveryCategory:
                    # If name is set means that we should know whether the category is loaded, or just it's `.id`
                    # is known.
                    if (primary_category.name and (not primary_category.primary)):
                        raise ValueError(f'The given `primary_category_id` was not given as a primary '
                            f'`{DiscoveryCategory.__name__}`, got {primary_category!r}.')
                    primary_category_id = primary_category.id
                elif primary_category_type is int:
                    primary_category_id = primary_category
                elif issubclass(primary_category_type, int):
                    primary_category_id = int(primary_category)
                else:
                    raise TypeError(f'`primary_category` can be given as `None`, `int` instance, or as '
                        f'`{DiscoveryCategory.__name__}` object, got {primary_category_type.__name__}.')
            
            data['primary_category_id'] = primary_category_id
        
        if (keywords is not ...):
            if (keywords is None):
                pass
            elif (not isinstance(keywords, str)) and hasattr(type(keywords), '__iter__'):
                keywords_processed = set()
                index = 0
                for keyword in keywords:
                    if (type(keyword) is str):
                        pass
                    elif isinstance(keyword, str):
                        keyword = str(keyword)
                    else:
                        raise TypeError(f'`keywords` can be `None` or `iterable` of `str`. Got `iterable`, but it\'s '
                            f'elemnet at index {index} is not `str` instance, got {keyword.__class__.__name__}.')
                    
                    keywords_processed.add(keyword)
                    index += 1
                
                keywords = keywords_processed
            else:
                raise TypeError(f'`keywords` can be `None` or `iterable` of `str`. Got {keywords.__class__.__name__}.')
        
            data['keywords'] = keywords
        
        if (emoji_discovery is not ...):
            if (emoji_discovery is None) or (type(emoji_discovery) is bool):
                pass
            elif isinstance(emoji_discovery, int):
                if emoji_discovery == 0:
                    emoji_discovery = False
                elif emoji_discovery == 1:
                    emoji_discovery = True
                else:
                    raise ValueError(f'`emoji_discovery` was given as `int` instance, but not as `0`, or `1`, got '
                        f'{emoji_discovery!r}.')
            else:
                raise TypeError(f'`emoji_discovery` can be given as `None`, `bool` or as `int` instance as `0` or '
                    f'`1`, got {emoji_discovery.__class__.__name__}.')
            
            data['emoji_discoverability_enabled'] = emoji_discovery
        
        guild_discovery_data = await self.http.guild_discovery_edit(guild_id, data)
        if type(guild_or_discovery) is Guild:
            guild_discovery = GuildDiscovery(guild_discovery_data, guild_or_discovery)
        else:
            guild_discovery = guild_or_discovery
            guild_discovery._update_no_return(guild_discovery_data)
        
        return guild_discovery
    
    async def guild_discovery_add_subcategory(self, guild_or_discovery, category):
        """
        Adds a discovery subcategory to the guild.
        
        The client must have `manage_guild` permission to execute this method.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild_or_discovery : ``Guild`` or ``GuildDiscovery``
            The guild to what the discovery subcategory will be added.
        category : ``DiscoveryCategory`` or `int`
            The discovery category or it's id what will be added as a subcategory.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        TypeError
            - If `guild_or_discovery` was neither passed as type ``Guild`` or ``GuildDiscovery``.
            - If `category` was not passed neither as ``DiscoveryCategory`` or as `int` instance.
        DiscordException
            If any exception was received from the Discord API.
        
        Notes
        -----
        A guild can have maximum `5` discovery subcategories.
        
        If `guild_or_discovery` was given as ``GuildDiscovery``, then it will be updated.
        """
        if type(guild_or_discovery) is Guild:
            guild_id = guild_or_discovery.id
        elif type(guild_or_discovery) is GuildDiscovery:
            guild_id = guild_or_discovery.guild.id
        else:
            raise TypeError(f'`guild_or_discovery` can be `{Guild.__name__}` or `{GuildDiscovery.__name__}` instance, '
                f'got {guild_or_discovery.__class__.__name__}.')
        
        category_type = category.__class__
        if category_type is DiscoveryCategory:
            category_id = category.id
        elif category_type is int:
            category_id = category
        elif issubclass(category_type, int):
            category_id = int(category)
        else:
            raise TypeError(f'`category` can be given either as `int` or as `{DiscoveryCategory.__name__} instance, '
                f'got {category_type.__name__}.')
        
        await self.http.guild_discovery_add_subcategory(guild_id, category_id)
        
        if type(guild_or_discovery) is GuildDiscovery:
            guild_or_discovery.sub_categories.add(category_id)
    
    async def guild_discovery_delete_subcategory(self, guild_or_discovery, category):
        """
        Removes a discovery subcategory of the guild.
        
        The client must have `manage_guild` permission to execute this method.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild_or_discovery : ``Guild`` or ``GuildDiscovery``
            The guild to what the discovery subcategory will be removed from.
        category : ``DiscoveryCategory`` or `int`
            The discovery category or it's id what will be removed from the subcategories.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        TypeError
            - If `guild_or_discovery` was neither passed as type ``Guild`` or ``GuildDiscovery``.
            - If `category` was not passed neither as ``DiscoveryCategory`` or as `int` instance.
        DiscordException
            If any exception was received from the Discord API.
        
        Notes
        -----
        A guild can have maximum `5` discovery subcategories.
        
        If `guild_or_discovery` was given as ``GuildDiscovery``, then it will be updated.
        """
        if type(guild_or_discovery) is Guild:
            guild_id = guild_or_discovery.id
        elif type(guild_or_discovery) is GuildDiscovery:
            guild_id = guild_or_discovery.guild.id
        else:
            raise TypeError(f'`guild_or_discovery` can be `{Guild.__name__}` or `{GuildDiscovery.__name__}` instance, '
                f'got {guild_or_discovery.__class__.__name__}.')
        
        category_type = category.__class__
        if category_type is DiscoveryCategory:
            category_id = category.id
        elif category_type is int:
            category_id = category
        elif issubclass(category_type, int):
            category_id = int(category)
        else:
            raise TypeError(f'`category` can be given either as `int` or as `{DiscoveryCategory.__name__} instance, '
                f'got {category_type.__name__}.')
        
        await self.http.guild_discovery_delete_subcategory(guild_id, category_id)
        
        if type(guild_or_discovery) is GuildDiscovery:
            try:
                guild_or_discovery.sub_categories.remove(category_id)
            except KeyError:
                pass
    
    async def discovery_categories(self):
        """
        Returns a list of discovery categories, which can be used when editing guild discovery.
        
        This method is a coroutine.
        
        Returns
        -------
        discovery_categories : `list` of ``DiscoveryCategory``
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        discovery_category_datas = await self.http.discovery_categories()
        return [
            DiscoveryCategory.from_data(discovery_category_data) for discovery_category_data in discovery_category_datas
                    ]
    
    # Add cached, so even tho the first request fails with `ConnectionError` will not be raised.
    discovery_categories = DiscoveryCategoryRequestCacher(discovery_categories, 3600.0,
        cached=list(DISCOVERY_CATEGORIES.values()))
    
    async def discovery_validate_term(self, term):
        """
        Checks whether the given discovery search term is valid.
        
        This method is a coroutine.
        
        Parameters
        ----------
        term : `str`
        
        Returns
        -------
        valid : `bool`
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        data = await self.http.discovery_validate_term({'term': term})
        return data['valid']
    
    discovery_validate_term = DiscoveryTermRequestCacher(discovery_validate_term, 86400.0,
        RATELIMIT_GROUPS.discovery_validate_term)
    
    async def guild_users(self, guild):
        """
        Requests all the users of the guild and returns them.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild``
            The guild what's users will be requested.
        
        Returns
        -------
        users : `list` of (``User`` or ``Client``) objects
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        
        Notes
        -----
        If user caching is allowed, these users should be already loaded if the client finished starting up.
        This method takes a long time to finish for huge guilds.
        """
        data = {'limit': 1000, 'after': '0'}
        result = []
        while True:
            user_datas = await self.http.guild_users(guild.id, data)
            for user_data in user_datas:
                user = User(user_data, guild)
                result.append(user)
            if len(user_datas) < 1000:
                break
            data['after'] = user_datas[999]['user']['id']
        return result
    
    async def guild_get_all(self):
        """
        Requests all the guilds of the client.
        
        This method is a coroutine.
        
        Returns
        -------
        guilds : `list` of ``Guilds` objects
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        
        Notes
        -----
        If the client finished starting up, all the guilds should be already loaded.
        """
        result = []
        params = {'after': 0}
        while True:
            data = await self.http.guild_get_all(params)
            result.extend(create_partial_guild(guild_data) for guild_data in data)
            if len(data) < 100:
                break
            params['after'] = result[-1].id
        
        return result
    
    async def guild_regions(self, guild):
        """
        Requests the available voice regions for the given guild and returns them and the optiomal ones.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild``
            The guild, what's regions will be requested.
        
        Returns
        -------
        voice_regions : `list` of ``VoiceRegion`` objects
            The available voice reions for the guild.
        optimals : `list` of ``VoiceRegion`` objects
            The optimal voice regions for the guild.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        data = await self.http.guild_regions(guild.id)
        voice_regions = []
        optimals = []
        for voice_region_data in data:
            region = VoiceRegion.from_data(voice_region_data)
            voice_regions.append(region)
            if voice_region_data['optimal']:
                optimals.append(region)
        
        return voice_regions, optimals
    
    async def voice_regions(self):
        """
        Returns all the voice regions.
        
        This method is a coroutine.
        
        Returns
        -------
        voice_regions : `list` of ``VoiceRegion`` objects
            Received voice regions.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        data = await self.http.voice_regions()
        voice_regions = []
        for voice_region_data in data:
            region = VoiceRegion.from_data(voice_region_data)
            voice_regions.append(region)
        
        return voice_regions
    
    async def guild_sync_channels(self, guild):
        """
        Requests the given guild's channels and if there any desync between the wrapper and Discord, applies the
        changes.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild``
            The guild, what's channels will be requested.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        data = await self.http.guild_channels(guild.id)
        guild._sync_channels(data)
    
    async def guild_sync_roles(self, guild):
        """
        Requests the given guild's roles and if there any desync between the wrapper and Discord, applies the
        changes.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild``
            The guild, what's roles will be requested.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        data = await self.http.guild_roles(guild.id)
        guild._sync_roles(data)
    
    async def audit_logs(self, guild, limit=100, before=None, after=None, user=None, event=None,):
        """
        Request a batch of audit logs of the guild and returns them. The `after`, `around` and the `before` arguments
        are mutually exclusive and they can be passed as `int`, or as a ``DiscordEntitiy`` instance or as a `datetime`
        object.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild``
            The guild, what's audit logs will be requested.
        limit : `int`, Optional
            The amount of audit logs to request. Can b between 1 and 100. Defaults to 100.
        before : `int`, ``DiscordEntity` or `datetime`, Optional
            The timestamp before the audit log entries wer created.
        after : `int`, ``DiscordEntity`` or `datetime`, Optional
            The timestamp after the audit log entries wer created.
        user : ``Client`` or ``User`` object, Optional
            Whether the audit logs should be filtered only to those, which were created by the given user.
        event : ``AuditLogEvent``, Optional
            Whether the audit logs should be filtered only on the given event.
        
        Returns
        -------
        audit_log : ``AuditLog``
            A container what contains the ``AuditLogEntry``-s.
        
        Raises
        ------
        ValueError
            If `limit` is under `1` or over `100`.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        if limit < 1 or limit > 100:
            raise ValueError(f'Limit can be in <1, 100>, got {limit}')
        
        data = {'limit': limit}
        
        if (before is not None):
            data['before'] = log_time_converter(before)
        
        if (after is not None):
            data['after'] = log_time_converter(after)
        
        if (user is not None):
            data['user_id'] = user.id
        
        if (event is not None):
            data['action_type'] = event.value
        
        data = await self.http.audit_logs(guild.id, data)
        return AuditLog(data, guild)
    
    def audit_log_iterator(self, guild, user=None, event=None):
        """
        Returns an audit log iterator for the given guild.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild``
            The guild, what's audit logs will be requested.
        user : ``Client`` or ``User`` object, Optional
            Whether the audit logs should be filtered only to those, which were created by the given user.
        event : ``AuditLogEvent``, Optional
            Whether the audit logs should be filtered only on the given event.
        
        Returns
        -------
        audit_log_iterator : ``AuditLogIterator``
        """
        return AuditLogIterator(self, guild, user=user, event=event)
    
    # users
    
    async def user_edit(self, guild, user, nick=..., deaf=None, mute=None, voice_channel=..., roles=..., reason=None):
        """
        Edits the user at the given guild.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild``
            Where the user will be edited.
        user : ``User`` or ``Client`` object
            The user to edit
        nick : `None` or `str`, Optional
            The new nick of the user. You can remove the current one by passing it as `None` or as an empty string.
        deaf : `bool`, Optional
            Whether the user should be deafen at the voice channels.
        mute : `bool`, Optional
            Whether the user should be muted at the voice channels.
        voice_channel : `None` or ``ChannelVoice`` object, Optional
            Moves the user to the given voice channel. Only applicable if the user is already at a voice channel.
            Pass it as `None` to kick the user from it's voice channel.
        roles : `None` or `list` of ``Role`` objects, Optional
            The new roles of the user. Give it as `None` to remvoe all of the user's roles.
        reason : `None` or `str`, Optional
            Will show up at the guild's audit logs.
        
        Raises
        ------
        ValueError
            If `nick` was passed as `str` and it's length is over `32`.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        data = {}
        if (nick is not ...):
            if (nick is not None):
                nick_ln = len(nick)
                if nick_ln > 32:
                    raise ValueError(f'The length of the nick can be between 1-32, got {nick_ln}')
                if nick_ln == 0:
                    nick = None
            
            try:
                actual_nick = user.guild_profiles[guild].nick
            except KeyError:
                # user cache disabled, or the user is not at the guild -> will raise later
                should_edit_nick = True
            else:
                if (nick is None):
                    if (actual_nick is None):
                        should_edit_nick = False
                    else:
                        should_edit_nick = True
                else:
                    if (actual_nick is None):
                        should_edit_nick = True
                    elif actual_nick == nick:
                        should_edit_nick = False
                    else:
                        should_edit_nick = True
            
            if should_edit_nick:
                if self == user:
                    await self.http.client_edit_nick(guild.id, {'nick': nick}, reason)
                else:
                    data['nick'] = nick
                    
        if (deaf is not None):
            data['deaf'] = deaf
            
        if (mute is not None):
            data['mute'] = mute
            
        if (voice_channel is not ...):
            data['channel_id'] = None if voice_channel is None else voice_channel.id
        
        if (roles is not ...):
            if roles is None:
                role_ids = []
            else:
                role_ids = [role.id for role in roles]
            
            data['roles'] = role_ids
        
        await self.http.user_edit(guild.id, user.id, data, reason)
    
    async def user_role_add(self, user, role, reason=None):
        """
        Adds the role on the user.
        
        This method is a coroutine.
        
        Parameters
        ----------
        user : ``Client`` or ``User``
            The user who will get the role.
        role : ``Role``
            The role to add on the user.
        reason : `None` or `str`, Optional
            Shows up at the respective guild's audit logs.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        # If the role is partial, it's guild is None.
        guild = role.guild
        if guild is None:
            return
        
        await self.http.user_role_add(guild.id, user.id, role.id, reason)
    
    async def user_role_delete(self, user, role, reason=None):
        """
        Deletes the role from the user.
        
        This method is a coroutine.
        
        Parameters
        ----------
        user : ``Client`` or ``User``
            The user from who the role will be removed.
        role : ``Role``
            The role to remove from the user.
        reason : `None` or `str`, Optional
            Shows up at the respective guild's audit logs.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        # If the role is partial, it's guild is None.
        guild = role.guild
        if guild is None:
            return
        
        await self.http.user_role_delete(guild.id, user.id, role.id, reason)
    
    async def user_voice_move(self, user, voice_channel):
        """
        Moves the user to the given voice channel. The user must be in a voice channel at the respective guild already.
        
        This method is a coroutine.
        
        Parameters
        ----------
        user : ``Client`` or ``User``
            The user to move.
        voice_channel : ``ChannelVoice``
            The channel where the user will be moved.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        # If the channel is partial, it's guild is None.
        guild = voice_channel
        if guild is None:
            return
       
        await self.http.user_move(guild.id, user.id, {'channel_id': voice_channel.id})
    
    async def user_voice_kick(self, user, guild):
        """
        Kicks the user from the guild's voice channels. The user must be in a voice channel at the guild.
        
        This method is a coroutine.
        
        Parameters
        ----------
        user : ``Client`` or ``User``
            The user who will be kicked from the voice channel.
        guild : ``Guild``
            The guild from what's voice channel the user will be kicked.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        await self.http.user_move(guild.id, user.id, {'channel_id': None})
    
    async def user_get(self, user_id, force_update=False):
        """
        Gets an user by it's id. If the user is already loaded updates it.
        
        This method is a coroutine.
        
        Parameters
        ----------
        user_id : `int`
            The user's id, who will be requested.
        force_update : `bool`
            Whether the user should be requested even if it supposed to be up to date.
        
        Returns
        -------
        user : ``Client`` or ``User``
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        
        Raises
        ------
        TypeError
            If `user_id` was not given as `int` instance.
        """
        user_id_value = maybe_snowflake(user_id)
        if user_id_value is None:
            raise TypeError(f'`user_id` can be given as `int` instance, got {user_id.__class__.__name__}.')
        
        if not force_update:
            try:
                user = USERS[user_id_value]
            except KeyError:
                pass
            else:
                for guild in user.guild_profiles:
                    if not guild.partial:
                        return user
        
        data = await self.http.user_get(user_id_value)
        return User._create_and_update(data)
    
    async def guild_user_get(self, guild, user_id):
        """
        Gets an user and it's profile at a guild. The user must be the member of the guild. If the user is already
        loaded updates it.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild``
            The guild, where the user is.
        user_id : `int`
            The user's id, who will be requested.
        
        Returns
        -------
        user : ``Client`` or ``User``
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        data = await self.http.guild_user_get(guild.id, user_id)
        return User._create_and_update(data, guild)
    
    async def guild_user_search(self, guild, query, limit=1):
        """
        Gets an user and it's profile at a guild by it's name. If the users are already loaded updates it.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild``
            The guild, where the user is.
        query : `name`
            The query string with what the user's name or nick should start.
        limit : `int`, Optional
            The maximal amount of users to return. Can bebetween `1` and `1000`. Defaults to `1`.
        
        Returns
        -------
        users : `list` of (``Client`` or ``User``)
        
        Raises
        ------
        ValueError
            If limit is not between `1` and `1000`.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        data = {'query': query}
        
        if limit == 1:
            # default limit is `0`, so not needed to send it.
            pass
        elif limit > 0 and limit < 1000:
            data['limit'] = limit
        else:
            raise ValueError('`limit` can be betwwen 1 and 1000, got `{limit}`')
        
        data = await self.http.guild_user_search(guild.id, data)
        return [User._create_and_update(user_data, guild) for user_data in data]
    
    # integrations
    
    #TODO: decide if we should store integrations at Guild objects
    if API_VERSION == 8:
        async def integration_get_all(self, guild):
            """
            Requests the integrations of the given guild.
            
            This method is a coroutine.
            
            Parameters
            ----------
            guild : ``Guild``
                The guild, what's intgrations will be requested.
            
            Returns
            -------
            integrations : `list` of ``Integration``
            
            Raises
            ------
            ConnectionError
                No internet connection.
            DiscordException
                If any exception was received from the Discord API.
            """
            integrations_data = await self.http.integration_get_all(guild.id, None)
            return [Integration(integration_data) for integration_data in integrations_data]
    else:
        async def integration_get_all(self, guild):
            """
            Requests the integrations of the given guild.
            
            This method is a coroutine.
            
            Parameters
            ----------
            guild : ``Guild``
                The guild, what's intgrations will be requested.
            
            Returns
            -------
            integrations : `list` of ``Integration``
            
            Raises
            ------
            ConnectionError
                No internet connection.
            DiscordException
                If any exception was received from the Discord API.
            """
            integrations_data = await self.http.integration_get_all(guild.id, {'include_applications': True})
            return [Integration(integration_data) for integration_data in integrations_data]
    
    async def integration_create(self, guild, integration_id, type_):
        """
        Creates an integration at the given guild.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild``
            The guild to what the integration will be attached to.
        integration_id : ``int``
            The integration's id.
        type_ : `str`
            The integration's type (`'twitch'`, `'youtube'`, etc.).
        
        Returns
        -------
        integration : ``Integration``
            The created integrated.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        data = {
            'id'   : integration_id,
            'type' : type_,
                }
        data = await self.http.integration_create(guild.id, data)
        return Integration(data)

    async def integration_edit(self, integration, expire_behavior=None, expire_grace_period=None, enable_emojis=True):
        """
        Edits the given integration.
        
        This method is a coroutine.
        
        Parameters
        ----------
        integration : ``Integration``
            The integration to edit.
        expire_behavior : `int`, Optional
            Can be `0` for kick or `1` for role  remove.
        expire_grace_period : `int`, Optional
            The time in days, after the subscribtion will be ignored. Can be `1`, `3`, `7`, `14` or `30`.
        enable_emojis : `bool`, Optional
            Twitch only.
        
        Raises
        ------
        TypeError
            - If `expire_behavior` was not passed as `int`.
            - If `expire_grace_period` was not passed as `int`.
            - If `enable_emojis` was not passed as `bool`.
        ValueError
            - If `expire_behavior` was passed as `int`, but not any of: `0`, `1`.
            - If `expire_grace_period` was passed as `int`, but not any of `1`, `3`, `7`, `14`, `30`.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        detail = integration.detail
        if detail is None:
            return
        
        role = detail.role
        if role is None:
            return
        
        guild = role.guild
        if guild is None:
            return
        
        if expire_behavior is None:
            expire_behavior = integration.expire_behavior
        elif type(expire_behavior) is int:
            if expire_behavior not in (0, 1):
                raise ValueError(f'`expire_behavior` should be 0 for kick, 1 for remove role, got {expire_behavior!r}.')
        else:
            raise TypeError(f'`expire_behavior` should be type `int`, got {expire_behavior.__class__.__name__}.')
        if expire_grace_period is None:
            expire_grace_period=integration.expire_grace_period
        elif type(expire_grace_period) is int:
            if expire_grace_period not in (1, 3, 7, 14, 30):
                raise ValueError(f'`expire_grace_period` should be 1, 3, 7, 14, 30, got {expire_grace_period!r}.')
        else:
            raise TypeError(f'`expire_grace_period` should be type `int`, got {expire_grace_period.__class__.__name__}.')
        
        data = {
            'expire_behavior'     : expire_behavior,
            'expire_grace_period' : expire_grace_period,
                }
        
        if (integration.type == 'twitch') and (enable_emojis is not None):
            if type(enable_emojis) is not bool:
                raise TypeError(f'`enable_emojis` should be `bool`, got {enable_emojis.__class__.__name__}.')
            data['enable_emoticons'] = enable_emojis
        
        await self.http.integration_edit(guild.id, integration.id, data)
    
    async def integration_delete(self, integration):
        """
        Deletes the given integration.
        
        This method is a coroutine.
        
        Parameters
        ----------
        integration : ``Integation``
            The integration what will be deleted.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        detail = integration.detail
        if detail is None:
            return
        
        role = detail.role
        if role is None:
            return
        
        guild = role.guild
        if guild is None:
            return
        
        await self.http.integration_delete(guild.id, integration.id)
    
    async def integration_sync(self, integration):
        """
        Sync the given integration's state.
        
        This method is a coroutine.
        
        Parameters
        ----------
        integration : ``Integation``
            The integration to sync.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        detail = integration.detail
        if detail is None:
            return
        
        role = detail.role
        if role is None:
            return
        
        guild = role.guild
        if guild is None:
            return
        
        await self.http.integration_sync(guild.id, integration.id)
    
    async def permission_ow_edit(self, channel, overwrite, allow, deny, reason=None):
        """
        Edits the given prmission overwrite.
        
        This method is a coroutine.
        
        Parameters
        ----------
        channel : ˙˙ChannelGuildBase`` instance
            The channel where the permission overwrite is.
        overwrite : ``PermOW``
            The permission overwrite to edit.
        allow : ``Permission``
            The permission overwrite's new allowed permission's value.
        deny : ``Permission``
            The permission overwrite's new denied permission's value.
        reason : `None` or `str`, Optional
            Shows up at the respective guild's audit logs.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        data = {
            'allow' : allow,
            'deny'  : deny,
            'type'  : overwrite.type
                }
        await self.http.permission_ow_create(channel.id, overwrite.target.id, data, reason)
    
    async def permission_ow_delete(self, channel, overwrite, reason=None):
        """
        Deletes the given permission overwrite.
        
        This method is a coroutine.
        
        Parameters
        ----------
        channel : ˙˙ChannelGuildBase`` instance
            The channel where the permission overwrite is.
        overwrite : ``PermOW``
            The permission overwrite to delete.
        reason : `None` or `str`, Optional
            Shows up at the respective guild's audit logs.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        await self.http.permission_ow_delete(channel.id, overwrite.target.id, reason)
    
    async def permission_ow_create(self, channel, target, allow, deny, reason=None):
        """
        Creates a permission overwrite at the given channel.
        
        This method is a coroutine.
        
        Parameters
        ----------
        channel : ``ChannelGuildBase`` instance
            The channel to what the permission ovrwrite will be added.
        target : ``Role`` or ``UserBase`` instance
            The permission overwrite's target.
        allow : ``Permission``
            The permission overwrite's allowed permission's value.
        deny : ``Permission``
            The permission overwrite's denied permission's value.
        reason : `None` or `str`, Optional
            Shows up at the respective guild's audit logs.
        
        Returns
        -------
        permission_overwrite : ``PermOW``
            A permission overwrite, what estimatedly is same as the one what Discord will create.
        
        Raises
        ------
        TypeError
            If `target` was not passed neither as ``Role`` or as ``UserBase`` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        if type(target) is Role:
            type_ = PERMOW_TYPE_ROLE
        elif isinstance(target, UserBase):
            type_ = PERMOW_TYPE_USER
        else:
            raise TypeError(f'`target` can be either `{Role.__name__}` or `{UserBase.__name__}` instance, got '
                f'{target.__class__.__name__}.')
        
        data = {
            'target': target.id,
            'allow' : allow,
            'deny'  : deny,
            'type'  : type_,
                }
        
        await self.http.permission_ow_create(channel.id, target.id, data, reason)
        return PermOW.custom(target, allow, deny)
    
    # Webhook management
    
    async def webhook_create(self, channel, name, avatar=None):
        """
        Creates a webhook at the given channel.
        
        This method is a coroutine.
        
        Parameters
        ----------
        channel : ``ChannelText``
            The channel of the created webhook.
        name : `str`
            The name of the new webhook. It's lngth can be between `1` and `80`.
        avatar : `bytes-like`, Optional
            The webhook's avatar. Can be `'jpg'`, `'png'`, `'webp'` or `'gif'` image's raw data. However if set as
            `'gif'`, it will not have any animation.
            
        Returns
        -------
        webhook : ``Webhook``
            The created webhook.
        
        Raises
        ------
        TypeError
            If `avatar` was passed, but not as `bytes-like`.
        ValueError
            - If `name`'s length is under `1` or over `80`.
            - If `avatar` was passed as `bytes-like`, but it's format is not `'jpg'`, `'png'`, `'webp'` or `'gif'`.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        name_ln = len(name)
        if name_ln == 0 or name_ln > 80:
            raise ValueError(f'`name` length can be between 1-80, got {name!r}')
        
        data = {'name': name}
        
        if (avatar is not None):
            avatar_type = avatar.__class__
            if not issubclass(avatar_type, (bytes, bytearray, memoryview)):
                raise TypeError(f'`icon` can be passed as `bytes-like`, got {avatar_type.__name__}.')
            
            extension = get_image_extension(avatar)
            if extension not in VALID_ICON_FORMATS_EXTENDED:
                raise ValueError(f'Invalid icon type: `{extension}`.')
            
            data['avatar'] = image_to_base64(avatar)
        
        data = await self.http.webhook_create(channel.id, data)
        return Webhook(data)
    
    async def webhook_get(self, webhook_id):
        """
        Requests the webhook by it's id.
        
        This method is a coroutine.
        
        Parameters
        ----------
        webhook_id : `int`
            The webhook's id.
        
        Returns
        -------
        webhook : ``Webhook``
        
        Raises
        ------
        TypeError
            If `webhook_id` was not given as `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        
        See Also
        --------
        ``.webhook_get_token`` : Getting webhook with Discord's webhook API.
        
        Notes
        -----
        If the webhook already loaded and if it's guild's webhooks are up to date, no request is done.
        """
        webhook_id_value = maybe_snowflake(webhook_id)
        if webhook_id_value is None:
            raise TypeError(f'`webhook_id` can be given as `int` instance, got {webhook_id.__class__.__name__}.')
        
        try:
            webhook = USERS[webhook_id_value]
        except KeyError:
            data = await self.http.webhook_get(webhook_id_value)
            return Webhook(data)
        else:
            channel = webhook.channel
            if (channel is not None):
                guild = channel.guild
                if (guild is not None) and guild.webhooks_uptodate:
                    return webhook
            
            data = await self.http.webhook_get(webhook_id_value)
            webhook._update_no_return(data)
            return webhook
    
    async def webhook_get_token(self, webhook_id, webhook_token):
        """
        Requests the webhook through Discord's webhook API. The client do not needs to be in the guild of the webhook.
        
        This method is a coroutine.
        
        Parameters
        ----------
        webhook_id : `int`
            The webhook's id.
        webhook_token : `str`
            The webhook's token.
        
        Returns
        -------
        webhook : ``Webhook``
        
        Raises
        ------
        TypeError
            If `webhook_id` was not given as `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            If `webhook_token` was not given as `str` instance.
        
        Notes
        -----
        If the webhook already loaded and if it's guild's webhooks are up to date, no request is done.
        """
        webhook_id_value = maybe_snowflake(webhook_id)
        if webhook_id_value is None:
            raise TypeError(f'`webhook_id` can be given as `int` instance, got {webhook_id.__class__.__name__}.')
        
        if __debug__:
            if not isinstance(webhook_token, str):
                raise AssertionError(f'`webhook_token` can be given as `str` instance, got '
                    f'{webhook_token.__class__.__name__}')
        
        try:
            webhook = USERS[webhook_id_value]
        except KeyError:
            webhook = create_partial_webhook(webhook_id_value, webhook_token)
        else:
            channel = webhook.channel
            if (channel is not None):
                guild = channel.guild
                if (guild is not None) and guild.webhooks_uptodate:
                    return webhook
        
        data = await self.http.webhook_get_token(webhook)
        webhook._update_no_return(data)
        return webhook
    
    async def webhook_update(self, webhook):
        """
        Updates the given webhook.
        
        This method is a coroutine.
        
        Parameters
        ----------
        webhook : ``Webhook``
            The webhook to update.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        
        See Also
        --------
        ``.webhook_update_token`` : Updating webhook with Discord webhook API.
        """
        data = await self.http.webhook_get(webhook.id)
        webhook._update_no_return(data)

    async def webhook_update_token(self, webhook):
        """
        Updates the given webhook through Discord's webhook API.
        
        This method is a coroutine.
        
        Parameters
        ----------
        webhook : ``Webhook``
            The webhook to update.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        data = await self.http.webhook_get_token(webhook)
        webhook._update_no_return(data)
        
    async def webhook_get_channel(self, channel):
        """
        Requests the webhooks of the channel.
        
        This method is a coroutine.
        
        Parameters
        ----------
        channel : ``ChannelText``
            The channel, what's webhooks will be requested.
        
        Returns
        -------
        webhooks : `list` of ``Webhook` objects
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        
        Notes
        -----
        No request is done, if the passed channel is partial, or if the channel's guild's webhooks are up to date.
        """
        guild = channel.guild
        if guild is None:
            return []
        
        if guild.webhooks_uptodate:
            return [webhook for webhook in guild.webhooks.values() if webhook.channel is channel]
        
        data = await self.http.webhook_get_channel(channel.id)
        return [Webhook(data) for data in data]
    
    async def webhook_get_guild(self, guild):
        """
        Requests the webhooks of the given guild.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild``
            The guild, what's webhooks will be requested.
        
        Returns
        -------
        webhooks : `list` of ``Webhook` objects
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        
        Notes
        -----
        No request is done, if the guild's webhooks are up to date.
        """
        if guild.webhooks_uptodate:
            return list(guild.webhooks.values())
        
        old_ids = list(guild.webhooks)
        
        result = []
        
        data = await self.http.webhook_get_guild(guild.id)
        for webhook_data in data:
            webhook = Webhook(webhook_data)
            result.append(webhook)
            try:
                old_ids.remove(webhook.id)
            except ValueError:
                pass
        
        if old_ids:
            for id_ in old_ids:
                guild.webhooks[id_]._delete()
        
        guild.webhooks_uptodate = True
        
        return result
        
    async def webhook_delete(self, webhook):
        """
        Deletes the webhook.
        
        This method is a coroutine.
        
        Parameters
        ----------
        webhook : ``Webhook``
            The webhook to delete.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        
        See Also
        --------
        ``.webhook_delete_token`` : Deleting webhook with Discord's webhook API.
        """
        await self.http.webhook_delete(webhook.id)

    async def webhook_delete_token(self, webhook):
        """
        Deletes the webhook through Discord's webhook API.
        
        This method is a coroutine.
        
        Parameters
        ----------
        webhook : ``Webhook``

        Parameters
        ----------
        webhook : ``Webhook``
            The webhook to delete.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        await self.http.webhook_delete_token(webhook)
            
    # later there gonna be more stuff thats why 2 different
    async def webhook_edit(self, webhook, name=None, avatar=..., channel=None):
        """
        Edits and updates the given webhook.
        
        This method is a coroutine.
        
        Parameters
        ----------
        webhook : ``Webhook``
            The webhook to edit.
        name : `str`, Optional
            The webhook's new name. It's length can be between `1` and `80`.
        avatar : `None` or `bytes-like`, Optional
            The webhook's new avatar. Can be `'jpg'`, `'png'`, `'webp'` or `'gif'` image's raw data. However if set as
            `'gif'`, it will not have any animation. If passed as `None`, will remove the webhook's current avatar.
        channel : ``ChannelText``
            The webhook's name channel.
        
        Raises
        ------
        TypeError
            If `avatar` was passed, but not as `bytes-like`.
        ValueError
            - If `name`'s length is under `1` or over `80`.
            - If `avatar` was passed as `bytes-like`, but it's format is not `'jpg'`, `'png'`, `'webp'` or `'gif'`.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        
        See Also
        --------
        ``.webhook_edit_token`` : Editing webhook with Discord's webhook API.
        """
        data = {}
        
        if (name is not None):
            name_ln = len(name)
            if name_ln == 0 or name_ln > 80:
                raise ValueError(f'The length of the name can be between 1-80, got {name!r}')
            
            data['name'] = name
        
        if (avatar is not ...):
            if avatar is None:
                avatar_data = None
            else:
                avatar_type = avatar.__class__
                if not issubclass(avatar_type, (bytes, bytearray, memoryview)):
                    raise TypeError(f'`icon` can be passed as `bytes-like`, got {avatar_type.__name__}.')
            
                extension = get_image_extension(avatar)
                if extension not in VALID_ICON_FORMATS_EXTENDED:
                    raise ValueError(f'Invalid icon type: `{extension}`.')
                
                avatar_data = image_to_base64(avatar)
            
            data['avatar'] = avatar_data
        
        if (channel is not None):
            data['channel_id'] = channel.id
        
        if not data:
            return #save 1 request
        
        data = await self.http.webhook_edit(webhook.id, data)
        webhook._update_no_return(data)
        
    async def webhook_edit_token(self, webhook, name=None, avatar=...): #channel is ignored!
        """
        Edits and updates the given webhook through Discord's webhook API.
        
        This method is a coroutine.
        
        Parameters
        ----------
        webhook : ``Webhook``
            The webhook to edit.
        name : `str`, Optional
            The webhook's new name. It's length can be between `1` and `80`.
        avatar : `None` or `bytes-like`, Optional
            The webhook's new avatar. Can be `'jpg'`, `'png'`, `'webp'` or `'gif'` image's raw data. However if set as
            `'gif'`, it will not have any animation. If passed as `None`, will remove the webhook's current avatar.
        
        Raises
        ------
        TypeError
            If `avatar` was passed, but not as `bytes-like`.
        ValueError
            - If `name`'s length is under `1` or over `80`.
            - If `avatar` was passed as `bytes-like`, but it's format is not `'jpg'`, `'png'`, `'webp'` or `'gif'`.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        
        Notes
        -----
        This endpoint cannot edit the webhook's channel, like ``.webhook_edit``.
        """
        data = {}
        
        if (name is not None):
            name_ln = len(name)
            if name_ln == 0 or name_ln > 80:
                raise ValueError(f'The length of the name can be between 1-80, got {name_ln}')
            
            data['name'] = name
        
        if (avatar is not ...):
            if avatar is None:
                avatar_data = None
            else:
                avatar_type = avatar.__class__
                if not issubclass(avatar_type, (bytes, bytearray, memoryview)):
                    raise TypeError(f'`icon` can be passed as `bytes-like`, got {avatar_type.__name__}.')
                
                extension = get_image_extension(avatar)
                if extension not in VALID_ICON_FORMATS_EXTENDED:
                    raise ValueError(f'Invalid icon type: `{extension}`.')
                
                avatar_data = image_to_base64(avatar)
            
            data['avatar'] = avatar_data
        
        if not data:
            return # save 1 request
        
        data = await self.http.webhook_edit_token(webhook, data)
        webhook._update_no_return(data)
    
    async def webhook_send(self, *args, **kwargs):
        """
        Deprecated, please use ``.webhook_message_create`` instead. Will be removed in 2021 january.
        
        This method is a coroutine.
        """
        warnings.warn(
            '`Client.webhook_send` is deprecated, and will be removed in 2021 january. '
            'Please use `Client.webhook_message_create` instead.',
            FutureWarning)
        
        return await self.webhook_message_create(*args, **kwargs)
    
    async def webhook_message_create(self, webhook, content=None, *, embed=None, file=None, allowed_mentions=...,
            tts=False, name=None, avatar_url=None, wait=False):
        """
        Sends a message with the given webhook. If there is nothing to send, or if `wait` was not passed as `True`
        returns `None`.
        
        This method is a coroutine.
        
        Parameters
        ----------
        webhook : ``Webhook``
            The webhook through what will the message be sent.
        content : `str`, ``EmbedBase``, `Any`, Optional
            The message's content if given. If given as `str` or empty string, then no content will be sent, meanwhile
            if any other non `str` or ``EmbedBase`` instance is given, then will be casted to string.
            
            If given as ``EmbedBase`` instance, then is sent as the message's embed.
            
        embed : ``EmbedBase`` instance or `list` of ``EmbedBase`` instances, Optional
            The embedded content of the message.
            
            If `embed` and `content` parameters are both given as  ``EmbedBase`` instance, then `TypeError` is raised.
        file : `Any`, Optional
            A file to send. Check ``._create_file_form`` for details.
        allowed_mentions : `None`,  `str`, ``UserBase``, ``Role``, `list` of (`str`, ``UserBase``, ``Role`` ), Optional
            Which user or role can the message ping (or everyone). Check ``._parse_allowed_mentions`` for details.
        tts : `bool`, Optional
            Whether the message is text-to-speech.
        name : `str`, Optional
            The mesage's author's new name. Default to the webhook's name by Discord.
        avatar_url : `str`, Optional
            The message's author's avatar's url. Defaults to the webhook's avatar' url by Discord.
        wait : `bool`, Optional
            Whether we should wait for the message to send and receive it's data as well.
        
        Returns
        -------
        message : ``Message`` or `None`
            Returns `None` if there is nothing to send or if `wait` was given as `False` (so by default).
        
        Raises
        ------
        TypeError
            - If `allowed_mentions` contains an element of invalid type.
            - If `embed` was given as `list`, but it contains not only ``EmbedBase`` instances.
            - `content` parameter was given as ``EmbedBase`` instance, meanwhile `embed` parameter was given as well.
            - If ivalid file type would be sent.
        ValueError
            - If `allowed_mentions`'s elements' type is correct, but one of their value is invalid.
            - If more than `10` files would be sent.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            - If `name` was not passed neither as `None` or `str` instance.
            - If `name` was passed as `str` instance, but it's length is out of range [1:32].
            - If `avatar_url` was not given as `str` instance.
        """
        
        # Embed check order:
        # 1.: None
        # 2.: Embed -> [embed]
        # 3.: list of Embed -> embed[:10] or None
        # 4.: raise
        
        if embed is None:
            pass
        elif isinstance(embed, EmbedBase):
            embed = [embed]
        elif isinstance(embed, (list, tuple)):
            if embed:
                if __debug__:
                    for index, element in enumerate(embed):
                        if isinstance(element, EmbedBase):
                            continue
                        
                        raise TypeError(f'`embed` was given as a `list`, but it\'s element under index `{index}` '
                            f'is not `{EmbedBase.__name__}` instance, but {embed_element.__class__.__name__}`, got: '
                            f'{embed.__class__.__name__}.')
                
                embed = embed[:10]
            else:
                embed = None
            
        else:
            raise TypeError(f'`embed` was not given as `{EmbedBase.__name__}` instance, neither as a list of '
                f'{EmbedBase.__name__} instances, got {embed.__class__.__name__}.')
        
        # Content check order:
        # 1.: None
        # 2.: str
        # 3.: Embed -> embed = [content]
        # 4.: list of Embed -> embed = content[:10]
        # 5.: object -> str(content)
        
        if content is None:
            pass
        elif isinstance(content, str):
            if not content:
                content = None
        elif isinstance(content, EmbedBase):
            if __debug__:
                if (embed is not None):
                    raise TypeError(f'Multiple embeds were given, got content={content!r}, embed={embed!r}.')
            
            embed = [content]
            content = None
        else:
            # Check for list of embeds as well.
            if isinstance(content, (list, tuple)):
                if content:
                    for element in content:
                        if isinstance(element, EmbedBase):
                            continue
                        
                        is_list_of_embeds = False
                        break
                    else:
                        is_list_of_embeds = True
                else:
                    is_list_of_embeds = False
            else:
                is_list_of_embeds = False
            
            if is_list_of_embeds:
                if __debug__:
                    if (embed is not None):
                        raise TypeError(f'Multiple embeds were given, got content={content!r}, embed={embed!r}.')
                
                embed = content[:10]
                content = None
            else:
                content = str(content)
                if not content:
                    content = None
        
        message_data = {}
        contains_content = False
        
        if (content is not None):
            message_data['content'] = content
            contains_content = True
        
        if (embed is not None):
            message_data['embeds'] = [embed.to_data() for embed in embed]
            contains_content = True
        
        if (allowed_mentions is not ...):
            message_data['allowed_mentions'] = self._parse_allowed_mentions(allowed_mentions)
        
        if tts:
            message_data['tts'] = True
        
        if (avatar_url is not None):
            if __debug__:
                if not isinstance(avatar_url, str):
                    raise AssetionError(f'`avatar_url` can be given as `None` or `str` instance, got '
                        f'{avatar_url.__class__.__name__}.')
            
            message_data['avatar_url'] = avatar_url
        
        if (name is not None):
            if __debug__:
                if not isinstance(name, str):
                    raise AssertionError(f'`name` cane be given either as `None` or `str instance, got '
                        f'{name.__class__.__name__}')
                
                name_ln = len(name)
                if name_ln > 32:
                    raise AssertionError(f'`name` length can be in range [1:32], got {name_ln}; {name!r}.')
            
            if name:
                message_data['username'] = name
        
        if file is None:
            to_send = message_data
        else:
            to_send = self._create_file_form(message_data, file)
            if to_send is None:
                to_send = message_data
            else:
                contains_content = True
        
        if not contains_content:
            return None
        
        data = await self.http.webhook_message_create(webhook, to_send, wait)
        
        if not wait:
            return
        
        channel = webhook.channel
        if channel is None:
            channel = ChannelText.precreate(int(data['channel_id']))
        
        return channel._create_new_message(data)
    
    async def webhook_message_edit(self, webhook, message, content=..., *, embed=..., allowed_mentions=...):
        """
        Edits the message sent by the given webhook. The message's author must be the webhook itself.
        
        Parameters
        ----------
        webhook : ``Webhook``
            The webhook who created the message.
        message : ``Message`` or ``MessageRepr``, `int` instance
            The webhook's message to edit.
        content : `str`, ``EmbedBase`` or `Any`, Optional
            The new content of the message.
            
            If given as `str` then the message's content will be edited with it. If given as any non ``EmbedBase``
            instance, then it will be cased to string first.
            
            By passing it as empty string, you can remove the message's content.
            
            If given as ``EmbedBase`` instance, then the message's embeds will be edited with it.
        embed : `None`, ``EmbedBase`` instance or `list` of ``EmbedBase`` instances, Optional
            The new embedded content of the message. By passing it as `None`, you can remove the old.
            
            If `embed` and `content` parameters are both given as  ``EmbedBase`` instance, then `TypeError` is raised.
        allowed_mentions : `None`,  `str`, ``UserBase``, ``Role``, `list` of (`str`, ``UserBase``, ``Role`` ), Optional
            Which user or role can the message ping (or everyone). Check ``._parse_allowed_mentions``
            for details.
        
        Raises
        ------
        TypeError
            - If `allowed_mentions` contains an element of invalid type.
            - If `embed` was given as `list`, but it contains not only ``EmbedBase`` instances.
            - `content` parameter was given as ``EmbedBase`` instance, meanwhile `embed` parameter was given as well.
            - `message` was given as `None`. Make sure to use ``Client.webhook_message_create`` with `wait=True` and by
                giving any content to it as well.
            - `message` was not given neither as ``Message``, ``MessageRepr``  or `int` instance.
        ValueError
            - If `allowed_mentions`'s elements' type is correct, but one of their value is invalid.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            If `message` was detectably not sent by the `webhook`.
        
        See Also
        --------
        - ``.message_edit`` : Edit your own messages.
        - ``.webhook_message_create`` : Create a message with a webhook.
        - ``.webhook_message_delete`` : Delete a message created by a webhook.
        
        Notes
        -----
        Embed messages ignore suppression with their endpoint, not like ``.message_edit`` endpoint.
        
        Editing the message with empty string is broken.
        """
        
        # Detect message id
        # 1.: Message
        # 2.: int (str)
        # 3.: MessageRepr
        # 4.: None -> raise
        # 5.: raise
        
        if isinstance(message, Message):
            if __debug__:
                if message.author.id != webhook.id:
                    raise AssertionError('The message was not send by the webhook.')
            message_id = message.id
        else:
            message_id = maybe_snowflake(message)
            if (message_id is not None):
                pass
            elif isinstance(message, MessageRepr):
                # Cannot check author id, skip
                message_id = message.id
            elif message is None:
                raise TypeError(f'`message` was given as `None`. Make sure to use '
                    f'`{self.__class__.__name__}.webhook_message_create` with giving content and by passing `wait` '
                    f'parameter as `True` as well.')
            else:
                raise TypeError(f'`message` can be given as `{Message.__name__}`, `{MessageRepr.__name__}` or as '
                    f'`int` instance, got {message.__class__.__name__}`.')
        
        # Embed check order:
        # 1.: Elipsis
        # 2.: None
        # 3.: Embed : -> [embed]
        # 4.: list of Embed -> embed[:10] or None
        # 5.: raise
        
        if embed is ...:
            pass
        elif embed is None:
            pass
        elif isinstance(embed, EmbedBase):
            embed = [embed]
        elif isinstance(embed, (list, tuple)):
            if embed:
                if __debug__:
                    for index, element in enumerate(embed):
                        if isinstance(element, EmbedBase):
                            continue
                        
                        raise TypeError(f'`embed` was given as a `list`, but it\'s element under index `{index}` '
                            f'is not `{EmbedBase.__name__}` instance, but {embed_element.__class__.__name__}`, got: '
                            f'{embed.__class__.__name__}.')
                
                embed = embed[:10]
            else:
                embed = None
        else:
            raise TypeError(f'`embed` was not given as `{EmbedBase.__name__}` instance, neither as a list of '
                f'{EmbedBase.__name__} instances, got {embed.__class__.__name__}.')
        
        # Content check order:
        # 1.: Elipsis
        # 2.: None
        # 3.: str
        # 4.: Embed -> embed = [content]
        # 5.: list of Embed -> embed = content[:10]
        # 6.: object -> str(content)
        
        if content is ...:
            pass
        elif content is None:
            content = ''
        elif isinstance(content, str):
            pass
        elif isinstance(content, EmbedBase):
            if __debug__:
                if (embed is not ...):
                    raise ValueError(f'Multiple embeds were given, got content={content!r}, embed={embed!r}.')
            
            embed = [content]
            content = ...
        else:
            # Check for list of embeds as well.
            if isinstance(content, (list, tuple)):
                if content:
                    for element in content:
                        if isinstance(element, EmbedBase):
                            continue
                        
                        is_list_of_embeds = False
                        break
                    else:
                        is_list_of_embeds = True
                else:
                    is_list_of_embeds = False
            else:
                is_list_of_embeds = False
            
            if is_list_of_embeds:
                if __debug__:
                    if (embed is not ...):
                        raise ValueError(f'Multiple embeds were given, got content={content!r}, embed={embed!r}.')
                
                embed = content[:10]
                content = ...
            else:
                content = str(content)
        
        # Build payload
        message_data = {}
        
        # Discord docs say, content can be nullable, but nullable content is just ignored.
        if (content is not ...):
            message_data['content'] = content
        
        if (embed is not ...):
            if (embed is not None):
                embed = [embed.to_data() for embed in embed]
            
            message_data['embeds'] = embed
        
        if (allowed_mentions is not ...):
            message_data['allowed_mentions'] = self._parse_allowed_mentions(allowed_mentions)
        
        if not message_data:
            return
        
        # We receive the new message data, but we do not update the message, so dispatch events can get the difference.
        await self.http.webhook_message_edit(webhook, message_id, message_data)
    
    async def webhook_message_delete(self, webhook, message):
        """
        Deletes the message sent by the webhook.
        
        This method is a coroutine.
        
        Parameters
        ----------
        webhook : ``Webhook``
            The webhook who created the message.
        message : ``Message`` or ``MessageRepr`` or `int`
            The webhook's message to edit.
        
        Raises
        ------
        TypeError
            If `message` was not given neither as ``Message``, ``MessageRepr`` neither as `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            If `message` was detectably not sent by the `webhook`.
        
        See Also
        --------
        - ``.message_delete`` : Delete a message.
        - ``.webhook_message_create`` : Create a message with a webhook.
        - ``.webhook_message_edit`` : Edit a message created by a webhook.
        """
        
        # Detect message id
        # 1.: Message
        # 2.: int
        # 3.: MessageRepr
        # 4.: None -> raise
        # 5.: raise
        
        if isinstance(message, Message):
            if __debug__:
                if message.author.id != webhook.id:
                    raise TypeError('The message was not send by the webhook.')
            message_id = message.id
        else:
            message_id = maybe_snowflake(message)
            if (message_id is not None):
                pass
            elif isinstance(message, MessageRepr):
                # Cannot check author id, skip
                message_id = message.id
            elif message is None:
                raise AssertionError('`message` parameter was given as `None`. Make sure to use '
                    f'`{self.__class__.__name__}.webhook_message_create`  with giving content and with giving the '
                    '`wait` parameter as `True`.')
            else:
                raise TypeError(f'`message` can be given as `{Message.__name__}`, `{MessageRepr.__name__}` or as '
                    f'`int` instance, got {message.__class__.__name__}`.')
        
        await self.http.webhook_message_delete(webhook, message_id)
    
    async def emoji_get(self, guild, emoji_id):
        """
        Requests the emoji by it's id at the given guild. If the client's logging in is finished, then it should have
        it's every emoji loaded already.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild``
            The guild, where the emoji is.
        emoji_id : `int`
            The id of the emoji.
        
        Returns
        -------
        emoji : ``Emoji``
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        data = await self.http.emoji_get(guild.id, emoji_id)
        return Emoji(data, guild)
    
    async def guild_sync_emojis(self, guild):
        """
        Syncs the given guild's emojis with the wrapper.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild``
            The guild, what's emojis will be synced.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        data = await self.http.guild_emojis(guild.id)
        guild._sync_emojis(data)
    
    async def emoji_create(self, guild, name, image, roles=[], reason=None):
        """
        Creates an emoji at the given guild.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild``
            The guild, where the emoji will be created.
        name : `str`
            The emoji's name. It's length can be beween `2` and `32`.
        image : `bytes-like`
            The emoji's icon.
        roles : `list` of `Role` objects, Optional
            Whether the created emoji should be limited only to users with any of the specified roles.
        reason : `None` or `str`, Optional
            Will show up at the guild's audit logs.
        
        Returns
        -------
        emoji : ``Emoji``
            The created emoji.
        
        Raises
        ------
        ValueError
            If the `name`'s length is under `2`, or over `32`.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        
        Notes
        -----
        Only some characters can be in the emoji's name, so every other character is filtered out.
        """
        name = ''.join(_VALID_NAME_CHARS.findall(name))
        name_ln = len(name)
        if name_ln < 2 or name_ln > 32:
            raise ValueError(f'The length of the emoji can be between 2-32, got {name!r}.')
        
        image = image_to_base64(image)
        
        data = {
            'name'     : name,
            'image'    : image,
            'role_ids' : [role.id for role in roles]
                }
        
        data = await self.http.emoji_create(guild.id, data, reason)
        emoji = Emoji(data, guild)
        emoji.user = self
        return emoji
    
    async def emoji_delete(self, emoji, reason=None):
        """
        Deletes the given emoji.
        
        This method is a coroutine.
        
        Parameters
        ----------
        emoji : ``Emoji``
            The emoji to delete.
        reason : `None` or `str`, Optional
            Will show up at the respective guild's audit logs.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        guild = emoji.guild
        if guild is None:
            return
        
        await self.http.emoji_delete(guild.id, emoji.id, reason=reason)
    
    async def emoji_edit(self, emoji, name=None, roles=..., reason=None):
        """
        Edits the given emoji.
        
        This method is a coroutine.
        
        Parameters
        ----------
        emoji : ``Emoji``
            The emoji to edit.
        name : `str`, Optional.
            The emoji's new name.
        roles : `None` or `list` of ``Role`` objects, Optional
            The roles to what is the role limited. By passing it as `None`, or as an empty `list` you can remove the
            current ones.
        reason : `None` or `str`, Optional
            Shows up at the respective guild's audit logs.
        
        Raises
        ------
        ValueError
            If the `name`'s length is under `2`, or over `32`.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        guild = emoji.guild
        if guild is None:
            return
        
        data = {}
        
        # name is required
        if (name is None):
            data['name'] = emoji.name
        else:
            name = ''.join(_VALID_NAME_CHARS.findall(name))
            name_ln = len(name)
            if name_ln < 2 or name_ln > 32:
                raise ValueError(f'The length of `name` can be between 2-32, got {name!r}.')
            
            data['name'] = name
        
        # roles are not required
        if (roles is not ...):
            if (roles is not None):
                roles = [role.id for role in roles]
            
            data['roles'] = roles
        
        await self.http.emoji_edit(guild.id, emoji.id, data, reason)
        
    # Invite management
        
    async def vanity_invite(self, guild):
        """
        Returns the vanity invite of the given guild.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild``
            The guild, what's invite will be returned.
        
        Returns
        -------
        invite : `None` or ``Invite``
            The vanity invite of the `guild`, or `None` if it has no vanity invite.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        vanity_code = guild.vanity_code
        if vanity_code is None:
            return None
        
        data = await self.http.invite_get(vanity_code, {})
        return Invite._create_vanity(guild, data)
    
    async def vanity_edit(self, guild, code, reason=None):
        """
        Edits the given guild's vanity invite's code.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild``
            Th guild, what's invite will be edited.
        code : `str`
            The new code of the guild's vanity invite.
        reason : `None` or `str`, Optional
            Shows up at the guild's audit logs.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        await self.http.vanity_edit(guild.id, {'code': code}, reason)
    
    async def invite_create(self, channel, max_age=0, max_uses=0, unique=True, temporary=False):
        """
        Creates an invite at the given channel with the given parameters.
        
        This method is a coroutine.
        
        Parameters
        ----------
        channel : ``ChannelText``, ``ChannelVoice``, ``ChannelGroup`` or ``ChannelStore``
            The channel of the created invite.
        max_age : `int`, Optional
            After how much time (in seconds) will the invite expire. Defaults is never.
        max_uses : `int`, Optional
            How much times can the invite be used. Defaults to unlimited.
        unique : `bool`, Optional
            Whether the created invite should be unique. Defaults to `True`.
        temporary : `bool`, Optional
            Whether the invite should give only temporary membership. Defaults to `False`.
        
        Returns
        -------
        invite : ``Invite``
        
        Raises
        ------
        TypeError
            If the passed's channel is ``ChannelPrivate`` or ``ChannelCategory``.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        if channel.type in (1, 4):
            raise TypeError(f'Cannot create invite from {channel.__class__.__name__}.')
        
        data = {
            'max_age'   : max_age,
            'max_uses'  : max_uses,
            'temporary' : temporary,
            'unique'    : unique,
                }
        
        data = await self.http.invite_create(channel.id, data)
        return Invite(data, False)

    # 'target_user_id' :
    #     DiscordException BAD REQUEST (400), code=50035: Invalid Form Body
    #     target_user_type.GUILD_INVITE_INVALID_TARGET_USER_TYPE('Invalid target user type')
    # 'target_user_type', as 0:
    #     DiscordException BAD REQUEST (400), code=50035: Invalid Form Body
    #     target_user_type.BASE_TYPE_CHOICES('Value must be one of (1,).')
    # 'target_user_type', as 1:
    #     DiscordException BAD REQUEST (400), code=50035: Invalid Form Body
    #     target_user_type.GUILD_INVITE_INVALID_TARGET_USER_TYPE('Invalid target user type')
    # 'target_user_id' and 'target_user_type' together:
    #     DiscordException BAD REQUEST (400), code=50035: Invalid Form Body
    #     target_user_id.GUILD_INVITE_INVALID_STREAMER('The specified user is currently not streaming in this channel')
    # 'target_user_id' and 'target_user_type' with not correct channel:
    #     DiscordException BAD REQUEST (400), code=50035: Invalid Form Body
    #     target_user_id.GUILD_INVITE_INVALID_STREAMER('The specified user is currently not streaming in this channel')
    
    async def stream_invite_create(self, guild, user, max_age=0, max_uses=0, unique=True, temporary=False):
        """
        Creates an STREAM invite at the given guild for the specific user. The user must be streaming at the guild,
        when the invite is created.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild``
            The guild where the user streams
        user : ``Client`` or ``User``
            The streaming user.
        max_age : `int`, Optional
            After how much time (in seconds) will the invite expire. Defaults is never.
        max_uses : `int`, Optional
            How much times can the invite be used. Defaults to unlimited.
        unique : `bool`, Optional
            Whether the created invite should be unique. Defaults to `True`.
        temporary : `bool`, Optional
            Whether the invite should give only temporary membership. Defaults to `False`.
        
        Returns
        -------
        invite : ``Invite``
        
        Raises
        ------
        ValueError
            If the user is not streaming at the guild.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        user_id = user.id
        try:
            voice_state = guild.voice_states[user_id]
        except KeyError:
            raise ValueError('The user must stream at a voice channel of the guild!') from None
        
        if not voice_state.self_stream:
            raise ValueError('The user must stream at a voice channel of the guild!')
        
        data = {
            'max_age'          : max_age,
            'max_uses'         : max_uses,
            'temporary'        : temporary,
            'unique'           : unique,
            'target_user_id'   : user_id,
            'target_user_type' : 1,
                }
        
        data = await self.http.invite_create(voice_state.channel.id, data)
        return Invite(data, False)
    
    async def invite_create_pref(self, guild, *args, **kwargs):
        """
        Creates an invite to the guild's preferred channel.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild . ``Guild``
            The guild to her the invite will be created to.
        *args : Arguments
            Additional arguments to describe the created invite.
        **kwargs : Keyword arguments
            Additional keyword arguments to describe the created invite.
        
        Other Parameters
        ----------------
        max_age : `int`, Optional
            After how much time (in seconds) will the invite expire. Defaults is never.
        max_uses : `int`, Optional
            How much times can the invite be used. Defaults to unlimited.
        unique : `bool`, Optional
            Whether the created invite should be unique. Defaults to `True`.
        temporary : `bool`, Optional
            Whether the invite should give only temporary membership. Defaults to `False`.
        
        Returns
        -------
        invite : ``Invite``
        
        Raises
        ------
        ValueError
            If the guild has no channel to create invite to.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        while True:
            if not guild.channels:
                raise ValueError('The guild has no channels (yet?), try waiting for dispatch or create a channel')

            channel = guild.system_channel
            if channel is not None:
                break
            
            channel = guild.widget_channel
            if channel is not None:
                break
            
            for channel_type in (0, 2):
                for channel in guild.channels:
                    if channel.type == 4:
                        for channel in channel.channels:
                            if channel.type == channel_type:
                                break
                    if channel.type == channel_type:
                        break
                if channel.type == channel_type:
                    break
            else:
                raise ValueError('The guild has only category channels and cannot create invite from them!')
            break
        
        # Check permission, because it can save a lot of time >.>
        if not channel.cached_permissions_for(self).can_create_instant_invite:
            return None
        
        try:
            return (await self.invite_create(channel, *args, **kwargs))
        except DiscordException as err:
            if err.code in (
                    ERROR_CODES.unknown_channel, # the channel was deleted meanwhile
                    ERROR_CODES.invalid_permissions, # permissons changed meanwhile
                        ):
                return None
            raise
    
    async def invite_get(self, invite_code, with_count=True):
        """
        Requests a partial invite with the given code.
        
        This method is a coroutine.
        
        Parameters
        ----------
        invite_code : `str`
            The invites code.
        with_count : `bool`, Optional
            Whether the invite should contain the respective guild's user and online user count. Defaults to `True`.
        
        Returns
        -------
        invite : ``Invite``
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        data = await self.http.invite_get(invite_code, {'with_counts': with_count})
        return Invite(data, False)
    
    async def invite_update(self, invite, with_count=True):
        """
        Updates the given invite. Because this method uses the same endpoint as ``.invite_get``, no new information
        is received if `with_count` is passed as `False`.
        
        This method is a coroutine.
        
        Parameters
        ----------
        invite : ``Invite``
            The invite to update.
        with_count : `bool`, Optional
            Whether the invite should contain the respective guild's user and online user count. Defaults to `True`.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        data = await self.http.invite_get(invite.code, {'with_counts': with_count})
        if invite.partial:
            updater = Invite._update_attributes
        else:
            updater = Invite._update_counts_only
        
        updater(invite, data)
    
    async def invite_get_guild(self, guild):
        """
        Gets the invites of the given guild.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild``
            The guild, what's invites will be requested.
        
        Returns
        -------
        invites : `list` of ``Invite`` objects
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        data = await self.http.invite_get_guild(guild.id)
        return [Invite(invite_data, False) for invite_data in data]
    
    async def invite_get_channel(self, channel):
        """
        Gets the invites of the given channel.
        
        This method is a coroutine.
        
        Parameters
        ----------
        channel : ``ChannelBase`` instance
            The channel, what's invites will be requested.
        
        Returns
        -------
        invites : `list` of ``Invite`` objects
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        data = await self.http.invite_get_channel(channel.id)
        return [Invite(invite_data, False) for invite_data in data]

    async def invite_delete(self, invite, reason=None):
        """
        Deletes the given invite.
        
        This method is a coroutine.
        
        Parameters
        ----------
        invite : ``Invite``
            The invite to delete.
        reason : `None` or `str`, Optional
            Shows up at the respective guild's audit logs.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        await self.http.invite_delete(invite.code, reason)

    async def invite_delete_by_code(self, invite_code, reason=None):
        """
        Deletes the invite by it's code and returns it.
        
        This method is a coroutine.
        
        Parameters
        ----------
        invite_code : ``str``
            The invite's code to delete.
        reason : `None` or `str`, Optional
            Shows up at the respective guild's audit logs.
        
        Returns
        -------
        invite : ``Invite``
            The deleted invite.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        data = await self.http.invite_delete(invite_code, reason)
        return Invite(data, False)
    
    # Role management
    
    async def role_edit(self, role, name=None, color=None, separated=None, mentionable=None, permissions=None,
            position=None, reason=None):
        """
        Edits the role with the given parameters.
        
        This method is a coroutine.
        
        Parameters
        ----------
        role : ``Role``
            The role to edit.
        name : `str`, Optional
            The role's new name.
        color : ``Color`` or `int` Optional
            The role's new color.
        separated : `bool`, Optional
            Whether the users with this role should be shown up as separated from the others.
        mentionable : `bool`, Optional
            Whether the role should be mentionable.
        permissions : ``Permission`` or `int`, Optional
            The new permission value of the role.
        position : `int`, Optional
            The role's new position.
        reason : `None` or `str`, Optional
            Shows up at the respective guild's audit logs.
        
        Raises
        ------
        ValueError
            - If default role would be moved.
            - If any role would be moved to position `0`.
            - If `name`'s length is under `2` or over `32`.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        guild = role.guild
        if guild is None:
            return
        
        if (position is not None):
            await self.role_move(role, position, reason)
        
        data = {}
        
        if (name is not None):
            name_ln = len(name)
            if name_ln < 2 or name_ln > 32:
                raise ValueError(f'The name of the role can be between 2-32, got {name!r}.')
            data['name'] = name
        
        if (color is not None):
            data['color'] = color
        
        if (separated is not None):
            data['hoist'] = separated
        
        if (mentionable is not None):
            data['mentionable'] = mentionable
        
        if (permissions is not None):
            data['permissions'] = permissions
        
        if data:
            await self.http.role_edit(guild.id, role.id, data, reason)
    
    async def role_delete(self, role, reason=None):
        """
        Deletes the given role.
        
        This method is a coroutine.
        
        Parameters
        ----------
        role : ``Role``
            The role to delete
        reason : `None` or `str`, Optional
            Shows up at the respective guild's audit logs.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        guild = role.guild
        if guild is None:
            return
        
        await self.http.role_delete(guild.id, role.id, reason)
    
    async def role_create(self, guild, name=None, permissions=None, color=None, separated=None, mentionable=None,
            reason=None):
        """
        Creates a role at the given guild.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild``
            The guild where the role will be created.
        name : `str`, Optional
            The created role's name.
        color : ``Color`` or `int` Optional
            The created role's color.
        separated : `bool`, Optional
            Whether the users with the created role should show up as separated from the others.
        mentionable : `bool`, Optional
            Whether the created role should be mentionable.
        permissions : ``Permission`` or `int`, Optional
            The permission value of the created role.
        reason : `None` or `str`, Optional
            Shows up at the guild's audit logs.
        
        Raises
        ------
        ValueError
            If `name`'s length is under `2` or over `32`.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        data = {}
        if (name is not None):
            name_ln = len(name)
            if name_ln < 2 or name_ln > 32:
                raise ValueError(f'Role\'s name\'s length can be between 2-32, got {name!r}.')
            data['name'] = name
        
        if (permissions is not None):
            data['permissions'] = permissions
        
        if (color is not None):
            data['color'] = color
        
        if (separated is not None):
            data['hoist'] = separated
        
        if (mentionable is not None):
            data['mentionable'] = mentionable
        
        data = await self.http.role_create(guild.id, data, reason)
        return Role(data, guild)
    
    async def role_move(self, role, position, reason=None):
        """
        Moves the given role.
        
        This method is a coroutine.
        
        Parameters
        ----------
        role : ``Role``
            The role to move
        position : `int`
            The position to move the given role.
        reason : `None` or `str`, Optional
            Shows up at the respective guild's audit logs.
        
        Raises
        ------
        ValueError
            - If default role would be moved.
            - If any role would be moved to position `0`.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        guild = role.guild
        if guild is None:
            # The role is partial, we cannot move it, because there is nowhere to move it >.>
            return
        
        # Is there nothing to move?
        if role.position == position:
            return
        
        # Default role cannot be moved to position not 0
        if role.position == 0:
            if position != 0:
                raise ValueError(f'Default role cannot be moved: `{role!r}`.')
        # non default role cannot be moved to position 0
        else:
            if position == 0:
                raise ValueError(f'Role cannot be moved to position `0`.')
        
        data = change_on_switch(guild.role_list, role, position, key=lambda role_, pos:{'id': role_.id,'position': pos})
        if not data:
            return
        
        await self.http.role_move(guild.id, data, reason)
    
    async def role_reorder(self, roles, reason=None):
        """
        Moves more roles at their guild to the specifie positions.
        
        Partial roles are ignored and if passed any, every role's position after it is reduced. If there are roles
        passed with different guilds, then `ValueError` will be raised. If there are roles passed with the same
        position, then their positions will be sorted out.
        
        This method is a coroutine.
        
        Parameters
        ----------
        roles : (`dict` like or `iterable`) of `tuple` (``Role``, `int`) items
            A `dict` or any `iterable`, which contains `(Role, position)` items.
        reason : `None` or `str`, Optional
            Shows up at the respective guild's audit logs.
        
        Raises
        ------
        TypeError
            If `roles`'s format is not any of the expected ones.
        ValueError
            - If default role would be moved.
            - If any role would be moved to position `0`.
            - If roles from more guilds are passed.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        """
        # Nothing to move, nice
        if not roles:
            return
        
        # Lets check `roles` structure
        roles_valid = []
        
        # Is `roles` passed as dictlike?
        if hasattr(type(roles), 'items'):
            for item in roles.items():
                if type(item) is not tuple:
                    raise TypeError(f'`roles` passed as dictlike, but when iterating it\'s `.items` returned not a '
                        f'`tuple`, got `{item!r}`')
                
                if len(item)!=2:
                    raise TypeError(f'`roles` passed as dictlike, but when iterating it\'s `.items` returned a '
                        f'`tuple`, but not with length `2`, got `{item!r}`')
                
                if (type(item[0]) is not Role) or (type(item[1]) is not int):
                    raise TypeError(f'Items should be `{Role.__name__}`, `int` pairs, but got `{item!r}`')
                
                roles_valid.append(item)
        
        # Is `roles` passed as other iterable
        elif hasattr(type(roles), '__iter__'):
            for item in roles:
                if type(item) is not tuple:
                    raise TypeError(f'`roles` passed as other iterable, but when iterating returned not a `tuple`, got '
                        f'`{item!r}`')
                
                if len(item) != 2:
                    raise TypeError(f'`roles` passed as other iterable, but when iterating returned a `tuple`, but not '
                        f'with length `2`, got `{item!r}`')
                
                if (type(item[0]) is not Role) or (type(item[1]) is not int):
                    raise TypeError(f'Items should be `{Role.__name__}`, `int` pairs, but got `{item!r}`')
                
                roles_valid.append(item)
        
        # `roles` has an unknown format
        else:
            raise TypeError(
                f'`roles` should have been passed as dictlike with (`{Role.__name__}, `int`) items, or as other '
                f'iterable with (`{Role.__name__}, `int`) elements, but got `{roles!r}`')
        
        # Check default and moving to default position
        index = 0
        limit = len(roles_valid)
        while True:
            if index == limit:
                break
            
            role, position = roles_valid[index]
            # Default role cannot be moved
            if role.position == 0:
                if position != 0:
                    raise ValueError(f'Default role cannot be moved: `{role!r}`.')
                
                # default and moving to default, lets delete it
                del roles_valid[index]
                limit -= 1
                continue
                
            else:
                # Role cannot be moved to default position
                if position == 0:
                    raise ValueError(f'Role cannot be moved to position `0`.')
            
            index += 1
            continue
        
        if not limit:
            return
        
        # Check dupe roles
        roles = set()
        ln = 0
        
        for role, position in roles_valid:
            roles.add(role)
            if len(roles) == ln:
                raise ValueError(f'{Role.__name__} `{role!r}` is duped.')
            
            ln += 1
            continue
        
        # Now that we have the roles, lets order them
        roles_valid.sort(key = lambda item : item[1])
        
        # We have all the roles sorted, but they can have dupe positions too
        index = 0
        limit = len(roles_valid)
        last_position = 0
        while True:
            role, position = roles_valid[index]
            
            if last_position != position:
                last_position = position
                
                index += 1
                if index == limit:
                    break
                
                continue
            
            # Oh no, we need to reorder
            # First role cannot get here, becuase it cannot have position 0.
            roles = [roles_valid[index-1][0], role]
            
            sub_index = index+1
            
            while True:
                if sub_index == limit:
                    break
                
                role, position = roles_valid[sub_index]
                if position != last_position:
                    break
                
                roles.append(role)
                sub_index += 1
                continue
            
            # We have all the roles with the same target position.
            # Now we order them by their actual position.
            roles.sort()
            
            index -= 1
            sub_index = 0
            sub_limit = len(roles)
            while True:
                real_index = sub_index+index
                role = roles[sub_index]
                real_position = last_position+sub_index
                roles_valid[real_index] = (role, real_position)
                
                sub_index += 1
                if sub_index == sub_limit:
                    break
                
                continue
            
            added_position = sub_limit-1
            
            real_index = sub_index+index
            while True:
                if real_index == limit:
                    break
                
                role, position = roles_valid[real_index]
                real_position = position+added_position
                roles_valid[real_index] = (role, real_position)
                
                real_index += 1
                continue
            
            
            index += sub_limit
            last_position += added_position
            
            if index == limit:
                break
            
            continue
        
        # We have all the roles in order. Filter out partial roles.
        index = 0
        push = 0
        while True:
            role, position = roles_valid[index]
            
            if role.guild is None:
                push += 1
                del roles_valid[index]
                limit -= 1
            
            else:
                if push:
                    roles_valid[index] = (role, position-push)
                
                index=index+1
            
            if index==limit:
                break
            
            continue
        
        # Did we get down to 0 role?
        if limit == 0:
            return
        
        # Check role guild
        guild = roles_valid[0][0].guild
        
        index = 1
        while True:
            if index == limit:
                break
            
            guild_ = roles_valid[index][0].guild
            index += 1
            
            if guild is guild_:
                continue
            
            raise ValueError(f'There were roles passed at least from two different guilds: `{guild!r}` and '
                f'`{guild_!r}`.')
        
        # Lets cut out every other role from the guild's
        roles_leftover = set(guild.roles.values())
        for item in roles_valid:
            role = item[0]
            roles_leftover.remove(role)
        
        roles_leftover = sorted(roles_leftover)
    
        target_order = []
        
        index_valid = 0
        index_leftover = 0
        limit_valid = len(roles_valid)
        limit_leftover = len(roles_leftover)
        position_target = 0
        
        while True:
            if index_valid == limit_valid:
                while True:
                    if index_leftover == limit_leftover:
                        break
                    
                    role = roles_leftover[index_leftover]
                    index_leftover += 1
                    target_order.append(role)
                    continue
                
                break
            
            if index_leftover == limit_leftover:
                while True:
                    if index_valid == limit_valid:
                        break
                    
                    role = roles_valid[index_valid][0]
                    index_valid += 1
                    target_order.append(role)
                    continue
                
                
                break
            
            role, position = roles_valid[index_valid]
            if position == position_target:
                position_target += 1
                index_valid += 1
                target_order.append(role)
                continue
            
            role = roles_leftover[index_leftover]
            position_target = position_target+1
            index_leftover = index_leftover+1
            target_order.append(role)
            continue
        
        data = []
        
        for index, role in enumerate(target_order):
            position = role.position
            if index == position:
                continue
            
            data.append({'id': role.id, 'position': index})
            continue
        
        # Nothing to move
        if not data:
            return
        
        await self.http.role_move(guild.id, data, reason)
    
    # Application Command & Interaction related
    
    async def application_command_global_get_all(self):
        """
        Requests the client's global application commands.
        
        This method is a coroutine.
        
        Returns
        -------
        application_commands : `list` of ``ApplicationCommand``
            The received application commands.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            If the client's application is not yet synced.
        """
        application_id = self.application.id
        if __debug__:
            if application_id == 0:
                raise AssertionError('The client\'s application is not yet synced.')
        
        data = await self.http.application_command_global_get_all(application_id)
        return [ApplicationCommand.from_data(application_command_data) for application_command_data in data]
    
    
    async def application_command_global_create(self, application_command):
        """
        Creates a new global application command.
        
        This method is a coroutine.
        
        Parameters
        ----------
        application_command : ``ApplicationCommand``
            The application command to create.
        
        Returns
        -------
        application_command : ``ApplicationCommand``
            The created application command.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            - If the client's application is not yet synced.
            - If `application_command` was not given as ``ApplicationCommand`` instance.
        
        Notes
        -----
        Creating a global command with the same name as an already exisitng one, will overwrite the old command.
        
        The command will be available in all guilds after 1 hour.
        """
        application_id = self.application.id
        if __debug__:
            if application_id == 0:
                raise AssertionError('The client\'s application is not yet synced.')
        
        if __debug__:
            if not isinstance(application_command, ApplicationCommand):
                raise AssertionError(f'`application_command` can be given as `{ApplicationCommand.__name__}`, got '
                    f'{application_command.__class__.__name__}.')
        
        data = application_command.to_data()
        data = await self.http.application_command_global_create(application_id, data)
        return ApplicationCommand.from_data(data)
    
    
    async def application_command_global_edit(self, old_application_command, new_application_command):
        """
        Edits a global application command.
        
        This method is a coroutine.
        
        Parameters
        ----------
        old_application_command : ``ApplicationCommand`` or `int`
            The application command to edit. Can be given as the application command's id as well.
        new_application_command : ``ApplicationCommand``
            The application command to edit to.
        
        Returns
        -------
        application_command : ``ApplicationCommand``
            The edited application command.
        
        Raises
        ------
        TypeError
            If `old_application_command` was not given neither as ``ApplicationCommand`` nor `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            - If the client's application is not yet synced.
            - If `new_application_command` was not given as ``ApplicationCommand`` instance.
        
        Notes
        -----
        The updates will be available in all guilds after 1 hour.
        """
        if isinstance(old_application_command, ApplicationCommand):
            application_command_id = old_application_command.id
        else:
            application_command_id = maybe_snowflake(old_application_command)
            if application_command_id is None:
                raise TypeError(f'`old_application_command` can be given as `{ApplicationCommand.__name__}` or `int` '
                    f'instance, got {old_application_command.__class__.__name__}.')
        
        application_id = self.application.id
        if __debug__:
            if application_id == 0:
                raise AssertionError('The client\'s application is not yet synced.')
        
        if __debug__:
            if not isinstance(new_application_command, ApplicationCommand):
                raise AssertionError(f'`new_application_command` can be given as `{ApplicationCommand.__name__}`, got '
                    f'{new_application_command.__class__.__name__}.')
        
        data = new_application_command.to_data()
        await self.http.application_command_global_edit(application_id, application_command_id, data)
        return Application_command._from_edit_data(data, application_command_id, application_id)
    
    async def application_command_global_delete(self, application_command):
        """
        Delets the given application command.
        
        Parameters
        ----------
        application_command : ``ApplicationCommand`` or `int`
            The application command delete edit. Can be given as the application command's id as well.
        
        Raises
        ------
        TypeError
            If `application_command` was not given neither as ``ApplicationCommand`` nor `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            If the client's application is not yet synced.
        """
        application_id = self.application.id
        if __debug__:
            if application_id == 0:
                raise AssertionError('The client\'s application is not yet synced.')
        
        if isinstance(application_command, ApplicationCommand):
            application_command_id = application_command.id
        else:
            application_command_id = maybe_snowflake(application_command)
            if application_command_id is None:
                raise TypeError(f'`application_command` can be given as `{ApplicationCommand.__name__}` or `int` '
                    f'instance, got {application_command.__class__.__name__}.')
        
        await self.http.application_command_global_delete(application_id, application_command_id)
    
    
    async def application_command_guild_get_all(self, guild):
        """
        Requests the client's global application commands.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild`` or `int`
            The guild, which application commands will be requested.
        
        Returns
        -------
        application_commands : `list` of ``ApplicationCommand``
            The received application commands.
        
        Raises
        ------
        TypeError
            If `guild` was not given neither as``Guild`` nor `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            If the client's application is not yet synced.
        """
        application_id = self.application.id
        if __debug__:
            if application_id == 0:
                raise AssertionError('The client\'s application is not yet synced.')
        
        if isinstance(guild, Guild):
            guild_id = guild.id
        else:
            guild_id = maybe_snowflake(guild)
            if guild_id is None:
                raise TypeError(f'`guild` can be given as ``{Guild.__name__}`` or `int` instance, got '
                    f'{guild.__class__.__name__}.')
        
        data = await self.http.application_command_guild_get_all(application_id, guild_id)
        return [ApplicationCommand.from_data(application_command_data) for application_command_data in data]
    
    
    async def application_command_guild_create(self, guild, application_command):
        """
        Creates a new guild application command.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild`` or `int`
            The guild, where application commands will be created.
        application_command : ``ApplicationCommand``
            The application command to create.
        
        Returns
        -------
        application_command : ``ApplicationCommand``
            The created application command.
        
        Raises
        ------
        TypeError
            If `guild` was not given neither as``Guild`` nor `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            - If the client's application is not yet synced.
            - If `application_command` was not given as ``ApplicationCommand`` instance.
        
        Notes
        -----
        Creating a global command with the same name as an already exisitng one, will overwrite the old command.
        """
        application_id = self.application.id
        if __debug__:
            if application_id == 0:
                raise AssertionError('The client\'s application is not yet synced.')
        
        if isinstance(guild, Guild):
            guild_id = guild.id
        else:
            guild_id = maybe_snowflake(guild)
            if guild_id is None:
                raise TypeError(f'`guild` can be given as ``{Guild.__name__}`` or `int` instance, got '
                    f'{guild.__class__.__name__}.')
        
        if __debug__:
            if not isinstance(application_command, ApplicationCommand):
                raise AssertionError(f'`application_command` can be given as `{ApplicationCommand.__name__}`, got '
                    f'{application_command.__class__.__name__}.')
        
        data = application_command.to_data()
        data = await self.http.application_command_guild_create(application_id, guild_id, data)
        return ApplicationCommand.from_data(data)
    
    
    async def application_command_guild_edit(self, guild, old_application_command, new_application_command):
        """
        Edits a guild application command.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild`` or `int`
            The guild, to what the application command is bound to.
        old_application_command : ``ApplicationCommand`` or `int`
            The application command to edit. Can be given as the application command's id as well.
        new_application_command : ``ApplicationCommand``
            The application command to edit to.
        
        Raises
        ------
        TypeError
            - If `guild` was not given neither as``Guild`` nor `int` instance.
            - If `old_application_command` was not given neither as ``ApplicationCommand`` nor `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            - If the client's application is not yet synced.
            - If `new_application_command` was not given as ``ApplicationCommand`` instance.
        """
        if isinstance(old_application_command, ApplicationCommand):
            application_command_id = old_application_command.id
        else:
            application_command_id = maybe_snowflake(old_application_command)
            if application_command_id is None:
                raise TypeError(f'`old_application_command` can be given as `{ApplicationCommand.__name__}` or `int` '
                    f'instance, got {old_application_command.__class__.__name__}.')
        
        application_id = self.application.id
        if __debug__:
            if application_id == 0:
                raise AssertionError('The client\'s application is not yet synced.')
        
        if isinstance(guild, Guild):
            guild_id = guild.id
        else:
            guild_id = maybe_snowflake(guild)
            if guild_id is None:
                raise TypeError(f'`guild` can be given as ``{Guild.__name__}`` or `int` instance, got '
                    f'{guild.__class__.__name__}.')
        
        if __debug__:
            if not isinstance(new_application_command, ApplicationCommand):
                raise AssertionError(f'`new_application_command` can be given as `{ApplicationCommand.__name__}`, got '
                    f'{new_application_command.__class__.__name__}.')
        
        data = new_application_command.to_data()
        await self.http.application_command_guild_edit(application_id, guild_id, application_command_id, data)
    
    async def application_command_guild_delete(self, guild, application_command):
        """
        Delets the given application command.
        
        Parameters
        ----------
        guild : ``Guild`` or `int`
            The guild, to what the application command is bound to.
        application_command : ``ApplicationCommand`` or `int`
            The application command delete edit. Can be given as the application command's id as well.
        
        Raises
        ------
        TypeError
            - If `guild` was not given neither as``Guild`` nor `int` instance.
            - If `application_command` was not given neither as ``ApplicationCommand`` nor `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            If the client's application is not yet synced.
        """
        application_id = self.application.id
        if __debug__:
            if application_id == 0:
                raise AssertionError('The client\'s application is not yet synced.')
        
        if isinstance(guild, Guild):
            guild_id = guild.id
        else:
            guild_id = maybe_snowflake(guild)
            if guild_id is None:
                raise TypeError(f'`guild` can be given as ``{Guild.__name__}`` or `int` instance, got '
                    f'{guild.__class__.__name__}.')
        
        if isinstance(application_command, ApplicationCommand):
            application_command_id = application_command.id
        else:
            application_command_id = maybe_snowflake(application_command)
            if application_command_id is None:
                raise TypeError(f'`application_command` can be given as `{ApplicationCommand.__name__}` or `int` '
                    f'instance, got {application_command.__class__.__name__}.')
        
        await self.http.application_command_guild_delete(application_id, guild_id, application_command_id)
    
    
    async def interaction_response_message_create(self, interaction, content=None, *, embed=None, allowed_mentions=...,
            tts=False, show_source=True):
        """
        Sends an interaction response.
        
        This method is a coroutine.
        
        Parameters
        ----------
        interaction : ``InteractionEvent`` instance
            Interaction to respond to.
        content : `str`, ``EmbedBase``, `Any`, Optional
            The interaction response's content if given. If given as `str` or empty string, then no content will be
            sent, meanwhile if any other non `str` or ``EmbedBase`` instance is given, then will be casted to string.
            
            If given as ``EmbedBase`` instance, then is sent as the message's embed.
        
        embed : ``EmbedBase`` instance or `list` of ``EmbedBase`` instances, Optional
            The embedded content of the interaction response.
            
            If `embed` and `content` parameters are both given as  ``EmbedBase`` instance, then `TypeError` is raised.
        allowed_mentions : `None`,  `str`, ``UserBase``, ``Role``, `list` of (`str`, ``UserBase``, ``Role`` ), Optional
            Which user or role can the message ping (or everyone). Check ``._parse_allowed_mentions`` for details.
        tts : `bool`, Optional
            Whether the message is text-to-speech.
        show_source : `bool`, Optional
            Whether the source message should be shown as well. Defaults to `True`.
        
        Raises
        ------
        TypeError
            - If `allowed_mentions` contains an element of invalid type.
            - If `embed` was given as `list`, but it contains not only ``EmbedBase`` instances.
            - If `content` parameter was given as ``EmbedBase`` instance, meanwhile `embed` parameter was given as well.
        ValueError
            If `allowed_mentions`'s elements' type is correct, but one of their value is invalid.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            If `interaction` was not given an ``InteractionEvent`` instance.
        
        Notes
        -----
        Discord do not returns message data, so the method cannto return a ``Message`` either.
        
        By calling the method on the same interaction twice, you will get:
        
        ```
        DiscordException Not Found (404), code=10062: Unknown interaction
        ```
        """
        if __debug__:
            if not isinstance(interaction, InteractionEvent):
                raise AssertionError(f'`interaction` can be given as `{InteractionEvent.__name__}` instance, got '
                    f'{interaction.__class__.__name__}.')
        
        # Embed check order:
        # 1.: None
        # 2.: Embed -> [embed]
        # 3.: list of Embed -> embed[:10] or None
        # 4.: raise
        
        if embed is None:
            pass
        elif isinstance(embed, EmbedBase):
            embed = [embed]
        elif isinstance(embed, (list, tuple)):
            if embed:
                if __debug__:
                    for index, element in enumerate(embed):
                        if isinstance(element, EmbedBase):
                            continue
                        
                        raise TypeError(f'`embed` was given as a `list`, but it\'s element under index `{index}` '
                            f'is not `{EmbedBase.__name__}` instance, but {embed_element.__class__.__name__}`, got: '
                            f'{embed.__class__.__name__}.')
                
                embed = embed[:10]
            else:
                embed = None
            
        else:
            raise TypeError(f'`embed` was not given as `{EmbedBase.__name__}` instance, neither as a list of '
                f'{EmbedBase.__name__} instances, got {embed.__class__.__name__}.')
        
        # Content check order:
        # 1.: None
        # 2.: str
        # 3.: Embed -> embed = [content]
        # 4.: list of Embed -> embed = content[:10]
        # 5.: object -> str(content)
        
        if content is None:
            pass
        elif isinstance(content, str):
            if not content:
                content = None
        elif isinstance(content, EmbedBase):
            if __debug__:
                if (embed is not None):
                    raise TypeError(f'Multiple embeds were given, got content={content!r}, embed={embed!r}.')
            
            embed = [content]
            content = None
        else:
            # Check for list of embeds as well.
            if isinstance(content, (list, tuple)):
                if content:
                    for element in content:
                        if isinstance(element, EmbedBase):
                            continue
                        
                        is_list_of_embeds = False
                        break
                    else:
                        is_list_of_embeds = True
                else:
                    is_list_of_embeds = False
            else:
                is_list_of_embeds = False
            
            if is_list_of_embeds:
                if __debug__:
                    if (embed is not None):
                        raise TypeError(f'Multiple embeds were given, got content={content!r}, embed={embed!r}.')
                
                embed = content[:10]
                content = None
            else:
                content = str(content)
                if not content:
                    content = None
        
        message_data = {}
        contains_content = False
        
        if (content is not None):
            message_data['content'] = content
            contains_content = True
        
        if (embed is not None):
            message_data['embeds'] = [embed.to_data() for embed in embed]
            contains_content = True
        
        if (allowed_mentions is not ...):
            message_data['allowed_mentions'] = self._parse_allowed_mentions(allowed_mentions)
        
        if tts:
            message_data['tts'] = True
        
        data = {}
        if contains_content:
            data['data'] = message_data
            
            if show_source:
                response_type = InteractionResponseTypes.message_and_source
            else:
                response_type = InteractionResponseTypes.message
        else:
            if show_source:
                response_type = InteractionResponseTypes.source
            else:
                response_type = InteractionResponseTypes.acknowledge
        
        data['type'] = response_type
        
        await self.http.interaction_response_message_create(interaction.id, interaction.token, data)
        # No message data is provided, return `None`.
        return None
    
    
    async def interaction_response_message_edit(self, interaction, content=..., embed=..., allowed_mentions=...):
        """
        Edits the given `interaction`'s source response.
        
        This method is a coroutine.
        
        Parameters
        ----------
        interaction : ``InteractionEvent`` instance
            Interaction, what's source response message will be edited.
        content : `str`, ``EmbedBase`` or `Any`, Optional
            The new content of the message.
            
            If given as `str` then the message's content will be edited with it. If given as any non ``EmbedBase``
            instance, then it will be cased to string first.
            
            By passing it as empty string, you can remove the message's content.
            
            If given as ``EmbedBase`` instance, then the message's embeds will be edited with it.
        embed : `None`, ``EmbedBase`` instance or `list` of ``EmbedBase`` instances, Optional
            The new embedded content of the message. By passing it as `None`, you can remove the old.
            
            If `embed` and `content` parameters are both given as  ``EmbedBase`` instance, then `TypeError` is raised.
        allowed_mentions : `None`,  `str`, ``UserBase``, ``Role``, `list` of (`str`, ``UserBase``, ``Role`` ), Optional
            Which user or role can the message ping (or everyone). Check ``._parse_allowed_mentions``
            for details.
        
        Raises
        ------
        TypeError
            - If `allowed_mentions` contains an element of invalid type.
            - If `embed` was given as `list`, but it contains not only ``EmbedBase`` instances.
            - If `content` parameter was given as ``EmbedBase`` instance, meanwhile `embed` parameter was given as well.
        ValueError
            If `allowed_mentions`'s elements' type is correct, but one of their value is invalid.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            - If `interaction` was not given as ``InteractionEvent`` instance.
            - If the client's application is not yet synced.
        """
        application_id = self.application.id
        if __debug__:
            if application_id == 0:
                raise AssertionError('The client\'s application is not yet synced.')
        
        if __debug__:
            if not isinstance(interaction, InteractionEvent):
                raise AssertionError(f'`interaction` can be given as `{InteractionEvent.__name__}` instance, got '
                    f'{interaction.__class__.__name__}.')
        
        # Embed check order:
        # 1.: Elipsis
        # 2.: None
        # 3.: Embed : -> [embed]
        # 4.: list of Embed -> embed[:10] or None
        # 5.: raise
        
        if embed is ...:
            pass
        elif embed is None:
            pass
        elif isinstance(embed, EmbedBase):
            embed = [embed]
        elif isinstance(embed, (list, tuple)):
            if embed:
                if __debug__:
                    for index, element in enumerate(embed):
                        if isinstance(element, EmbedBase):
                            continue
                        
                        raise TypeError(f'`embed` was given as a `list`, but it\'s element under index `{index}` '
                            f'is not `{EmbedBase.__name__}` instance, but {embed_element.__class__.__name__}`, got: '
                            f'{embed.__class__.__name__}.')
                
                embed = embed[:10]
            else:
                embed = None
        else:
            raise TypeError(f'`embed` was not given as `{EmbedBase.__name__}` instance, neither as a list of '
                f'{EmbedBase.__name__} instances, got {embed.__class__.__name__}.')
        
        # Content check order:
        # 1.: Elipsis
        # 2.: None
        # 3.: str
        # 4.: Embed -> embed = [content]
        # 5.: list of Embed -> embed = content[:10]
        # 6.: object -> str(content)
        
        if content is ...:
            pass
        elif content is None:
            content = ''
        elif isinstance(content, str):
            pass
        elif isinstance(content, EmbedBase):
            if __debug__:
                if (embed is not ...):
                    raise ValueError(f'Multiple embeds were given, got content={content!r}, embed={embed!r}.')
            
            embed = [content]
            content = ...
        else:
            # Check for list of embeds as well.
            if isinstance(content, (list, tuple)):
                if content:
                    for element in content:
                        if isinstance(element, EmbedBase):
                            continue
                        
                        is_list_of_embeds = False
                        break
                    else:
                        is_list_of_embeds = True
                else:
                    is_list_of_embeds = False
            else:
                is_list_of_embeds = False
            
            if is_list_of_embeds:
                if __debug__:
                    if (embed is not ...):
                        raise ValueError(f'Multiple embeds were given, got content={content!r}, embed={embed!r}.')
                
                embed = content[:10]
                content = ...
            else:
                content = str(content)
        
        
        # Build payload
        message_data = {}
        
        # Discord docs say, content can be nullable, but nullable content is just ignored.
        if (content is not ...):
            message_data['content'] = content
        
        if (embed is not ...):
            if (embed is not None):
                embed = [embed.to_data() for embed in embed]
            
            message_data['embeds'] = embed
        
        if (allowed_mentions is not ...):
            message_data['allowed_mentions'] = self._parse_allowed_mentions(allowed_mentions)
        
        if not message_data:
            return
        
        # We receive the new message data, but we do not update the message, so dispatch events can get the difference.
        await self.http.interaction_response_message_edit(application_id, interaction.id, interaction.token,
            message_data)
    
    
    async def interaction_response_message_delete(self, interaction):
        """
        Deletes the given `interaction`'s source response message.
        
        This method is a coroutine.
        
        Parameters
        ----------
        interaction : ``InteractionEvent`` instance
            Interaction, what's source response message will be deleted.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            - If `interaction` was not given as ``InteractionEvent`` instance.
            - If the client's application is not yet synced.
        """
        application_id = self.application.id
        if __debug__:
            if application_id == 0:
                raise AssertionError('The client\'s application is not yet synced.')
        
        if __debug__:
            if not isinstance(interaction, InteractionEvent):
                raise AssertionError(f'`interaction` can be given as `{InteractionEvent.__name__}` instance, got '
                    f'{interaction.__class__.__name__}.')
        
        await self.http.interaction_response_message_delete(application_id, interaction.id, interaction.token)
    
    
    async def interaction_followup_message_create(self, interaction, content=None, *, embed=None, allowed_mentions=...,
            tts=False):
        """
        Sends a followup message with the given interaction.
        
        This method is a coroutine.
        
        Parameters
        ----------
        interaction : ``InteractionEvent`` instance
            Interaction to create followup message with.
        content : `str`, ``EmbedBase``, `Any`, Optional
            The message's content if given. If given as `str` or empty string, then no content will be sent, meanwhile
            if any other non `str` or ``EmbedBase`` instance is given, then will be casted to string.
            
            If given as ``EmbedBase`` instance, then is sent as the message's embed.
            
        embed : ``EmbedBase`` instance or `list` of ``EmbedBase`` instances, Optional
            The embedded content of the message.
            
            If `embed` and `content` parameters are both given as  ``EmbedBase`` instance, then `TypeError` is raised.
        allowed_mentions : `None`,  `str`, ``UserBase``, ``Role``, `list` of (`str`, ``UserBase``, ``Role`` ), Optional
            Which user or role can the message ping (or everyone). Check ``._parse_allowed_mentions`` for details.
        tts : `bool`, Optional
            Whether the message is text-to-speech.
        
        Returns
        -------
        message : `None` or ``Message``
            Returns `None` if there is nothing to send.
        
        Raises
        ------
        TypeError
            - If `allowed_mentions` contains an element of invalid type.
            - If `embed` was given as `list`, but it contains not only ``EmbedBase`` instances.
            - `content` parameter was given as ``EmbedBase`` instance, meanwhile `embed` parameter was given as well.
            - If ivalid file type would be sent.
        ValueError
            - If `allowed_mentions`'s elements' type is correct, but one of their value is invalid.
            - If more than `10` files would be sent.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            - If `interaction` was not given as ``InteractionEvent`` instance.
            - If the client's application is not yet synced.
        
        Notes
        -----
        Can be used before calling ``.interaction_response_message_create``.
        """
        application_id = self.application.id
        if __debug__:
            if application_id == 0:
                raise AssertionError('The client\'s application is not yet synced.')
        
        if __debug__:
            if not isinstance(interaction, InteractionEvent):
                raise AssertionError(f'`interaction` can be given as `{InteractionEvent.__name__}` instance, got '
                    f'{interaction.__class__.__name__}.')
        
        # Embed check order:
        # 1.: None
        # 2.: Embed -> [embed]
        # 3.: list of Embed -> embed[:10] or None
        # 4.: raise
        
        if embed is None:
            pass
        elif isinstance(embed, EmbedBase):
            embed = [embed]
        elif isinstance(embed, (list, tuple)):
            if embed:
                if __debug__:
                    for index, element in enumerate(embed):
                        if isinstance(element, EmbedBase):
                            continue
                        
                        raise TypeError(f'`embed` was given as a `list`, but it\'s element under index `{index}` '
                            f'is not `{EmbedBase.__name__}` instance, but {embed_element.__class__.__name__}`, got: '
                            f'{embed.__class__.__name__}.')
                
                embed = embed[:10]
            else:
                embed = None
            
        else:
            raise TypeError(f'`embed` was not given as `{EmbedBase.__name__}` instance, neither as a list of '
                f'{EmbedBase.__name__} instances, got {embed.__class__.__name__}.')
        
        # Content check order:
        # 1.: None
        # 2.: str
        # 3.: Embed -> embed = [content]
        # 4.: list of Embed -> embed = content[:10]
        # 5.: object -> str(content)
        
        if content is None:
            pass
        elif isinstance(content, str):
            if not content:
                content = None
        elif isinstance(content, EmbedBase):
            if __debug__:
                if (embed is not None):
                    raise TypeError(f'Multiple embeds were given, got content={content!r}, embed={embed!r}.')
            
            embed = [content]
            content = None
        else:
            # Check for list of embeds as well.
            if isinstance(content, (list, tuple)):
                if content:
                    for element in content:
                        if isinstance(element, EmbedBase):
                            continue
                        
                        is_list_of_embeds = False
                        break
                    else:
                        is_list_of_embeds = True
                else:
                    is_list_of_embeds = False
            else:
                is_list_of_embeds = False
            
            if is_list_of_embeds:
                if __debug__:
                    if (embed is not None):
                        raise TypeError(f'Multiple embeds were given, got content={content!r}, embed={embed!r}.')
                
                embed = content[:10]
                content = None
            else:
                content = str(content)
                if not content:
                    content = None
        
        message_data = {}
        contains_content = False
        
        if (content is not None):
            message_data['content'] = content
            contains_content = True
        
        if (embed is not None):
            message_data['embeds'] = [embed.to_data() for embed in embed]
            contains_content = True
        
        if (allowed_mentions is not ...):
            message_data['allowed_mentions'] = self._parse_allowed_mentions(allowed_mentions)
        
        if tts:
            message_data['tts'] = True
        
        if not contains_content:
            return None
        
        data = await self.http.interaction_followup_message_create(application_id, interaction.id, interaction.token,
            message_data)
        
        return interaction.channel._create_new_message(data)
    
    
    async def interaction_followup_message_edit(self, interaction, message, content=..., *, embed=...,
            allowed_mentions=...):
        """
        Edits the given interaction followup message.
        
        This method is a coroutine.
        
        Parameters
        ----------
        interaction : ``InteractionEvent`` instance
            Interaction with what the followup message was sent with.
        message : ``Message`` or ``MessageRepr``, `int` instance
            The interaction followup's message to edit.
        content : `str`, ``EmbedBase`` or `Any`, Optional
            The new content of the message.
            
            If given as `str` then the message's content will be edited with it. If given as any non ``EmbedBase``
            instance, then it will be cased to string first.
            
            By passing it as empty string, you can remove the message's content.
            
            If given as ``EmbedBase`` instance, then the message's embeds will be edited with it.
        embed : `None`, ``EmbedBase`` instance or `list` of ``EmbedBase`` instances, Optional
            The new embedded content of the message. By passing it as `None`, you can remove the old.
            
            If `embed` and `content` parameters are both given as  ``EmbedBase`` instance, then `TypeError` is raised.
        allowed_mentions : `None`,  `str`, ``UserBase``, ``Role``, `list` of (`str`, ``UserBase``, ``Role`` ), Optional
            Which user or role can the message ping (or everyone). Check ``._parse_allowed_mentions``
            for details.
        
        Raises
        ------
        TypeError
            - If `allowed_mentions` contains an element of invalid type.
            - If `embed` was given as `list`, but it contains not only ``EmbedBase`` instances.
            - If `content` parameter was given as ``EmbedBase`` instance, meanwhile `embed` parameter was given as well.
            - If `message` was not given neither as ``Message``, ``MessageRepr``  or `int` instance.
        ValueError
            If `allowed_mentions`'s elements' type is correct, but one of their value is invalid.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            - If `interaction` was not given as ``InteractionEvent`` instance.
            - If the client's application is not yet synced.
        """
        application_id = self.application.id
        if __debug__:
            if application_id == 0:
                raise AssertionError('The client\'s application is not yet synced.')
        
        if __debug__:
            if not isinstance(interaction, InteractionEvent):
                raise AssertionError(f'`interaction` can be given as `{InteractionEvent.__name__}` instance, got '
                    f'{interaction.__class__.__name__}.')
        
        # Detect message id
        # 1.: Message
        # 2.: int (str)
        # 3.: MessageRepr
        # 5.: raise
        
        if isinstance(message, Message):
            message_id = message.id
        else:
            message_id = maybe_snowflake(message)
            if (message_id is not None):
                pass
            elif isinstance(message, MessageRepr):
                # Cannot check author id, skip
                message_id = message.id
            else:
                raise TypeError(f'`message` can be given as `{Message.__name__}`, `{MessageRepr.__name__}` or as '
                    f'`int` instance, got {message.__class__.__name__}`.')
        
        # Embed check order:
        # 1.: Elipsis
        # 2.: None
        # 3.: Embed : -> [embed]
        # 4.: list of Embed -> embed[:10] or None
        # 5.: raise
        
        if embed is ...:
            pass
        elif embed is None:
            pass
        elif isinstance(embed, EmbedBase):
            embed = [embed]
        elif isinstance(embed, (list, tuple)):
            if embed:
                if __debug__:
                    for index, element in enumerate(embed):
                        if isinstance(element, EmbedBase):
                            continue
                        
                        raise TypeError(f'`embed` was given as a `list`, but it\'s element under index `{index}` '
                            f'is not `{EmbedBase.__name__}` instance, but {embed_element.__class__.__name__}`, got: '
                            f'{embed.__class__.__name__}.')
                
                embed = embed[:10]
            else:
                embed = None
        else:
            raise TypeError(f'`embed` was not given as `{EmbedBase.__name__}` instance, neither as a list of '
                f'{EmbedBase.__name__} instances, got {embed.__class__.__name__}.')
        
        # Content check order:
        # 1.: Elipsis
        # 2.: None
        # 3.: str
        # 4.: Embed -> embed = [content]
        # 5.: list of Embed -> embed = content[:10]
        # 6.: object -> str(content)
        
        if content is ...:
            pass
        elif content is None:
            content = ''
        elif isinstance(content, str):
            pass
        elif isinstance(content, EmbedBase):
            if __debug__:
                if (embed is not ...):
                    raise ValueError(f'Multiple embeds were given, got content={content!r}, embed={embed!r}.')
            
            embed = [content]
            content = ...
        else:
            # Check for list of embeds as well.
            if isinstance(content, (list, tuple)):
                if content:
                    for element in content:
                        if isinstance(element, EmbedBase):
                            continue
                        
                        is_list_of_embeds = False
                        break
                    else:
                        is_list_of_embeds = True
                else:
                    is_list_of_embeds = False
            else:
                is_list_of_embeds = False
            
            if is_list_of_embeds:
                if __debug__:
                    if (embed is not ...):
                        raise ValueError(f'Multiple embeds were given, got content={content!r}, embed={embed!r}.')
                
                embed = content[:10]
                content = ...
            else:
                content = str(content)
        
        # Build payload
        message_data = {}
        
        # Discord docs say, content can be nullable, but nullable content is just ignored.
        if (content is not ...):
            message_data['content'] = content
        
        if (embed is not ...):
            if (embed is not None):
                embed = [embed.to_data() for embed in embed]
            
            message_data['embeds'] = embed
        
        if (allowed_mentions is not ...):
            message_data['allowed_mentions'] = self._parse_allowed_mentions(allowed_mentions)
        
        if not message_data:
            return
        
        # We receive the new message data, but we do not update the message, so dispatch events can get the difference.
        await self.http.interaction_followup_message_edit(application_id, interaction.id, interaction.token, message_id,
            message_data)
    
    
    async def interaction_followup_message_delete(self, interaction, message):
        """
        Deletes an interaction's followup message.
        
        This method is a coroutine.
        
        Parameters
        ----------
        interaction : ``InteractionEvent`` instance
            Interaction with what the followup message was sent with.
        message : ``Message`` or ``MessageRepr``, `int` instance
            The interaction followup's message to edit.
        
        Raises
        ------
        TypeError
            If `message` was not given neither as ``Message``, ``MessageRepr``  or `int` instance.
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        AssertionError
            - If `interaction` was not given as ``InteractionEvent`` instance.
            - If the client's application is not yet synced.
        """
        application_id = self.application.id
        if __debug__:
            if application_id == 0:
                raise AssertionError('The client\'s application is not yet synced.')
        
        if __debug__:
            if not isinstance(interaction, InteractionEvent):
                raise AssertionError(f'`interaction` can be given as `{InteractionEvent.__name__}` instance, got '
                    f'{interaction.__class__.__name__}.')
        
        # Detect message id
        # 1.: Message
        # 2.: int (str)
        # 3.: MessageRepr
        # 5.: raise
        
        if isinstance(message, Message):
            message_id = message.id
        else:
            message_id = maybe_snowflake(message)
            if (message_id is not None):
                pass
            elif isinstance(message, MessageRepr):
                # Cannot check author id, skip
                message_id = message.id
            else:
                raise TypeError(f'`message` can be given as `{Message.__name__}`, `{MessageRepr.__name__}` or as '
                    f'`int` instance, got {message.__class__.__name__}`.')
        
        await self.http.interaction_followup_message_delete(application_id, interaction.id, interaction.token, message_id)
    
    
    # Relationship related
    
    async def relationship_delete(self, relationship):
        """
        Deletes the given relationship.
        
        This method is a coroutine.
        
        Parameters
        ----------
        relationship : ``Relationship``
            The relationship to delete.

        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        
        Notes
        -----
        This endpoint is available only for user accounts.
        """
        await self.http.relationship_delete(relationship.user.id)
    
    async def relationship_create(self, user, relationship_type=None):
        """
        Creates a relationship with the given user.
        
        This method is a coroutine.
        
        Parameters
        ----------
        user : ``Client`` or ``User``
            The user with who the relationsthip will be created.
        relationship_type : ``RelationshipType``, Optional
            The type of the relationship.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        
        Notes
        -----
        This endpoint is available only for user accounts.
        """
        data = {}
        if (relationship_type is not None):
            data['type'] = relationship_type.value
        await self.http.relationship_create(user.id, data)
    
    async def relationship_friend_request(self, user):
        """
        Sends a friend request to the given user.
        
        This method is a coroutine.
        
        Parameters
        ----------
        user : ``Client`` or ``User``
            The user, who will receive the friend request.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        
        Notes
        -----
        This endpoint is available only for user accounts.
        """
        data = {
            'username'      : user.name,
            'discriminator' : str(user.discriminator)
                }
        await self.http.relationship_friend_request(data)
    
    async def update_application_info(self):
        """
        Updates the client's application's info.
        
        This method is a coroutine.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        
        Notes
        -----
        Meanwhile the clients logs in this method is called to ensrue that the client's application info is loaded.
        
        This endpoint is available only for bot accounts.
        """
        if self.is_bot:
            data = await self.http.client_application_info()
            self.application = self.application._create_update(data, False)
    
    async def client_gateway(self):
        """
        Requests the gateway information for the client.
        
        Only `1` request can be done at a time and every other will yield the result of first started one.
        
        This method is a coroutine.
        
        Returns
        -------
        data : `dict` of (`str`, `Any`) items
        
        Raises
        ------
        ConnectionError
            No internet connection or if the request raised any ``DiscordException``.
        InvalidToken
            When the client's token is invalid.
        DiscordException
            If any exception was received from the Discord API.
        """
        if self._gateway_requesting:
            gateway_waiter = self._gateway_waiter
            if gateway_waiter is None:
                gateway_waiter = self._gateway_waiter = Future(KOKORO)
            
            return await gateway_waiter
        
        self._gateway_requesting = True
        
        try:
            while True:
                if self.is_bot:
                    coro = self.http.client_gateway_bot()
                else:
                    coro = self.http.client_gateway_hooman()
                try:
                    data = await coro
                except DiscordException as err:
                    status = err.status
                    if status == 401:
                        await self.disconnect()
                        raise InvalidToken() from err
                    
                    if status >= 500:
                        await sleep(2.5, KOKORO)
                        continue
                    
                    raise
                
                break
            
            try:
                session_start_limit_data = data['session_start_limit']
            except KeyError:
                gateway_max_concurrency = 1
            else:
                gateway_max_concurrency = session_start_limit_data.get('max_concurrency', 1)
            
            self._gateway_max_concurrency = gateway_max_concurrency
        except BaseException as err:
            self._gateway_requesting = False
            gateway_waiter = self._gateway_waiter
            if (gateway_waiter is not None):
                self._gateway_waiter = None
                gateway_waiter.set_exception_if_pending(err)
            
            raise
        
        self._gateway_requesting = False
        gateway_waiter = self._gateway_waiter
        if (gateway_waiter is not None):
            self._gateway_waiter = None
            gateway_waiter.set_result_if_pending(data)
        
        return data
    
    async def client_gateway_url(self):
        """
        Requests the client's gateway url. To avoid unreasoned requests when sharding, if this request was done at the
        last `60` seconds then returns the last generated url.
        
        This method is a coroutine.
        
        Raises
        ------
        ConnectionError
            No internet connection or if the request raised any ``DiscordException``.
        InvalidToken
            When the client's token is invalid.
        DiscordException
            If any exception was received from the Discord API.
        
        Returns
        -------
        gateway_url : `str`
            The url to what the gateways' webscoket will be connected.
        """
        if self._gateway_time > (LOOP_TIME()-60.0):
            return self._gateway_url
        
        data = await self.client_gateway()
        self._gateway_url = gateway_url = f'{data["url"]}?encoding=json&v={API_VERSION}&compress=zlib-stream'
        self._gateway_time = LOOP_TIME()
        
        return gateway_url
    
    async def client_gateway_reshard(self, force=False):
        """
        Reshards the client. And also updates it's gatewas url as a sidenote.
        
        Should be called only if every shard is down.
        
        This method is a coroutine.
        
        Parameters
        ----------
        force : `bool`
            Whether the the client should reshard to lower amount of shards if needed.
        
        Raises
        ------
        ConnectionError
            No internet connection or if the request raised any ``DiscordException``.
        InvalidToken
            When the client's token is invalid.
        DiscordException
            If any exception was received from the Discord API.
        """
        data = await self.client_gateway()
        self._gateway_url = f'{data["url"]}?encoding=json&v={API_VERSION}&compress=zlib-stream'
        self._gateway_time = LOOP_TIME()
        
        old_shard_count = self.shard_count
        if old_shard_count == 0:
            old_shard_count = 1
        
        new_shard_count = data['shards']
        
        # Do we have more shards already?
        if (not force) and (old_shard_count >= new_shard_count):
            return
        
        if new_shard_count == 1:
            new_shard_count = 0
        
        self.shard_count = new_shard_count
        
        gateway = self.gateway
        if type(gateway) is DiscordGateway:
            if new_shard_count:
                self.gateway = DiscordGatewaySharder(self)
        else:
            if new_shard_count:
                gateway.reshard()
            else:
                self.gateway = DiscordGateway(self)
    
    async def hypesquad_house_change(self, house):
        """
        Changes the client's hypesquad house.
        
        This method is a coroutine.
        
        Parameters
        ----------
        house : `int` or ``HypesquadHouse`` instance
            The hypesquad house to join.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        
        Raises
        ------
        TypeError
            `house` was not given as `int`  neither as ``HypesquadHouse`` instance.
        
        Notes
        -----
        User account only.
        """
        if isinstance(house, HypesquadHouse):
            house_id = house.value
        elif isinstance(house, int):
            house_id = house
        else:
            raise TypeError(f'`house` can be given as `int` or `{HypesquadHouse.__name__}` instance, got '
                f'{house.__class__.__name__}.')
        
        await self.http.hypesquad_house_change({'house_id':house_id})
    
    async def hypesquad_house_leave(self):
        """
        Leaves the client from it's current hypesquad house.
        
        This method is a coroutine.
        
        Raises
        ------
        ConnectionError
            No internet connection.
        DiscordException
            If any exception was received from the Discord API.
        
        Notes
        -----
        User account only.
        """
        await self.http.hypesquad_house_leave()
    
    def start(self):
        """
        Starts the clients's connecting to Discord. If the client is already running, raises `RuntimeError`.
        
        The return of the method depends on the thread, from which it was called from.
        
        Returns
        -------
        task : `bool`, ``Task`` or ``FutureAsyncWrapper``
            - If the method was called from the client's thread (KOKORO), then returns a ``Task``. The task will return
                `True`, if connecting was successful.
            - If the method was called from an ``EventThread``, but not from the client's, then returns a
                `FutureAsyncWrapper`. The task will return `True`, if connecting was successful.
            - If the method was called from any other thread, then waits for the connecter task to finish and returns
                `True`, if it was successful.
        
        Raises
        ------
        RuntimeError
            If the client is already running.
        """
        if self.running:
            raise RuntimeError(f'{self!r} is already running!')
        
        task = Task(self.connect(), KOKORO)
        
        thread = current_thread()
        if thread is KOKORO:
            return task
        
        if isinstance(thread, EventThread):
            # Asyncwrap wakes up KOKORO
            return task.asyncwrap(thread)
        
        KOKORO.wakeup()
        return task.syncwrap().wait()
    
    def stop(self):
        """
        Starts disconneting the client.
        
        The return of the method depends on the thread, from which it was called from.
        
        Returns
        -------
        task : `None`, ``Task`` or ``FutureAsyncWrapper``
            - If the method was called from the client's thread (KOKORO), then returns a ``Task``.
            - If the method was called from an ``EventThread``, but not from the client's, then returns a
                `FutureAsyncWrapper`.
            - If the method was called from any other thread, returns `None` when disconnecting finished.
        """
        task = Task(self.disconnect(), KOKORO)
        
        thread = current_thread()
        if thread is KOKORO:
            return task
        
        if isinstance(thread, EventThread):
            # Asyncwrap wakes up KOKORO
            return task.asyncwrap(thread)
        
        KOKORO.wakeup()
        task.syncwrap().wait()
    
    async def connect(self):
        """
        Starts connecting the client to Discord, fills up the undefined events and creates the task, what will keep
        receiving the data from Discord (``._connect``).
        
        If you want to start the connecting process consider using the toplevel ``.start`` or ``start_clients`` instead.
        
        This method is a coroutine.
        
        Returns
        -------
        success : `bool`
            Whether the client could be started.
        
        Raises
        ------
        RuntimeError
            If the client is already running.
        """
        if self.running:
            raise RuntimeError(f'{self!r} is already running!')
        
        try:
            data = await self.client_login_static()
        except BaseException as err:
            if isinstance(err, ConnectionError) and err.args[0] == 'Invalid adress':
                after = (
                    'Connection failed, could not connect to Discord.\n Please check your internet connection / has '
                    'Python rights to use it?\n'
                        )
            else:
                after = None
            
            before = [
                'Exception occured at calling ',
                self.__class__.__name__,
                '.connect\n',
                    ]
            
            await KOKORO.render_exc_async(err, before, after)
            return False
        
        if type(data) is not dict:
            sys.stderr.write(''.join([
                'Connection failed, could not connect to Discord.\n'
                'Received invalid data:\n',
                repr(data), '\n']))
            return False
        
        self._init_on_ready(data)
        await self.client_gateway_reshard()
        await self.gateway.start()
        
        if self.is_bot:
            task = Task(self.update_application_info(), KOKORO)
            if __debug__:
                task.__silence__()
        
        # Check it twice, because meanwhile logging on, connect calls are not limited
        if self.running:
            raise RuntimeError(f'{self!r} is already running!')
        
        self.running = True
        PARSER_DEFAULTS.register(self)
        Task(self._connect(), KOKORO)
        return True
    
    async def _connect(self):
        """
        Connects the client's gateway(s) to Discord and reconnects them if needed.
        
        This method is a coroutine.
        """
        try:
            while True:
                try:
                    await self.gateway.run()
                except (GeneratorExit, CancelledError) as err:
                    # For now only here. These errors occured randomly for me since I made the wrapper, only once-once,
                    # and it was not the wrapper causing them, so it is time to say STOP.
                    # I also know `GeneratorExit` will show up as RuntimeError, but it is already a RuntimeError.
                    try:
                        await KOKORO.render_exc_async(err, [
                            'Ignoring unexpected outer Task or coroutine cancellation at ',
                            repr(self),
                            '._connect:\n',
                                ],)
                    except (GeneratorExit, CancelledError) as err:
                        sys.stderr.write(
                            f'Ignoring unexpected outer Task or coroutine cancellation at {self!r}._connect as '
                            f'{err!r} meanwhile rendering an exception for the same reason.\n The client will '
                            f'reconnect.\n')
                    continue
                
                except DiscordGatewayException as err:
                    if err.code in DiscordGatewayException.RESHARD_ERROR_CODES:
                        sys.stderr.write(
                            f'{err.__class__.__name__} occured, at {self!r}._connect:\n'
                            f'{err!r}\n'
                            f'The client will reshard itself and reconnect.\n'
                                )
                        
                        await self.client_gateway_reshard(force=True)
                        continue
                    
                    raise
                
                else:
                    if not self.running:
                        break
                    
                    while True:
                        try:
                            await sleep(5.0, KOKORO)
                            try:
                                # We are down, why not reshard instantly?
                                await self.client_gateway_reshard()
                            except ConnectionError:
                                continue
                            else:
                                break
                        except (GeneratorExit, CancelledError) as err:
                            try:
                                await KOKORO.render_exc_async(err,[
                                    'Ignoring unexpected outer Task or coroutine cancellation at ',
                                    repr(self),
                                    '._connect:\n',
                                        ],)
                            except (GeneratorExit, CancelledError) as err:
                                sys.stderr.write(
                                    f'Ignoring unexpected outer Task or coroutine cancellation at {self!r}._connect as '
                                    f'{err!r} meanwhile rendering an exception for the same reason.\n The client will '
                                    f'reconnect.\n')
                            continue
                    continue
        except BaseException as err:
            if isinstance(err, InvalidToken) or \
                    (isinstance(err, DiscordGatewayException) and \
                     err.code in DiscordGatewayException.INTENT_ERROR_CODES):
                
                sys.stderr.write(
                    f'{err.__class__.__name__} occured, at {self!r}._connect:\n'
                    f'{err!r}\n'
                        )
            else:
                await KOKORO.render_exc_async(err,[
                    'Unexpected exception occured at ',
                    repr(self),
                    '._connect\n',
                        ],
                    'If you can reproduce this bug, Please send me a message or open an issue whith your code, and '
                    'with every detail how to reproduce it.\n'
                    'Thanks!\n')
        
        finally:
            try:
                await self.gateway.close()
            finally:
                PARSER_DEFAULTS.unregister(self)
                self.running = False
                
                if not self.guild_profiles:
                    return
                
                to_remove = []
                for guild in self.guild_profiles:
                    guild._delete(self)
                    if guild.clients:
                        continue
                    to_remove.append(guild)
                
                if to_remove:
                    for guild in to_remove:
                        del self.guild_profiles[guild]
                
                #needs to delete the references for cleanup
                guild = None
                to_remove = None
    
    async def join_voice_channel(self, channel):
        """
        Joins a voice client to the channel. If there is an already existing voice client at the respective guild,
        moves it.
        
        If not every library is installed, raises `RuntimeError`, or if the voice client fails to connect raises
        `TimeoutError`.
        
        This method is a coroutine.
        
        Parameters
        ----------
        channel : ``ChannelVoice``
            The channel to join to.
        
        Returns
        -------
        voice_client : ``VoiceClient``
        
        Raises
        ------
        RuntimeError
            If not every library is installed to join voice.
        TimeoutError
            If voice client fails to connect the given channel.
        """
        guild = channel.guild
        if guild is None:
            raise TimeoutError(f'Cannot join channel without guild: {channel!r}')
        
        try:
            voice_client = self.voice_clients[guild.id]
        except KeyError:
            voice_client = await VoiceClient(self, channel)
        else:
            if voice_client.channel is not channel:
                gateway = self._gateway_for(guild)
                await gateway._change_voice_state(guild.id, channel.id)
        
        return voice_client
    
    async def wait_for(self, event_name, check, timeout=None):
        """
        O(n) event waiter with massive overhead compared to other optimized event waiters.
        
        This method is a coroutine.
        
        Parameters
        ----------
        event_name : `str`
            The respective event's name.
        check : `callable`
            Check, what tells that the waiting is over.
            
            If the `check` returns `True` the received `args` are passed to the waiter future and returned by the
            method. However if the check returns any non `bool` value, then that object is pased next to `args` and
            returned as well.
        
        timeout : `None` or `float`
            Timeout after `TimeoutError` is raised and the waiting is cancelled.
        
        Returns
        -------
        result : `Any`
            Arguments passed to the `check` and the value returned by the `check` if it's type is not `bool`.
        
        Raised
        ------
        TimeoutError
            Timeout occured.
        BaseException
            Any exception raised by `check`.
        """
        wait_for_handler = self.events.get_handler(event_name, WaitForHandler)
        if wait_for_handler is None:
            wait_for_handler = WaitForHandler()
            self.events(wait_for_handler, name=event_name)
        
        future = Future(KOKORO)
        wait_for_handler.waiters[future] = check
        
        if (timeout is not None):
            future_or_timeout(future, timeout)
        
        try:
            return await future
        finally:
            waiters = wait_for_handler.waiters
            del waiters[future]
            
            if not waiters:
                self.events.remove(wait_for_handler, name=event_name)
    
    async def _delay_ready(self):
        """
        Delays the client's "ready" till it receives all of it guild's data. If caching is allowed (so by default),
        then it waits additional time till it requests all the members of it's guilds.
        
        This method is a coroutine.
        """
        ready_state = self.ready_state
        try:
            if self.is_bot:
                await ready_state
            
            if ready_state.guilds and CACHE_USER:
                await self._request_members2(ready_state.guilds)
                
            self.ready_state = None
        
        except CancelledError:
            pass
        else:
            Task(_with_error(self, self.events.ready(self)), KOKORO)
    
    async def _request_members2(self, guilds):
        """
        Requests the members of the client's guilds. Called after the client is started up and user caching is
        enabled (so by default).
        
        This method is a coroutine.
        
        Parameters
        ----------
        guilds : `list` of ``Guild`` objects
            The guilds, which users should be requested.
        """
        event_handler = self.events.guild_user_chunk
        
        try:
            waiter = event_handler.waiters.pop('0000000000000000')
        except KeyError:
            pass
        else:
            waiter.cancel()
        
        event_handler.waiters['0000000000000000'] = waiter = MassUserChunker(len(guilds))
        
        shard_count = self.shard_count
        if shard_count:
            guilds_by_shards = [[] for x in range(shard_count)]
            for guild in guilds:
                shard_index = (guild.id>>22)%shard_count
                guilds_by_shards[shard_index].append(guild)
            
            tasks = []
            gateways = self.gateway.gateways
            for index in range(shard_count):
                task = Task(self._request_members_loop(gateways[index], guilds_by_shards[index]), KOKORO)
                tasks.append(task)
            
            done, pending = await WaitTillExc(tasks, KOKORO)
            for task in pending:
                task.cancel()
            
            for task in done:
                task.result()
            
        else:
            await self._request_members_loop(self.gateway, guilds)

        
        try:
            await waiter
        except CancelledError:
            try:
                del event_handler.waiters['0000000000000000']
            except KeyError:
                pass
    
    @staticmethod
    async def _request_members_loop(gateway, guilds):
        """
        Called by ``._request_members2`` pararelly with other ``._request_members_loop``-s for each shard.
        
        The function requests all the members of given guilds without putting too much pressure on the respective
        gateway's ratelimits.
        
        This function is a coroutine.
        
        Parameters
        ----------
        gateway : ``DiscordGateway``
            The gateway to use for requests.
        guilds : `list` of ``Guild``
            The guilds, what's members should be requested.
        """
        sub_data = {
            'guild_id'  : 0,
            'query'     : '',
            'limit'     : 0,
            'presences' : CACHE_PRESENCE,
            'nonce'     : '0000000000000000',
                }
        
        data = {
            'op' : DiscordGateway.REQUEST_MEMBERS,
            'd'  : sub_data
                }
        
        for guild in guilds:
            sub_data['guild_id'] = guild.id
            await gateway.send_as_json(data)
            await sleep(0.6, KOKORO)
    
    async def _request_members(self, guild):
        """
        Requests the members of the given guild. Called when the client joins a guild and user caching is enabled
        (so by default).
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild``
            The guild, what's members will be requested.
        """
        event_handler = self.events.guild_user_chunk
        
        self._user_chunker_nonce = nonce = self._user_chunker_nonce+1
        nonce = nonce.__format__('0>16x')
        
        event_handler.waiters[nonce] = waiter = MassUserChunker(1)
        
        data = {
            'op' : DiscordGateway.REQUEST_MEMBERS,
            'd' : {
                'guild_id'  : guild.id,
                'query'     : '',
                'limit'     : 0,
                'presences' : CACHE_PRESENCE,
                'nonce'     : nonce
                    },
                }
        
        gateway = self._gateway_for(guild)
        await gateway.send_as_json(data)
        
        try:
            await waiter
        except CancelledError:
            try:
                del event_handler.waiters[nonce]
            except KeyError:
                pass
    
    async def request_members(self, guild, name, limit=1):
        """
        Requests the members of the given guild by their name.
        
        This method uses the client's gateway to request the users. If any of the parameters do not match their
        expected value or if timeout occures, returns an empty list instead of raising.
        
        This method is a coroutine.
        
        Parameters
        ----------
        guild : ``Guild``
            The guild, what's members will be requested.
        name : `str`
            The received user's name or nick should start with this string.
        limit : `int`
            The amount of users to received. Limited to `100`.
        
        Returns
        -------
        users : `list` of (``Client`` or ``User``) objects
        """
        #do we really need these checks?
        if limit > 100:
            limit = 100
        elif limit < 1:
            return []
        
        if not 0 < len(name) < 33:
            return []
        
        event_handler = self.events.guild_user_chunk
        
        self._user_chunker_nonce = nonce = self._user_chunker_nonce+1
        nonce = nonce.__format__('0>16x')
        
        event_handler.waiters[nonce] = waiter = SingleUserChunker()
        
        data = {
            'op' : DiscordGateway.REQUEST_MEMBERS,
            'd' : {
                'guild_id'  : guild.id,
                'query'     : name,
                'limit'     : limit,
                'presences' : CACHE_PRESENCE,
                'nonce'     : nonce,
                    },
                }
        
        gateway = self._gateway_for(guild)
        await gateway.send_as_json(data)
        
        try:
            return await waiter
        except CancelledError:
            try:
                del event_handler.waiters[nonce]
            except KeyError:
                pass
            
            return []
    
    async def disconnect(self):
        """
        Disconnects the client and closes it's wewbsocket(s). Till the client goes offline, it might take even over
        than `1` minute. Because bot accounts can not logout, so they need to wait for timeout.
        
        This method is a coroutine.
        """
        if not self.running:
            return
        
        self.running = False
        shard_count = self.shard_count
        
        # cancel shards
        if shard_count:
            for gateway in self.gateway.gateways:
                gateway.kokoro.cancel()
        else:
            self.gateway.kokoro.cancel()
        
        # Stop voice clients
        voice_clients = self.voice_clients
        if voice_clients:
            tasks = []
            for voice_client in self.voice_clients.values():
                tasks.append(Task(voice_client.disconnect(), KOKORO))
            
            future = WaitTillAll(tasks, KOKORO)
            tasks = None # clear references
            await future
            future = None # clear references
        
        if (not self.is_bot):
            await self.http.client_logout()
        
        if shard_count:
            tasks = []
            for gateway in self.gateway.gateways:
                websocket = gateway.websocket
                if (websocket is not None) and websocket.open:
                    tasks.append(Task(gateway.close(), KOKORO))
            
            if tasks:
                future = WaitTillAll(tasks, KOKORO)
                tasks = None # clear references
                await future
                future = None # clear references
            else:
                tasks = None # clear references
        
        else:
            websocket = self.gateway.websocket
            if (websocket is not None) and websocket.open:
                await self.gateway.close()
    
    def voice_client_for(self, message):
        """
        Returns the voice client for the given message's guild if it has any.
        
        Parameters
        ----------
        message : ``Message``
            The message what's voice client will be looked up.
        
        Returns
        -------
        voice_client : `None` or ``VoiceClient``
            The voice client if applicable.
        """
        guild = message.channel.guild
        if guild is None:
            return
        
        return self.voice_clients.get(guild.id)
    
    def get_guild(self, name, default=None):
        """
        Tries to find a guild by it's name. If there is no guild with the given name, then returns the passed
        default value.
        
        Parameters
        ----------
        name : `str`
            The guild's name to search.
        default : `Any`, Optional
            The default value, what will be returned if the guild was not found.
        
        Returns
        -------
        guild : ``Guild`` or `default`
        
        Raises
        ------
        AssertionError
            `name` was not given as `str` instance.
        """
        if __debug__:
            if not isinstance(name, str):
                raise AssertionError(f'`name` should have be given as `str` instance, got {name.__class__:__name__}.')
        
        if 1 < len(name) < 101:
            for guild in self.guild_profiles.keys():
                if guild.name == name:
                    return guild
        
        return default
    
    get_ratelimits_of = methodize(RatelimitProxy)
    
    @property
    def owner(self):
        """
        Returns the client's owner if applicable.
        
        If the client is a user account, or if it's ``.update_application_info`` was not called yet, then returns
        ``ZEROUSER``. If the client is owned by a ``Team``, then returns the team's owner.
        
        Returns
        -------
        owner : ``User``, ``Client``
        """
        application_owner = self.application.owner
        if type(application_owner) is Team:
            owner = application_owner.owner
        else:
            owner = application_owner
        
        return owner
    
    def is_owner(self, user):
        """
        Returns whether the passed user is one of the client's owners.
        
        Parameters
        ----------
        user : ``Client`` or ``User`` object
            The user who will be checked.
        
        Returns
        -------
        is_owner : `bool`
        """
        application_owner = self.application.owner
        if type(application_owner) is Team:
            if user in application_owner.accepted:
                return True
        else:
            if application_owner is user:
                return True
        
        additional_owner_ids = self._additional_owner_ids
        if (additional_owner_ids is not None) and (user.id in additional_owner_ids):
            return True
        
        return False
    
    def add_additional_owners(self, *users):
        """
        Adds additional users to be passed at the ``.is_owner`` check.
        
        Parameters
        ----------
        *users : `int` or ``UserBase`` instances
            The `.id` of the a user or the user itself to be added.
        
        Raises
        ------
        TypeError
            A user was passed with invalid type.
        """
        limit = len(users)
        if limit == 0:
            return
        
        index = 0
        while True:
            user = users[index]
            index += 1
            if not isinstance(user,(int, UserBase)):
                raise TypeError(f'User {index} was not passed neither as `int` or as `{UserBase.__name__}` instance, '
                    f'got {user.__class__.__name__}.')
            
            if index == limit:
                break
        
        additional_owner_ids = self._additional_owner_ids
        if additional_owner_ids is None:
            additional_owner_ids = self._additional_owner_ids = set()
        
        for user in users:
            if type(user) is int:
                pass
            elif isinstance(user, int):
                user = int(user)
            else:
                user = user.id
            
            additional_owner_ids.add(user)
    
    def remove_additional_owners(self, *users):
        """
        Removes additonal owners added by the ``.add_additional_owners`` method.
        
        Parameters
        ----------
        *users : `int` or ``UserBase`` instances
            The `.id` of the a user or the user itself to be removed.
        
        Raises
        ------
        TypeError
            A user was passed with invalid type.
        """
        limit = len(users)
        if limit == 0:
            return
        
        index = 0
        while True:
            user = users[index]
            index += 1
            if not isinstance(user, (int, UserBase)):
                raise TypeError(f'User {index} was not passed neither as `int` or as `{UserBase.__name__}` instance, '
                    f'got {user.__class__.__name__}.')
            
            if index==limit:
                break
        
        additional_owner_ids = self._additional_owner_ids
        if additional_owner_ids is None:
            additional_owner_ids = self._additional_owner_ids = set()
        
        for user in users:
            if type(user) is int:
                pass
            elif isinstance(user, int):
                user = int(user)
            else:
                user = user.id
            
            additional_owner_ids.discard(user)
    
    @property
    def owners(self):
        """
        Returns the owners of the client.
        
        Returns
        -------
        owners : `set` of (``Client`` or ``User``)
        """
        owners = set()
        
        application_owner = self.application.owner
        if type(application_owner) is Team:
            owners.update(application_owner.accepted)
        else:
            owners.add(application_owner)
        
        additional_owner_ids = self._additional_owner_ids
        if (additional_owner_ids is not None):
            for user_id in additional_owner_ids:
                user = create_partial_user(user_id)
                owners.add(user)
        
        return owners
    
    def _update(self, data):
        """
        Updates the client and returns it's old attribtes in a `dict` with `attribute-name`, `old-value` relation.
        
        Parameters
        ----------
        data : `dict` of (`str`, `Any`) items
            Data received from Discord.
        
        Returns
        -------
        old_attributes : `dict` of (`str`, `Any`) items
            All item in the returned dict is optional.
        
        Returned Data Structure
        -----------------------
        +-----------------------+-------------------+
        | Keys                  | Values            |
        +=======================+===================+
        | avatar                | ``Icon``          |
        +-----------------------+-------------------+
        | discriminator         | `int`             |
        +-----------------------+-------------------+
        | email                 | `None` or `str`   |
        +-----------------------+-------------------+
        | flags                 | ``UserFlag``      |
        +-----------------------+-------------------+
        | locale                | `str              |
        +-----------------------+-------------------+
        | mfa                   | `bool`            |
        +-----------------------+-------------------+
        | name                  | `str              |
        +-----------------------+-------------------+
        | premium_type          | ``PremiumType``   |
        +-----------------------+-------------------+
        | verified              | `bool`            |
        +-----------------------+-------------------+
        """
        old_attributes = {}
            
        name = data['username']
        if self.name != name:
            old_attributes['name'] = self.name
            self.name = name
                
        discriminator = int(data['discriminator'])
        if self.discriminator != discriminator:
            old_attributes['discriminator'] = self.discriminator
            self.discriminator = discriminator

        self._update_avatar(data, old_attributes)
        
        email = data.get('email')
        if self.email != email:
            old_attributes['email'] = self.email
            self.email = email
        
        premium_type = PremiumType.get(data.get('premium_type', 0))
        if self.premium_type is not premium_type:
            old_attributes['premium_type'] = premium_type
            self.premium_type = premium_type
        
        system = data.get('system', False)
        if self.system != system:
            old_attributes['system'] = self.system
            self.system = system
        
        verified = data.get('verified', False)
        if self.verified != verified:
            old_attributes['verified'] = self.verified
            self.verified = verified
        
        mfa = data.get('mfa_enabled', False)
        if self.mfa != mfa:
            old_attributes['mfa'] = self.mfa
            self.mfa = mfa
        
        flags = UserFlag(data.get('flags', 0))
        if self.flags != flags:
            old_attributes['flags'] = self.flags
            self.flags = flags
        
        locale = parse_locale(data)
        if self.locale != locale:
            old_attributes['locale'] = self.locale
            self.locale = locale
        
        return old_attributes
    
    def _update_no_return(self, data):
        """
        Updates the client by overwriting it's old attributes.
        
        Parameters
        ----------
        data : `dict` of (`str`, `Any`) items
            Data received from Discord.
        """
        self.name = data['username']
        
        self.discriminator = int(data['discriminator'])
        
        self._set_avatar(data)
        
        self.system = data.get('system', False)
        
        self.verified = data.get('verified', False)
        
        self.email = data.get('email')
        
        self.premium_type = PremiumType.get(data.get('premium_type', 0))
        
        self.mfa = data.get('mfa_enabled', False)
        
        self.flags = UserFlag(data.get('flags', 0))
        
        self.locale = parse_locale(data)
    
    def _update_profile_only(self, data, guild):
        """
        Used only when user caching is disabled. Updates the client's guild profile for the given guild and returns
        the changed old attributes in a `dict` with `attribute-name`, `old-value` relation.
        
        Parameters
        ----------
        data : `dict` of (`str`, `Any`) items
            Data received from Discord.
        guild : ``Guild``
            The respective guild of the guild profile.
        
        Returns
        -------
        old_attributes : `dict` of (`str`, `Any`) items
            All item in the returned dict is optional.
        
        Returned Data Structure
        -----------------------
        +---------------+-----------------------+
        | Keys          | Values                |
        +===============+=======================+
        | nick          | `str` / `None`        |
        +---------------+-----------------------+
        | roles         | `list` of ``Role``    |
        +---------------+-----------------------+
        | boosts_since  | `datetime` / `None`   |
        +---------------+-----------------------+
        """
        try:
            profile = self.guild_profiles[guild]
        except KeyError:
            self.guild_profiles[guild] = GuildProfile(data, guild)
            guild.users[self.id] = self
            return {}
        return profile._update(data, guild)
    
    def _update_profile_only_no_return(self, data, guild):
        """
        Used only when user caching is disabled. Updates the client's guild profile for the given guild.
        
        Parameters
        ----------
        data : `dict` of (`str`, `Any`) items
            Data received from Discord.
        guild : ``Guild``
            The respective guild of the guild profile.
        """
        try:
            profile = self.guild_profiles[guild]
        except KeyError:
            self.guild_profiles[guild] = GuildProfile(data, guild)
            guild.users[self.id] = self
        else:
            profile._update_no_return(data, guild)
    
    @property
    def friends(self):
        """
        Returns the client's friends.
        
        Returns
        -------
        relationships : `list` of ``Relationship`` objects
        """
        type_ = RelationshipType.friend
        return [rs for rs in self.relationships.values() if rs.type is type_]

    @property
    def blocked(self):
        """
        Returns the client's blocked relationships.
        
        Returns
        -------
        relationships : `list` of ``Relationship`` objects
        """
        type_ = RelationshipType.blocked
        return [rs for rs in self.relationships.values() if rs.type is type_]
    
    @property
    def received_requests(self):
        """
        Returns the received friend requests of the client.
        
        Returns
        -------
        relationships : `list` of ``Relationship`` objects
        """
        type_ = RelationshipType.pending_incoiming
        return [rs for rs in self.relationships.values() if rs.type is type_]
    
    @property
    def sent_requests(self):
        """
        Returns the sent friend requests of the client.
        
        Returns
        -------
        relationships : `list` of ``Relationship`` objects
        """
        type_ = RelationshipType.pending_outgoing
        return [rs for rs in self.relationships.values() if rs.type is type_]
    
    def _gateway_for(self, guild):
        """
        Returns the coresponding gateway of the client to the passed guild.
        
        Parameters
        ----------
        guild : ``Guild`` or `None`
            The guild what's gateway will be returned.
        
        Returns
        -------
        gateway : ``DiscordGateway``
        """
        shard_count = self.shard_count
        if shard_count:
            if guild is None:
                return self.gateway.gateways[0]
            
            guild_id = guild.id
            shard_index = (guild_id>>22)%shard_count
            
            return self.gateway.gateways[shard_index]
        
        return self.gateway


module_client_core.Client = Client
module_message.Client = Client
module_webhook.Client = Client
module_channel.Client = Client
module_invite.Client = Client
module_parsers.Client = Client
module_client_utils.Client = Client
module_guild.Client = Client

del module_client_core
del re
del URLS
del module_message
del module_webhook
del RATELIMIT_GROUPS
del DISCOVERY_CATEGORIES
del module_invite
del module_parsers
del methodize
del module_client_utils
del module_channel
del module_guild
