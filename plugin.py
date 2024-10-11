from abc import abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
import importlib.util
import inspect
import sys
from types import MethodType, ModuleType
from typing import Any, Awaitable, Callable, Final, Dict, ForwardRef, Generic, List, Literal, Optional, Set, Tuple, Type, TypeVar, Union, get_args, get_origin
import pickle
import glob
import re
from typing import Union
from mirai import Event, FriendMessage, GroupMessage, MessageChain, MessageEvent, Mirai, Plain, At, StrangerMessage, TempMessage
from mirai.models.events import NudgeEvent, MemberJoinRequestEvent, GroupRecallEvent, MemberJoinEvent, MemberUnmuteEvent, MemberCardChangeEvent
from mirai.models.message import MessageComponent, Quote
from mirai.models.entities import GroupMember, Group
import os
import asyncio
import aiofile
import inflection
from functools import wraps
import contextvars
import traceback
from collections.abc import Iterable
from mirai.models.api import RespOperate

from utilities import AchvEnum, GroupMemberOp, GroupOp, Msg, MsgOp, Overrides, Redirected, ResolverMixer, SourceOp, Target, User, bind, ensure_attr, get_logger, to_unbind

logger = get_logger()

PLUGIN_PATH: Final[str] = './plugins/*.py'
BACKUP_PATH: Final[str] = './backups'

class CommandNotFoundError(Exception):
    ...

class ExecFailedError(Exception):
    ...


class InstrAttr(Enum):
    NO_ALERT_CALLER = auto()
    FORECE_BACKUP = auto()
    BACKGROUND = auto()
    INTERCEPT_EXCEPTIONS = auto()

@dataclass
class PluginPath():
    data: 'DataPath'

    def __getattribute__(self, name):
        obj = object.__getattribute__(self, name)
        if isinstance(obj, DataPath):
            obj.ensure()
        return obj

class DataPath():
    path_str: str
    cache: 'DataPath'

    def __init__(self, path_str: str):
        self.path_str = path_str

    def __fspath__(self):
        return self.path_str
    
    def __getattr__(self, name):
        p = DataPath(os.path.join(self, name))
        p.ensure()
        return p
    
    def __getitem__(self, name):
        if isinstance(name, Enum):
            p = DataPath(os.path.join(self, name.name))
            p.ensure()
        else:
            p = DataPath(os.path.join(self, str(name)))
        return p
    
    def __str__(self) -> str:
        return self.path_str
    
    def ensure(self):
        if not os.path.exists(self.path_str):
            os.makedirs(self.path_str)

    def of_file(self, file_name: str):
        return os.path.join(self, file_name)

class MetaPlugin(type):
    @property
    def path(cls):
        return cls._get_path()
    
    def _get_path(cls, stack_depth = 2):
        frm = inspect.stack()[stack_depth]
        mod = inspect.getmodule(frm[0])
        data_path = DataPath(os.path.join(os.path.dirname(os.path.abspath(mod.__file__)), mod.__name__.split('.')[-1]))
        return PluginPath(data_path)


T = TypeVar('T')

# def state(*, default: T) -> T:
#     return State(default=default)

class Empty(): ...

empty: Final = Empty()

@dataclass
class State():
    default: Any = None
    ...

# 被注解的类变量是状态
class BackupMan():
    t: asyncio.Task
    target: 'Plugin'
    # dirty: bool

    def __init__(self, target: 'Plugin'):
        self.t = None
        self.target = target
        # self.dirty = False

    def __enter__(self):
        ...

    def __exit__(self, type, value, trace):
        self.target.engine.clear_dirty_plugins()
        ...

    def trigger_backup(self):
        if self.t is not None and not self.t.done():
            return
        async def fn():
            file_path = self.get_filepath(self.target.__class__)
            try:
                by = pickle.dumps(self.target)
                async with aiofile.async_open(file_path, 'wb') as f:
                    await f.write(by)
                logger.debug(f'{self.target.__class__.__name__} state backuped')
            except Exception as e:
                logger.error(f'pickle failed {e=}')
                print(self.target.__getstate__)
                print(self.target.__getstate__())
        self.t = asyncio.create_task(fn())

    def set_dirty(self):
        # self.dirty = True
        self.target.engine.append_dirty_plugin(self.target)

    @classmethod
    def get_filepath(cls, target_cls: Type['Plugin']):
        return os.path.join(BACKUP_PATH, f'{target_cls.__module__.split(".")[-1]}.pkl')

    @classmethod
    def has_backup(cls, target_cls: Type['Plugin']):
        return os.path.exists(cls.get_filepath(target_cls))

    @classmethod
    def load_plugin(cls, target_cls: Type['Plugin']) -> 'Plugin':
        if cls.has_backup(target_cls):
            logger.debug(f'resume {target_cls.__name__} from backup')
            with open(cls.get_filepath(target_cls), 'rb') as f:
                obj = pickle.load(f)
                obj.__init__()
                return obj
        else:
            obj = target_cls()
            for anno in obj.__annotations__.keys():
                if anno in target_cls.__dict__:
                    #TODO 这里可能有BUG，需要factory
                    attr = target_cls.__dict__[anno]
                    if isinstance(attr, State):
                        attr = attr.create()
                    setattr(obj, anno, attr)
            obj.init_state()
            return obj

