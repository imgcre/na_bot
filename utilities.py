import dataclasses
from datetime import datetime
from enum import Enum, auto
import inspect
import logging
import re
import time
from typing import Any, Callable, Dict, Generic, Iterable, Optional, Type, TypeVar, Union, get_args
from dataclasses import Field, dataclass, field
from abc import ABC, abstractmethod
import typing
from mirai import At, GroupMessage, MessageChain, Mirai, Plain, TempMessage
from mirai.models.entities import GroupMember, Group
from mirai.models.events import NudgeEvent, Event
import ast

if typing.TYPE_CHECKING:
    from plugin import Context, Plugin

T = TypeVar('T')

class AdminType(Enum):
    ACHV = auto()
    SUPER = auto()

class Upgraded():
    def __new__(cls, *args, **kwargs):
        obj = super().__new__(cls, *args, **kwargs)
        for k, v in typing.cast(dict[str, Field], cls.__dataclass_fields__).items():
            if hasattr(obj, k): continue
            _def = None
            if v.default_factory is not dataclasses.MISSING:
                _def = v.default_factory()
            if v.default is not dataclasses.MISSING:
                _def = v.default
            setattr(obj, k, _def)
        return obj

class ResolverMixer(ABC):
    @abstractmethod
    def resolver_mixin(self) -> Dict[type, Callable[..., Any]]: ...

class Target(Enum):
    GROUP = auto()
    TEMP = auto()
    KEEP = auto()


@dataclass
class User():
    id: int

@dataclass
class Msg():
    id: int

@dataclass
class MsgOp():
    bot: Mirai
    msg: Msg
    group: Group

    async def recall(self):
        await self.bot.recall(self.msg.id, self.group.id)

@dataclass
class UserSpec(Generic[T], ResolverMixer):
    users: Dict[int, T] = field(default_factory=dict)

    def get_or_create_data(self, user_id: int, factory: Callable[[], T] = None):
        if user_id not in self.users:
            if factory is None:
                factory = get_args(self.__orig_class__)[0]
            self.users[user_id] = factory()
        return self.users[user_id]
    
    def get_data(self, user_id: int, _default=None):
        if user_id not in self.users:
            return _default
        return self.users[user_id]

    def event_t(self) -> Type['UserSpecAsEvent[T]']:
        return UserSpecAsEvent[get_args(self.__orig_class__)]

    def as_event(self, event: Event, user: User) -> 'UserSpecAsEvent[T]':
        return UserSpecAsEvent[T](self, event, user)

    def resolver_mixin(self) -> Dict[type, Callable[..., Any]]:
        def resolve(event: Event, user: User):
            return self.as_event(event, user)
        def resolve_opt_data(gse: self.event_t()):
            return gse.get_data()
        def resolve_data(gse: self.event_t()):
            return gse.get_or_create_data()
        return {
            UserSpecAsEvent[get_args(self.__orig_class__)]: resolve,
            Optional[get_args(self.__orig_class__)[0]]: resolve_opt_data,
            get_args(self.__orig_class__)[0]: resolve_data
        }

    ...

@dataclass
class UserSpecAsEvent(Generic[T]):
    outter: UserSpec[T]
    event: Event
    user: User

    def get_or_create_data(self, factory: Callable[[], T] = None):
        return self.outter.get_or_create_data(self.user.id, factory)
    
    def get_data(self, _default=None):
        return self.outter.get_data(self.user.id, _default)

@dataclass
class GroupSpec(Generic[T], ResolverMixer):
    groups: Dict[int, T] = field(default_factory=dict)

    def get_or_create_data(self, group_id: int, factory: Callable[[], T] = None):
        if group_id not in self.groups:
            if factory is None:
                factory = get_args(self.__orig_class__)[0]
            self.groups[group_id] = factory()
        return self.groups[group_id]
    
    def get_data(self, group_id: int, _default=None):
        if group_id not in self.groups:
            return _default
        return self.groups[group_id]

    def event_t(self) -> Type['GroupSpecAsEvent[T]']:
        return GroupSpecAsEvent[get_args(self.__orig_class__)]

    def as_event(self, event: Event, group: Group) -> 'GroupSpecAsEvent[T]':
        return GroupSpecAsEvent[T](self, event, group)

    def resolver_mixin(self) -> Dict[type, Callable[..., Any]]:
        def resolve(event: Event, group: Group):
            return self.as_event(event, group)
        def resolve_opt_data(gse: self.event_t()):
            return gse.get_data()
        def resolve_data(gse: self.event_t()):
            return gse.get_or_create_data()
        return {
            GroupSpecAsEvent[get_args(self.__orig_class__)]: resolve,
            Optional[get_args(self.__orig_class__)[0]]: resolve_opt_data,
            get_args(self.__orig_class__)[0]: resolve_data
        }


