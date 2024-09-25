import inspect
import traceback
from types import MethodType

from plugin import AllLoadedNotifier, Plugin, route
from utilities import get_logger

logger = get_logger()

@route('events')
class Events(Plugin, AllLoadedNotifier):
    registed_handlers: dict[Plugin, set[MethodType]]

    def __init__(self) -> None:
        self.registed_handlers = {}


    async def emit(self, obj):
        # t = type(obj)
        # print(f'{t.__name__=}')
        # globals()[t.__name__] = t

        try:

            for plguin, handlers in self.registed_handlers.items():
                for handler in handlers:
                    # print(f'[{handler=}]')
                    s = inspect.signature(handler)
                    params = [p for p in s.parameters.values() if p.kind != p.KEYWORD_ONLY]
                    if not any([isinstance(obj, p.annotation) for p in params]):
                        continue
                    # print(f'matched [{handler=}]')
                    try:
                        await handler(obj)
                    except: 
                        traceback.print_exc()
                        ...
        except:
            traceback.print_exc()

    def all_loaded(self):
        for target in self.engine.plugins.values():
            for _, method in inspect.getmembers(target, predicate=inspect.ismethod):
                if hasattr(method, '_event_handler_'):
                    if target not in self.registed_handlers:
                        self.registed_handlers[target] = set()
                    
                    logger.debug(f'found event handler {method.__self__.__class__.__name__}.{method.__name__}')
                    self.registed_handlers[target].add(method)