def delegate(*attr):
    def deco(fn: Callable):
        @wraps(fn)
        async def wrapper(self: 'Plugin', *args, **kwargs):
            async def ctx_wrapper(ctx: 'Context'):
                if not hasattr(fn, '__self__'):
                    bound_method = MethodType(fn, self)
                else:
                    bound_method = fn
                resolved = await ctx.resolve_args(bound_method, list(args))

                # TODO NEW task dirty out of context!!
                async def task():
                    try:
                        return await bound_method(*resolved, **kwargs)
                    finally:
                        if InstrAttr.FORECE_BACKUP in attr:
                            self.backup_man.set_dirty()
                
                if InstrAttr.BACKGROUND in attr:
                    logger.debug('task created')
                    copied = ctx.copy_overrides_stack()
                    async def wrap_with():
                        ctx.set_overrides_stack(copied)
                        with ctx:
                            await task()
                    return asyncio.create_task(wrap_with())
                return await task()
            
            ctx = self.engine.get_context()
            if ctx is None:
                with self.engine.of() as c, c:
                    return await ctx_wrapper(c)
            else:
                return await ctx_wrapper(ctx)

        to_unbind(fn)._delegated_ = True
        return wrapper
    return deco


class Plugin(object, metaclass=MetaPlugin):
    bot: Mirai
    path: PluginPath
    backup_man: 'BackupMan'
    engine: 'Engine'
    disabled: bool

    def __getattr__(self, name):
        if name == 'path':
            p = self.__class__._get_path()
            self.path = p
            return p
        raise AttributeError

    def disable(self):
        self.disabled = True

    def enable(self):
        self.disabled = False

    def override(self, *args, to: Optional[Target] = None):
        return Overrides(
            context=self.engine.get_context(),
            vals=args,
            to=to,
            outer=self
        )
    
    @delegate()
    async def member_from(self, group: Group, *, at: Optional[At]=None, member_id: Optional[int]=None):
        if at is not None:
            return await self.bot.get_group_member(group.id, at.target)
        if member_id is not None:
            return await self.bot.get_group_member(group.id, member_id)

    def init(self, bot: Mirai, engine: 'Engine'):
        self.bot = bot
        self.engine = engine
        self.backup_man = BackupMan(self)
        self.disabled = False

        for _, method in inspect.getmembers(self, predicate=inspect.ismethod):
            
            if hasattr(method, '_bot_autorun_'):
                def get_wrapper(m):
                    return delegate()(m)(self)

                bot.add_background_task(get_wrapper(method))

    
    def __setattr__(self, name, value):
        if name in self.__annotations__: 
            config = ensure_attr(self.__class__, PluginConfig)
            if config.backup_enabled and hasattr(self, 'backup_man'):
                # print(f'{self=}, {name=}, {value=}')
                # self.backup_man.trigger_backup()
                # self.backup_man.set_dirty()
                # TODO: 写时dirty机制
                ...
            
        self.__dict__[name] = value

    def get_config(self):
        config = ensure_attr(self.__class__, PluginConfig)
        return config

    def __getstate__(self):
        annos = self.__annotations__
        states = {k: getattr(self, k) for k in annos if try_get_injector(annos[k]) is None and get_origin(annos[k]) is not Final and annos[k] is not Final}
        states.update({k: getattr(self, k) for k, v in self.__class__.__dict__.items() if isinstance(v, State) and k not in states})
        # print('get state', self.__class__.__name__, v)
        return states

    def get_resolvers(self) -> Dict[type, Callable[[Any], Any]]: return {}

    def init_state(self): ...

def flatten(S):
    if S == []:
        return S
    if isinstance(S[0], list):
        return flatten(S[0]) + flatten(S[1:])
    return S[:1] + flatten(S[1:])

class PlaceholderEvent(Event):
    ...