@dataclass
class GroupSpecAsEvent(Generic[T]):
    outter: GroupSpec[T]
    event: Event
    group: Group

    def get_or_create_data(self, factory: Callable[[], T] = None):
        return self.outter.get_or_create_data(self.group.id, factory)
    
    def get_data(self, _default=None):
        return self.outter.get_data(self.group.id, _default)

class GroupLocalStorage(Generic[T], ResolverMixer):
    groups: Dict[int, Dict[int, T]]

    def __init__(self) -> None:
        self.groups = {}

    def get_or_create_data(self, group_id: int, member_qq: int, factory: Callable[[], T] = None):
        if group_id not in self.groups:
            self.groups[group_id] = {}
        group = self.groups[group_id]
        if member_qq not in group:
            if factory is None:
                factory = get_args(self.__orig_class__)[0]
            group[member_qq] = factory()
        return group[member_qq]
    
    def get_data(self, group_id: int, member_qq: int, _default=None):
        if group_id not in self.groups:
            return _default
        group = self.groups[group_id]
        if member_qq not in group:
            return _default
        return group[member_qq]

    def get_data_of_group(self, group_id: int) -> Dict[int, T]:
        if group_id not in self.groups:
            return {}
        return self.groups[group_id]

    def event_t(self) -> Type['GroupLocalStorageAsEvent[T]']:
        return GroupLocalStorageAsEvent[get_args(self.__orig_class__)]
    
    def at_t(self) -> Type['GroupLocalStorageAsAt[T]']:
        return GroupLocalStorageAsAt[get_args(self.__orig_class__)]

    def as_event(self, event: GroupMessage, member: GroupMember) -> 'GroupLocalStorageAsEvent[T]':
        return GroupLocalStorageAsEvent[T](self, event, member)
    
    def as_at(self, event: GroupMessage, at: At) -> 'GroupLocalStorageAsAt[T]':
        return GroupLocalStorageAsAt[T](self, event, at)
    
    def resolver_mixin(self) -> Dict[type, Callable[..., Any]]:
        def resolve(event: Event, member: GroupMember):
            return self.as_event(event, member)
        def resolve_opt_data(glse: self.event_t()):
            return glse.get_data()
        def resolve_data(glse: self.event_t()):
            return glse.get_or_create_data()
        def resolve_at(event: GroupMessage, at: At):
            return self.as_at(event, at)
        def resolve_at_data(glsa: self.at_t()):
            return glsa.get_or_create_data()
        return {
            GroupLocalStorageAsEvent[get_args(self.__orig_class__)]: resolve,
            GroupLocalStorageAsAt[get_args(self.__orig_class__)]: resolve_at,
            Optional[get_args(self.__orig_class__)[0]]: resolve_opt_data,
            get_args(self.__orig_class__)[0]: resolve_data,
            # AtData[get_args(self.__orig_class__)[0]]: resolve_at_data,
        }

# class _AtData(Generic[T]): ...
# AtData = Union[T, _AtData[T]]

class GroupLocalStorageAsAt(Generic[T]):
    outter: GroupLocalStorage[T]
    event: GroupMessage
    at: At

    def __init__(self, outter: GroupLocalStorage[T], event: GroupMessage, at: At):
        self.outter = outter
        self.event = event
        self.at = at

    def get_or_create_data(self, factory: Callable[[], T] = None):
        return self.outter.get_or_create_data(self.event.group.id, self.at.target, factory)
    
    def get_data(self, _default=None):
        return self.outter.get_data(self.event.group.id, self.at.target, _default)
    
    def get_data_of_group(self):
        return self.outter.get_data_of_group(self.event.group.id)

class GroupLocalStorageAsEvent(Generic[T]):
    outter: GroupLocalStorage[T]
    event: Event
    group_id: int
    member_id: int

    def __init__(self, outter: GroupLocalStorage[T], event: Event, member: GroupMember):
        self.outter = outter
        self.event = event
        self.group_id = member.group.id
        self.member_id = member.id

    def get_or_create_data(self, factory: Callable[[], T] = None):
        return self.outter.get_or_create_data(self.group_id, self.member_id, factory)
    
    def get_data(self, _default=None):
        return self.outter.get_data(self.group_id, self.member_id, _default)
        ...
    
    def get_data_of_group(self):
        return self.outter.get_data_of_group(self.group_id)

