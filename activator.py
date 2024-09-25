from abc import ABC, abstractmethod
from mirai import MessageEvent, MessageChain, Plain
from mirai.models.message import Quote

class Activator(ABC):
    @abstractmethod
    def check(self, event: MessageEvent) -> MessageChain: ...

class SharpActivator(Activator):
    def check(self, event: MessageEvent) -> MessageChain: 
        chain = event.message_chain
        chain = chain[:]
        quote_li = []
        if len(chain) > 1 and isinstance(chain[1], Quote):
            quote_li = [chain.pop(1)]
        if len(chain) > 1 and isinstance(chain[1], Plain) and len(str(chain[1])) > 0 and str(chain[1])[0] in ('#', '＃', '/'):
            return [Plain(str(chain[1])[1:]), *chain[2:], *quote_li]
        return None