class Engine():
    plugins: Dict[str, Plugin]
    dirty_plugins: Set[Plugin]
    _context: contextvars.ContextVar
    bot: Mirai

    def __init__(self, bot: Mirai) -> None:
        self.plugins = {}
        self.dirty_plugins = set()
        self._context = contextvars.ContextVar[Context]('Context')
        self.bot = bot

    def load(self):
        mods: List[ModuleType] = []
        for file in glob.glob(PLUGIN_PATH):
            mod_name = file.replace('\\', '/').replace('./', '.').replace('/', '.')[:-3]
            mod_name = mod_name[1:]
            spec = importlib.util.spec_from_file_location(mod_name, file)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = mod
            spec.loader.exec_module(mod)
            mods.append(mod)
        
        for mod in mods:
            for _, member in inspect.getmembers(mod, lambda m: inspect.isclass(m) and m.__module__ == mod.__name__):
                if issubclass(member, Plugin):
                    globals()[member.__name__] = member

        for mod in mods:
            for _, member in inspect.getmembers(mod, lambda m: inspect.isclass(m) and m.__module__ == mod.__name__):
                if issubclass(member, Plugin):
                    self._load_plugin_cls(member)

        for plugin in self.plugins.values():
            if isinstance(plugin, AllLoadedNotifier):
                plugin.all_loaded()

    def append_dirty_plugin(self, p: Plugin):
        self.dirty_plugins.add(p)
        ...

    def clear_dirty_plugins(self):
        for p in self.dirty_plugins:
            p.backup_man.trigger_backup()
        self.dirty_plugins.clear()
        ...

    def _load_plugin_cls(self, member: Type['Plugin']):
        may_already_exist = next((x for x in list(self.plugins.values()) if x.__class__ is member), None)
        if may_already_exist is not None:
            return may_already_exist
        logger.info(f'loading {member.__name__}...')
        p = BackupMan.load_plugin(member)
        p.init(self.bot, self)
        config = ensure_attr(member, PluginConfig)
        self.plugins[config.name] = p

        for name, anno in member.__annotations__.items():
            injected = self.try_load_injector(anno)
            if injected is None: continue
            logger.debug(f'inject {injected.__class__.__name__} -> {member.__name__}')
            setattr(p, name, injected)
            if isinstance(injected, InjectNotifier):
                injected.injected(p)
        return p

    def try_load_injector(self, anno):
        target_plugin_cls = try_get_injector(anno)
        if target_plugin_cls is None: return None
        if isinstance(target_plugin_cls, ForwardRef):
            target_plugin_cls = target_plugin_cls._evaluate(globals(), locals(), frozenset())
        return self._load_plugin_cls(target_plugin_cls)

    def get_context(self) -> 'Context':
        return self._context.get(None)
    
    def of(self, event: Optional[Event]=None):
        outer = self
        if event is None:
            event = PlaceholderEvent(type='PlaceholderEvent')
        class CW():
            def __enter__(self):
                nonlocal event
                if isinstance(event, PlaceholderEvent):
                    context_factory = OutOfContext
                elif isinstance(event, MessageEvent):
                    context_factory = MessageContext
                elif isinstance(event, NudgeEvent):
                    context_factory = NudgeContext
                elif isinstance(event, MemberJoinRequestEvent):
                    context_factory = JoinReqContext
                elif isinstance(event, GroupRecallEvent):
                    context_factory = RecallContext
                elif isinstance(event, MemberJoinEvent):
                    context_factory = JoinedContext
                elif isinstance(event, MemberUnmuteEvent):
                    context_factory = UnmuteContext
                elif isinstance(event, MemberCardChangeEvent):
                    context_factory = MemberCardChangeContext
                else:
                    raise RuntimeError('not impl')
                ctx = context_factory(outer, event)
                token = outer._context.set(ctx)
                ctx.token = token
                return ctx

            def __exit__(self, type, value, trace):
                ctx: Context = outer._context.get()
                outer._context.reset(ctx.token)
        return CW()
    
class ResolveFailedException(Exception):
    ...