@dataclass
class AchvRarityVal():
    level: int
    aka: str = field(compare=False)

class AchvRarity(Enum):
    COMMOM = AchvRarityVal(0, '普通')
    UNCOMMON = AchvRarityVal(1, '罕见')
    RARE = AchvRarityVal(2, '稀有')
    EPIC = AchvRarityVal(3, '史诗')
    LEGEND = AchvRarityVal(4, '传说')
    

@dataclass
class AchvOpts():
    condition_hidden: bool = field(compare=False, default=False)
    hidden: bool = field(compare=False, default=False)
    rarity: AchvRarity = field(compare=False, default=AchvRarity.COMMOM)
    provisional: bool = field(compare=False, default=False)
    custom_obtain_msg: str = field(compare=False, default=None)
    target_obtained_cnt: int = field(compare=False, default=1)
    is_punish: bool = field(compare=False, default=False)
    prompt: Union[None, str] = field(compare=False, default=None)
    display: Union[None, str] = field(compare=False, default=None)
    display_weight: Optional[int] = field(compare=False, default=None)
    locked: bool = field(compare=False, default=False)
    dynamic_deletable: bool = field(compare=False, default=False)
    min_display_durtion: Optional[int] = field(compare=False, default=None)
    display_pinned: bool = field(compare=False, default=False)
    unit: str = field(compare=False, default='个')
    dynamic_obtained: bool = field(compare=False, default=False)

    @property
    def formatted_target_obtained_cnt(self):
        if self.target_obtained_cnt > 0:
            return str(self.target_obtained_cnt)
        return '∞'

    def is_deletable(self, ts: Optional[float]):
        if self.locked:
            return False
        
        if ts is None:
            return False
        
        if self.is_punish:
            span = datetime.now().replace(tzinfo=None) - datetime.fromtimestamp(ts).replace(tzinfo=None)
            if span.days < 3:
                return False
        
        return True

@dataclass
class AchvInfo():
    id: int
    aka: str = field(compare=False)
    condition: str = field(compare=False)
    opts: AchvOpts = field(compare=False, default_factory=AchvOpts)

    __reduce_ex__ = int.__reduce_ex__ # TODO: 高版本python可能需要删除这个，Pickle库的问题

    def __new__(cls, *args, **kwarg): # Enum内部实现会判断这个是否存在别问我为什么
        return object.__new__(cls)

    def __str__(self):
        return f'{self.aka}[{self.opts.rarity.value.aka}]'
    
    def get_display_text(self):
        if self.opts.display is not None:
            return self.opts.display
        return self.aka

class AchvEnum(AchvInfo, Enum):
    def __hash__(self) -> int:
        return hash(self.name)


@dataclass
class RewardCategoryOpts():
    is_exclusive: bool = field(compare=False, default=False) # 该类别下的物品是否获取了其中一个之后就无法获得其他的
    ...

@dataclass
class RewardCategoryInfo():
    id: int
    aka: str = field(compare=False)
    opts: RewardCategoryOpts = field(compare=False, default_factory=RewardCategoryOpts)

    __reduce_ex__ = int.__reduce_ex__ # TODO: 高版本python可能需要删除这个，Pickle库的问题

    def __new__(cls, *args, **kwarg): # Enum内部实现会判断这个是否存在别问我为什么
        return object.__new__(cls)

    def __str__(self):
        return f'{self.aka}'

class RewardCategoryEnum(RewardCategoryInfo, Enum):
    def __hash__(self) -> int:
        return hash(self.name)
    
class BaseRewardCategories(RewardCategoryEnum):
    VIRTUAL = 0, '虚拟奖励'

@dataclass
class RewardOpts():
    category: RewardCategoryEnum = field(compare=False, default=BaseRewardCategories.VIRTUAL)
    max_claims: Optional[int] = field(compare=False, default=None) # None表示无限制
    ticket_cost: int = field(compare=False, default=1)

@dataclass
class RewardInfo():
    id: int
    aka: str = field(compare=False)
    opts: RewardOpts = field(compare=False, default_factory=RewardOpts)
    
    __reduce_ex__ = int.__reduce_ex__ # TODO: 高版本python可能需要删除这个，Pickle库的问题

    def __new__(cls, *args, **kwarg): # Enum内部实现会判断这个是否存在别问我为什么
        return object.__new__(cls)

    def __str__(self):
        return f'{self.aka}'
    