class Context(ResolverMixer):
    token: contextvars.Token['Context']

    def __init__(self, engine: Engine, event: Event) -> None:
        self.engine = engine
        self.stack = []
        self.token = None
        self.event = event
        self.overrides_stack_save = contextvars.ContextVar[list[Overrides]]('overrides_stack_save')
        self.redirected: 'Redirected' = None
        self.debug = False

    def __enter__(self):
        ...

    def __exit__(self, type, value, trace):
        self.engine.clear_dirty_plugins()
        if type is not None and isinstance(self, OutOfContext):
            logger.warning('exception catched by context')
            traceback.print_exc()
            return True
        ...

    # @abstractmethod
    def get_instr_attr_name(self):
        ...

    async def instrs(self, instr_attr_name, cb: Callable[[MethodType], Awaitable], *, raise_error = False, plugins: list[Plugin] = None):
        if plugins is None:
            plugins = self.engine.plugins.values()
        with self:
            for plugin in plugins:
                if plugin.disabled: continue
                
                for _, method in inspect.getmembers(plugin, predicate=inspect.ismethod):
                    if hasattr(method, instr_attr_name):
                        # print(f'found {method=}')
                        if InstrAttr.FORECE_BACKUP in method._instr_attrs_:
                            plugin.backup_man.set_dirty()
                        res = None
                        try:
                            async with plugin.override() as redirected:
                                self.set_redirected(None)
                                try:
                                    res = await cb(method) # 需要抛一个异常让with吃到
                                except Exception as e:
                                    if not isinstance(e, ExecFailedError) and InstrAttr.INTERCEPT_EXCEPTIONS not in method._instr_attrs_:
                                        raise
                                    else:
                                        if self.debug:
                                            traceback.print_exc()
                        except: ...
                        if res is not None:
                            if self.redirected is None:
                                redirected(res, attrs=method._instr_attrs_)
                        if self.redirected is not None:
                            await self.send()


    async def exec(self):
        async def cb(method: MethodType):
            return await method(*(await self.resolve_args(method, [])))
        await self.instrs(self.get_instr_attr_name(), cb)

    async def send(self):
        res = []

        if self.redirected.mc is None:
            return

        attrs = self.redirected.attrs
        if attrs is None:
            attrs = []
        
        def append_at(target_id: int):
            res.append(At(target=target_id))
            res.append('\n')

        if InstrAttr.NO_ALERT_CALLER not in [e for e in attrs]:
            if self.redirected.to is None:
                if self.redirected.source_op.get_target() == Target.GROUP:
                    append_at(self.redirected.source_op.get_member_id())
            else:
                if self.redirected.to == Target.GROUP:
                    append_at(self.redirected.source_op.get_member_id())

        res.extend(self.redirected.mc)
        await self.redirected.source_op.send(res, to=self.redirected.to)

    def get_overrides_stack(self):
        s = self.overrides_stack_save.get(None)
        if s is None:
            s = []
            self.overrides_stack_save.set(s)
        return s

    def copy_overrides_stack(self):
        return self.get_overrides_stack().copy()

    def set_overrides_stack(self, s):
        self.overrides_stack_save.set(s)

    def push_overrides(self, o: Overrides):
        self.get_overrides_stack().append(o)
    
    def remove_overrides(self, o: Overrides):
        self.get_overrides_stack().remove(o)

    def set_redirected(self, redirected: 'Redirected'):
        self.redirected = redirected
        # print(f'{self.redirected=}')

    async def get_override(self, t, _def_factory: Callable[[], Awaitable]=None):
        res = self.get_override_sync(t)
        if res is not empty:
            return res
        if _def_factory is not None:
            return await _def_factory()

    def get_override_sync(self, t):
        for overrides in reversed(self.get_overrides_stack()):
            for val in overrides.vals:
                if isinstance(val, t):
                    return val
        return empty
        ...

    def resolver_mixin(self) -> Dict[type, Callable[..., Any]]:
        async def resolve_user(event: Event):
            if isinstance(event, (GroupMessage, FriendMessage, StrangerMessage, TempMessage)):
                return User(event.sender.id)
            elif isinstance(event, NudgeEvent):
                return User(event.from_id)
            elif isinstance(event, GroupRecallEvent):
                return User(event.author_id)
            elif isinstance(self.event, MemberJoinRequestEvent):
                return User(self.event.from_id)
            elif isinstance(event, (MemberJoinEvent, MemberUnmuteEvent, MemberCardChangeEvent)):
                return User(event.member.id)
            else:
                raise ExecFailedError(f'消息类型不匹配 USER, {event=}')

        async def resolve_msg(event: Event):
            async def msg_from_event():
                # print('[msg_from_event]')
                if isinstance(event, MessageEvent):
                    return Msg(event.message_chain.message_id)
                
            override = await self.get_override(Msg, msg_from_event)
            if override is None:
                raise ExecFailedError(f'消息类型不匹配 MSG, {event=}')
            # print(f'{override=}')
            return override
        
        async def resolve_quote(event: MessageEvent):
            for c in event.message_chain:
                if isinstance(c, Quote):
                    return c
            else:
                raise ExecFailedError(f'消息类型不匹配 Quote, {event=}')
        
        async def resolve_msg_op(msg: Msg, group: Group):
            return MsgOp(
                bot=self.engine.bot,
                msg=msg,
                group=group
            )

        async def resolve_group(event: Event):
            async def group_from_event():
                if isinstance(event, GroupMessage):
                    return event.sender.group
                elif isinstance(event, TempMessage):
                    return event.group
                elif isinstance(event, NudgeEvent) and event.subject.kind == 'Group':
                    return await self.engine.bot.get_group(event.subject.id)
                elif isinstance(event, MemberJoinRequestEvent):
                    return await self.engine.bot.get_group(event.group_id)
                elif isinstance(event, GroupRecallEvent):
                    return event.group
                elif isinstance(event, MemberJoinEvent):
                    return event.member.group
                elif isinstance(event, MemberUnmuteEvent):
                    return event.member.group
                elif isinstance(event, MemberCardChangeEvent):
                    return event.member.group
                
            member_override: GroupMember = await self.get_override(GroupMember)
            if member_override is not None:
                return member_override.group

            override = await self.get_override(Group, group_from_event)
            if override is None:
                raise ExecFailedError(f'消息类型不匹配 GROUP, {event=}')
            return override
        async def resolve_group_member(event: Event):
            async def group_member_from_event():
                if isinstance(event, GroupMessage):
                    return event.sender
                elif isinstance(event, TempMessage):
                    return event.sender
                elif isinstance(event, NudgeEvent) and event.subject.kind == 'Group':
                    return await self.engine.bot.get_group_member(event.subject.id, event.from_id)
                elif isinstance(event, GroupRecallEvent):
                    return await self.engine.bot.get_group_member(event.group.id, event.author_id)
                elif isinstance(event, MemberJoinEvent):
                    return event.member
                elif isinstance(event, MemberUnmuteEvent):
                    return event.member
                elif isinstance(event, MemberCardChangeEvent):
                    return event.member
            override = await self.get_override(GroupMember, group_member_from_event)
            if override is None:
                raise ExecFailedError(f'消息类型不匹配 GROUP MEMBER, {event=}')
            return override
        def resolve_group_op(group: Group):
            return GroupOp(bot=self.engine.bot, group=group)
        def resolve_group_member_op(member: GroupMember):
            return GroupMemberOp(bot=self.engine.bot, member=member)
        def resolve_source_op(event: Event, group: Optional[Group], member: Optional[GroupMember]):
            return SourceOp(bot=self.engine.bot, event=event, group=group, member=member)
        return {
            Msg: resolve_msg,
            MsgOp: resolve_msg_op,
            User: resolve_user,
            Group: resolve_group,
            GroupMember: resolve_group_member,
            GroupOp: resolve_group_op,
            GroupMemberOp: resolve_group_member_op,
            SourceOp: resolve_source_op,
            Quote: resolve_quote,
        }
    
    @staticmethod
    def is_type_of(var, cls):
        if type(cls) is str:
            return inspect.isclass(var) and '.'.join([var.__module__, var.__qualname__]) == cls
        return inspect.isclass(var) and issubclass(var, cls)
    
    def pretty_stack(self):
        return ''.join([f'[{i}]' for i in self.stack])

    @staticmethod
    def is_optional(t):
        origin = get_origin(t)
        args = get_args(t)
        return origin is Union and len(args) == 2 and args[1] is type(None)

    @classmethod
    def get_allowed_events(cls, param: inspect.Parameter) -> Tuple:
        if get_origin(param.annotation) is Union:
            union_args = get_args(param.annotation)
            all_msg_type = all([cls.is_type_of(a, Event) for a in union_args])
            all_not_msg_type = all([not cls.is_type_of(a, Event) for a in union_args])
            assert(all_msg_type or all_not_msg_type)
            if all_msg_type:
                return union_args
        elif cls.is_type_of(param.annotation, Event):
            return (param.annotation,)

    @classmethod
    def is_target_msg(cls, params: List[inspect.Parameter], event: Event):
        for p in params:
            allowed_events = cls.get_allowed_events(p)
            if allowed_events is None: continue
            return any([isinstance(event, e) for e in allowed_events])
        return True

    @staticmethod
    def get_text(comp):
        if isinstance(comp, str):
            return comp
        assert(isinstance(comp, Plain))
        return comp.text


    async def resolve_args(self, method: MethodType, chain: List[Union[MessageComponent, Any]], plugin: Plugin = None, *, match: re.Match[str] = None):
        s = inspect.signature(method)
        if plugin is None:
            plugin = method.__self__
        params = [p for p in s.parameters.values() if p.kind not in (p.KEYWORD_ONLY, p.VAR_KEYWORD)]
        
        if isinstance(self.event, MessageEvent) and not self.is_target_msg(params, self.event):
            raise ExecFailedError(f'无法在当前上下文中调用')
        args = []
        resolvers = plugin.get_resolvers()
        resolvers.update(self.resolver_mixin())
        for ff in plugin.__dict__.values():
            if not isinstance(ff, ResolverMixer): continue
            resolvers.update(ff.resolver_mixin())
        for p in params:
            #下面这些是不消耗实参，直接从上下文中获得的形参
            if self.is_type_of(p.annotation, Event) and isinstance(self.event, p.annotation):
                args.append(self.event)
                continue
            if self.is_type_of(p.annotation, Context):
                args.append(self)
                continue
            injected = self.engine.try_load_injector(p.annotation)
            if injected is not None:
                if isinstance(injected, InjectNotifier):
                    injected.injected(plugin)
                args.append(injected)
                continue
            async def append_from_resolver(anno):
                # print(f'append_from_resolver prep {anno=}, {resolvers=}')
                if anno in resolvers:
                    resolvers_of_type = resolvers[anno]

                    if not isinstance(resolvers_of_type, Iterable):
                        resolvers_of_type = [resolvers_of_type]
                    
                    for resolver in resolvers_of_type:
                        # print(f'append_from_resolver try {anno=}, {resolver=}')
                        sub_args = await self.resolve_args(resolver, chain, plugin)
                        # print(f'{sub_args=}')
                        try:
                            if inspect.iscoroutinefunction(resolver):
                                sub_res = await resolver(*sub_args)
                            else:
                                sub_res = resolver(*sub_args)
                            args.append(sub_res)
                            # print(f'append_from_resolver result {anno=}, {sub_res=}')
                        except ExecFailedError as e:
                            # traceback.print_exc()
                            raise
                        return True
                return False

            async def append_single_arg():
                anno = p.annotation
                will_skip = False
                front = None
                curr_arg = None
                try:
                    if await append_from_resolver(anno): return
                except ExecFailedError as e:
                    ...
                if self.is_optional(anno):
                    will_skip = True
                    anno = get_args(anno)[0]
                if  p.default is not inspect._empty:
                    will_skip = True
                try:
                    if await append_from_resolver(anno): return
                    patharg_params = try_get_patharg_params(anno, p.name)
                    if patharg_params is not None and match is not None:
                        xtype, pos = patharg_params
                        curr_arg = match[pos]
                        anno = xtype
                    else:
                        if len(chain) > 0:
                            front = chain.pop(0)
                            curr_arg = front
                        else:
                            raise ExecFailedError(f'参数不足, {anno=}')
                    if curr_arg is None:
                        raise ExecFailedError(f'无法识别的参数类型')
                    if type(curr_arg) is anno:
                        args.append(curr_arg)
                        return
                    if anno in (str, int, float):
                        if type(curr_arg) is not str or isinstance(curr_arg, Plain):
                            raise ExecFailedError(f'参数类型错误')
                        args.append(anno(curr_arg.text if isinstance(curr_arg, Plain) else curr_arg))
                        return
                    if issubclass(anno, Enum) and isinstance(curr_arg, anno) and type(curr_arg) is not anno:
                        args.append(curr_arg)
                        return
                    if issubclass(anno, Enum):
                        values = [e.value for e in anno]
                        if curr_arg not in values:
                            raise ExecFailedError(f'枚举值无效, 可选: {", ".join(values)}')
                        args.append(anno(curr_arg))
                        return
                    if anno is At and isinstance(curr_arg, (Plain, str)):
                        try:
                            m_id = int(self.get_text(curr_arg))
                        except:
                            raise ExecFailedError(f'AT的目标id格式错误')
                        args.append(At(target=m_id))
                        return
                    if anno is MessageComponent:
                        args.append(curr_arg)
                        return
            
                    raise ExecFailedError(f'参数类型错误, 未匹配, {anno=}, {type(curr_arg)=}')
                # except ExecFailedError as e:
                #     raise
                except Exception as e:
                    if not will_skip: raise
                    if front is not None:
                        chain.insert(0, front)
                    default = p.default
                    if default is inspect._empty:
                        default = None
                    args.append(default)
            if p.kind is inspect._ParameterKind.VAR_POSITIONAL:
                while len(chain) > 0:
                    await append_single_arg()
            else:
                await append_single_arg()
        return args


class OutOfContext(Context):
    event: PlaceholderEvent


class NudgeContext(Context):
    event: NudgeEvent

    def get_instr_attr_name(self):
        return '_nudge_instr_'

class JoinReqContext(Context):
    event: MemberJoinRequestEvent

    async def exec_join(self, send_cb: Callable):
        with self:
            fin_res = None

            def get_resp_from_res(res):
                if isinstance(res, tuple):
                    resp, _ = res
                else:
                    resp = res
                return resp

            def update_res(res):
                nonlocal fin_res
                if fin_res is None:
                    fin_res = res
                    return
                if get_resp_from_res(fin_res) == RespOperate.BAN:
                    return
                if get_resp_from_res(res) == RespOperate.BAN:
                    fin_res = res
                    return
                if get_resp_from_res(fin_res) == RespOperate.DECLINE:
                    return
                if get_resp_from_res(res) == RespOperate.DECLINE:
                    fin_res = res
                    return
                if get_resp_from_res(res) == RespOperate.ALLOW:
                    fin_res = res
                    return

            for plugin in self.engine.plugins.values():
                if plugin.disabled: continue
                async with plugin.override():
                    for _, method in inspect.getmembers(plugin, predicate=inspect.ismethod):
                        if hasattr(method, '_join_req_instr_'):
                            logger.debug(f'found {method=}')
                            try:
                                if InstrAttr.FORECE_BACKUP in method._instr_attrs_:
                                    plugin.backup_man.set_dirty()
                                res = await method(*(await self.resolve_args(method, [])))
                                update_res(res)
                            except:
                                traceback.print_exc()
            if fin_res is not None:
                if not isinstance(fin_res, tuple):
                    fin_res = (fin_res,)
                await send_cb(*fin_res)