class RewardEnum(RewardInfo, Enum):
     def __hash__(self) -> int:
        return hash(self.name)

@dataclass
class Overrides():
    context: 'Context'
    vals: Iterable
    outer: 'Plugin'
    to: Optional[Target] = field(default=None)
    redirected: 'Redirected' = field(init=False)

    async def __aenter__(self):
        self.context.push_overrides(self)

        ctx = self.outer.engine.get_context()
        self.redirected = None

        try:
            self.redirected = Redirected(*await ctx.resolve_args(Redirected, [], self.outer))
            self.redirected.context = self.context
            self.redirected.to = self.to
            self.redirected.context = self.context

            # 把这个redirected放到栈顶
            return self.redirected
        except: 
            from plugin import OutOfContext
            if not isinstance(self.context, OutOfContext):
                ...
                # traceback.print_exc()
            ...
    

    async def __aexit__(self, type, value: Exception, trace):
        self.context.remove_overrides(self)

        # 如果发生异常了，就需要设置redirected
        if type is not None and self.redirected is not None:
            self.redirected([f' 错误: ', *value.args])
            # self.context.set_redirected(self.redirected)
            ...

@dataclass
class GroupMemberOp():
    bot: Mirai
    member: GroupMember

    async def mute(self, time_s: int):
        return await self.bot.mute(self.member.group.id, self.member.id, time_s)
    
    async def nudge(self):
        return await self.bot.send_nudge(self.member.id, self.member.group.id, 'Group')
    
    async def send(self, chain: MessageChain):
        return await self.bot.send_group_message(self.member.group.id, chain)

    async def send_temp(self, chain: MessageChain):
        await self.bot.send_temp_message(self.member.id, self.member.group.id, chain)

    def get_avatar(self):
        return self.member.get_avatar_url()

    @property
    def who(self): return self.member

@dataclass
class GroupOp():
    bot: Mirai
    group: Group

    async def send(self, msg):
        return await self.bot.send_group_message(self.group.id, msg)
    
    async def get_member(self, member_id: int):
        return await self.bot.get_group_member(self.group.id, member_id)
    
@dataclass
class SourceOp():
    bot: Mirai
    event: Event
    group: Optional[Group]
    member: Optional[GroupMember]

    def get_target(self):
        if isinstance(self.event, TempMessage):
            return Target.TEMP
        elif isinstance(self.event, NudgeEvent):
            if self.event.subject.kind == 'Group':
                return Target.GROUP
            else:
                return Target.TEMP
        else:
            return Target.GROUP

    def get_target_id(self):
        target = self.get_target()

        if target == Target.GROUP:
            return self.get_group_id()
        
        if target == Target.TEMP:
            return self.get_member_id()
        
    def get_member_id(self):
        return self.member.id
    
    def get_group_id(self):
        if self.member is not None:
            return self.member.group.id
        return self.group.id

    async def send(self, msg, *, to: Target=None):
        if to is None:
            to = self.get_target()

        if to == Target.GROUP:
            return await self.bot.send_group_message(self.get_group_id(), msg)
        
        if to == Target.TEMP:
            return await self.bot.send_temp_message(self.get_member_id(), self.get_group_id(), msg)
    

@dataclass
class Redirected():
    # member: Optional[GroupMember]
    source_op: SourceOp
    context: 'Context' = field(init=False)
    to: Optional[Target] = field(init=False)
    mc: MessageChain = field(init=False)
    attrs: list = field(init=False)

    def __post_init__(self):
        self.mc = None
        self.attrs = None

    def __call__(self, mc: Union[MessageChain, 'Redirected'], *, attrs = None) -> Any:
        if isinstance(mc, Redirected):
            self.mc = mc.mc
        else:
            self.mc = mc
        self.attrs = attrs
        self.context.set_redirected(self)
        return self

def get_delta_time_str(time_delta: float, *, use_seconds=True):
    time_delta = int(time_delta)
    days, remainder = divmod(time_delta, 3600 * 24)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    formatted = ''
    if days > 0:
        formatted += f'{days}天'
    if hours > 0:
        formatted += f'{hours}小时'
    if minutes > 0:
        formatted += f'{minutes}分钟'

    if not use_seconds and minutes == 0 and hours == 0 and days == 0:
        formatted += f'1分钟'
    if seconds > 0 and use_seconds:
        formatted += f'{seconds}秒'
    
    return formatted