class MemberCardChangeContext(Context):
    event: MemberCardChangeEvent
    def get_instr_attr_name(self):
        return '_member_card_changed_instr_'

class RecallContext(Context):
    event: GroupRecallEvent
    def get_instr_attr_name(self):
        return '_recall_instr_'

class JoinedContext(Context):
    event: MemberJoinEvent
    def get_instr_attr_name(self):
        return '_joined_instr_'

class UnmuteContext(Context):
    event: MemberUnmuteEvent
    def get_instr_attr_name(self):
        return '_unmute_instr_'

class MessageContext(Context):
    event: MessageEvent
            
    @staticmethod
    def preprocess(chain: MessageChain):
        res: List[MessageComponent] = []
        for msg in chain:
            if isinstance(msg, Plain):
                res.extend(list(filter(lambda x: x != '', msg.text.split(' '))))
            else:
                res.append(msg)
        return res
            
    async def exec_any(self, chain: MessageChain):
        processed_chain = self.preprocess(chain)
        async def cb(method: MethodType):
            return await method(*(await self.resolve_args(method, processed_chain[1:])))
        
        await self.instrs('_any_instr_', cb)

    async def exec_fall(self, chain: MessageChain):
        processed_chain = self.preprocess(chain)
        async def cb(method: MethodType):
            return await method(*(await self.resolve_args(method, processed_chain[2:])))

        await self.instrs('_fall_instr_', cb)


    async def exec_cmd(self, chain: MessageChain):
        
        top_instr_mod = False
        processed_chain = self.preprocess(chain)
        try:
            plugin_name = self.get_text(processed_chain[0])
        except:
            raise RuntimeError('请指定插件名')
        try:
            plugins = [self.engine.plugins[plugin_name]]
        except:
            plugins = self.engine.plugins.values()
            top_instr_mod = True

        self.stack.append(plugin_name)

        if top_instr_mod:
            instr_name = plugin_name
        else:
            instr_name = 'default'
            if len(processed_chain) > 0:
                try:
                    instr_name = self.get_text(processed_chain[1])
                except: ...

        instr_attr_name = '_top_instr_name_' if top_instr_mod else '_instr_name_'
        found = False

        async def cb(method: MethodType):
            nonlocal found
            match_result = re.fullmatch(getattr(method, instr_attr_name), instr_name, flags=re.IGNORECASE)
            if match_result:
                logger.debug(f'{instr_name=}, {match_result=}')
                found = True
                self.stack.append(instr_name)
                consume_param_cnt = 1 if top_instr_mod else 2
                try:
                    args = await self.resolve_args(method, processed_chain[consume_param_cnt:], match=match_result)
                    return await method(*args)
                except Exception as e:
                    if instr_name == '来只纳延':
                        traceback.print_exc()
                    raise

        await self.instrs(instr_attr_name, cb, plugins=plugins)

        if not found:
            raise CommandNotFoundError(f'指令{instr_name}不存在')

        # with self:
        #     for plugin in plugins:
        #         if plugin.disabled: continue
        #         async with plugin.override() as redirected:
        #             for _, method in inspect.getmembers(plugin, predicate=inspect.ismethod):
        #                 instr_attr_name = '_top_instr_name_' if top_instr_mod else '_instr_name_'
        #                 if hasattr(method, instr_attr_name):
        #                     match_result = re.fullmatch(getattr(method, instr_attr_name), instr_name, flags=re.IGNORECASE)
        #                     if match_result:
        #                         self.stack.append(instr_name)
        #                         if InstrAttr.FORECE_BACKUP in method._instr_attrs_:
        #                             plugin.backup_man.set_dirty()
        #                         s = inspect.signature(method)
        #                         params = [p for p in s.parameters.values() if p.kind != p.KEYWORD_ONLY]
        #                         if not self.is_target_msg(params, self.event):
        #                             raise RuntimeError(f'无法在当前上下文中调用')
        #                         consume_param_cnt = 1 if top_instr_mod else 2
        #                         self.set_redirected(None)
        #                         res = await method(*(await self.resolve_args(method, processed_chain[consume_param_cnt:], match=match_result)))
        #                         if res is not None:
        #                             if self.redirected is None:
        #                                 redirected(res, attrs=method._instr_attrs_)
        #                             await self.send()
        #                         return
        #                         # return await method(*(await self.resolve_args(method, processed_chain[consume_param_cnt:], match=match_result))), method._instr_attrs_

        #     raise CommandNotFoundError(f'指令{instr_name}不存在')