async def breakdown_chain(self, chain, regex, cb, ctx=None):
        if ctx is None:
            ctx = {}
        new_chain = []
        if type(chain) is str:
            chain = [chain]
        for comp in chain:
            txt = None
            if isinstance(comp, str):
                txt = comp
            if isinstance(comp, Plain):
                txt = comp.text
            if txt is None:
                new_chain.append(comp)
                continue
            of_sp = re.split(regex, txt)
            for idx, s in enumerate(of_sp):
                if idx % 2 != 0:
                    s = await cb(s, ctx)
                    # print(f'{s=}')
                if s is not None and s != '':
                    if type(s) is list:
                        new_chain.extend(s)
                    else:
                        new_chain.append(s)
        return new_chain

def breakdown_chain_sync(chain, regex, cb, ctx=None):
        if ctx is None:
            ctx = {}
        new_chain = []
        if type(chain) is str:
            chain = [chain]
        for comp in chain:
            txt = None
            if isinstance(comp, str):
                txt = comp
            if isinstance(comp, Plain):
                txt = comp.text
            if txt is None:
                new_chain.append(comp)
                continue
            of_sp = re.split(regex, txt)
            for idx, s in enumerate(of_sp):
                if idx % 2 != 0:
                    s = cb(s, ctx)
                    # print(f'{s=}')
                if s is not None and s != '':
                    if type(s) is list:
                        new_chain.extend(s)
                    else:
                        new_chain.append(s)
        return new_chain

@dataclass
class ThrottleMan():
    last_invoke_ts: float = 0
    effective_speech_cnt: int = 0

    def inc_effective_speech_cnt(self):
        self.effective_speech_cnt += 1

    def get_effective_speech_cnt(self):
        return self.effective_speech_cnt

    def get_cooldown_remains(self, cooldown_duration: float):
        return max(0, self.last_invoke_ts + cooldown_duration - time.time())
    
    def mark_invoked(self):
        self.last_invoke_ts = time.time()
        self.effective_speech_cnt = 0

def handler(func):
    func._event_handler_ = True
    return func

def bind(instance, func, as_name=None):
    """
    Bind the function *func* to *instance*, with either provided name *as_name*
    or the existing name of *func*. The provided *func* should accept the 
    instance as the first argument, i.e. "self".
    """
    if as_name is None:
        as_name = func.__name__
    bound_method = func.__get__(instance, instance.__class__)
    setattr(instance, as_name, bound_method)
    return bound_method

class CustomFormatter(logging.Formatter):
    grey = "\x1b[37m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    green = "\x1b[32;20m"
    skyblue = "\x1b[36;20m"
    purple = "\x1b[35;20m"
    reset = "\x1b[0m"
    format = f"%(asctime)s - %(levelname)s\t[%(name)s]: %(message)s"

    FORMATS = {
        logging.DEBUG: f"{grey}%(asctime)s - {reset}%(levelname)s\t{grey}[{reset}{skyblue}%(name)s{reset}{grey}]: {reset}%(message)s",
        logging.INFO: f"{grey}%(asctime)s - {reset}{green}%(levelname)s{reset}\t{grey}[{reset}{skyblue}%(name)s{reset}{grey}]: {reset}%(message)s",
        logging.WARNING: f"{grey}%(asctime)s - {reset}{yellow}%(levelname)s{reset}\t{grey}[{reset}{skyblue}%(name)s{reset}{grey}]: {reset}%(message)s",
        logging.ERROR: f"{grey}%(asctime)s - {reset}{red}%(levelname)s{reset}\t{grey}[{reset}{skyblue}%(name)s{reset}{grey}]: {reset}%(message)s",
        logging.CRITICAL: f"{grey}%(asctime)s - {reset}{bold_red}%(levelname)s{reset}\t{grey}[{reset}{skyblue}%(name)s{reset}{grey}]: {reset}%(message)s"
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt, "%Y-%m-%d %H:%M:%S")
        return formatter.format(record)

def get_logger():
    frm = inspect.stack()[1]
    mod = inspect.getmodule(frm[0])
    logger = logging.getLogger(mod.__name__.split('.')[-1])
    logger.setLevel(logging.DEBUG)

    ch = logging.StreamHandler()
    # ch.setLevel(logging.DEBUG)

    ch.setFormatter(CustomFormatter())

    logger.addHandler(ch)
    return logger