@dataclass
class InstrDesc():
    name: str = 'default'
    bypass: bool = False
    advice: bool = False
    fallback: bool = False
    force_backup: bool = False
    ...

def bypass(fn):
    desc = ensure_attr(fn, InstrDesc)
    desc.bypass = True

def advice(fn):
    desc = ensure_attr(fn, InstrDesc)
    desc.advice = True

def fallback(fn):
    desc = ensure_attr(fn, InstrDesc)
    desc.fallback = True

def force_backup(fn):
    desc = ensure_attr(fn, InstrDesc)
    desc.force_backup = True

def instr(name = 'default', *attr):
    def wrapper(func):
        func._instr_name_ = name
        func._instr_attrs_ = flatten(list(attr))
        return func
    return wrapper

def top_instr(name, *attr):
    def wrapper(func):
        func._top_instr_name_ = name
        func._instr_attrs_ = flatten(list(attr))
        return func
    return wrapper
    ...

def any_instr(*attr):
    def wrapper(func):
        func._any_instr_ = True
        func._instr_attrs_ = flatten(list(attr))
        return func
    return wrapper
    ...

def fall_instr(*attr):
    def wrapper(func):
        func._fall_instr_ = True
        func._instr_attrs_ = flatten(list(attr))
        return func
    return wrapper

def nudge_instr(*attr):
    def wrapper(func):
        func._nudge_instr_ = True
        func._instr_attrs_ = flatten(list(attr))
        return func
    return wrapper

def join_req_instr(*attr):
    def wrapper(func):
        func._join_req_instr_ = True
        func._instr_attrs_ = flatten(list(attr))
        return func
    return wrapper

def joined_instr(*attr):
    def wrapper(func):
        func._joined_instr_ = True
        func._instr_attrs_ = flatten(list(attr))
        return func
    return wrapper

def card_changed_instr(*attr):
    def wrapper(func):
        func._member_card_changed_instr_ = True
        func._instr_attrs_ = flatten(list(attr))
        return func
    return wrapper

def recall_instr(*attr):
    def wrapper(func):
        func._recall_instr_ = True
        func._instr_attrs_ = flatten(list(attr))
        return func
    return wrapper

def unmute_instr(*attr):
    def wrapper(func):
        func._unmute_instr_ = True
        func._instr_attrs_ = flatten(list(attr))
        return func
    return wrapper

def autorun(func):
    func._bot_autorun_ = True
    return func


# Array[int, Literal[2]]

T = TypeVar('T')
class _Inject(Generic[T]): ...

Inject = Union[T, _Inject[T]]

def try_get_injector(anno):
    maybe_patharg_wrapper = get_origin(anno)
    if maybe_patharg_wrapper is not Union:
        return
    wrapper_args = get_args(anno)
    if len(wrapper_args) != 2:
        return
    xtype_refer, maybe_inject_g = wrapper_args
    maybe_inject = get_origin(maybe_inject_g)
    if maybe_inject is not _Inject:
        return
    xtype, = get_args(maybe_inject_g)
    # print('xtype', xtype)
    if xtype_refer is not xtype:
        return
    return xtype
    ...

class InjectNotifier():
    @abstractmethod
    def injected(self, target: 'Plugin'):
        ...
    ...

class AchvCustomizer():
    async def is_achv_deletable(self, e: 'AchvEnum') -> bool:
        return False
    
    async def is_achv_obtained(self, e: 'AchvEnum') -> bool:
        return False

class AllLoadedNotifier():
    @abstractmethod
    def all_loaded(self):
        ...
    ...

T = TypeVar('T')
TPos = TypeVar('TPos') #Literal[2]
class _PathArg(Generic[T, TPos]): ...

PathArgOf = Union[T, _PathArg[T, TPos]]
PathArg = PathArgOf[T, Literal[999]]

def try_get_patharg_params(anno, _def_pos: str):
    maybe_patharg_wrapper = get_origin(anno)
    if maybe_patharg_wrapper is not Union:
        return
    wrapper_args = get_args(anno)
    if len(wrapper_args) != 2:
        return
    xtype_refer, maybe_patharg_g = wrapper_args
    maybe_patharg = get_origin(maybe_patharg_g)
    if maybe_patharg is not _PathArg:
        return
    xtype, literal_pos_g = get_args(maybe_patharg_g)
    if xtype_refer is not xtype:
        return
    maybe_literal_pos = get_origin(literal_pos_g)
    if maybe_literal_pos is not Literal:
       return
    (pos,) = get_args(literal_pos_g)
    if pos == 999: pos = _def_pos
    return xtype, pos

@dataclass
class PluginConfig():
    name: str = field(init=False)
    backup_enabled = False
    ...

def route(name):
    def wrapper(target):
        if inspect.isclass(target):
            config = ensure_attr(target, PluginConfig)
            config.name = name
        else:
            desc = ensure_attr(target, InstrDesc)
            desc.name = name
        return target
    return wrapper

def enable_backup(cls):
    config = ensure_attr(cls, PluginConfig)
    config.backup_enabled = True
    return cls
    ...

@dataclass
class State(Generic[T]):
    default: T = None
    default_factory: Callable[[], T] = None

    def create(self) -> T:
        if self.default is not None:
            return self.default
        factory = self.default_factory
        if factory is None:
            factory = get_args(self.__orig_class__)[0]
        return factory()


# todo: use_state[T] python 3.12+