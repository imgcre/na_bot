from typing import Final
from plugin import Plugin, route, enable_backup, instr
from bilibili_api import Credential

@route('b站')
@enable_backup
class Bili(Plugin):
    credential: Credential = Credential(
        sessdata="22d13ed4%2C1714846864%2C91015%2Ab2CjDFXW-ALsFjVnMktWvyu7zUNWdTWx4r3nlrwjJgWPnCU_STbzNu7mlq9SSHg4j8sFoSVkFvRmFEV3lQdV91WDluR3BKMHMtSlhKdE5wSVFBLWxDdTg5NnY1enJBSHl2c1hZbUNmZl9xQmpoYjdMbTE3eGtVN3lmOVdQMVVYdnc0MWhtRGFDX2xRIIEC", 
        bili_jct="6073ebbb6badedee04199b1a0c091f9a", 
        buvid3="62161A88-1EE0-FE5F-4DF9-222A643D8E7795311infoc", #不会变
        dedeuserid="3300650",  #不会变
        ac_time_value="f4a406fd013f7927de8f88790f1401b2"
    )

    async def __aenter__(self):
        if await self.credential.chcek_refresh():
            await self.credential.refresh()
            self.backup_man.set_dirty()
        return self.credential

    async def __aexit__(self, type, value, trace):
        ...

    @instr('help')
    async def help(self):
        return '\n'.join([
            'get_crdl --获取凭证',
            'set_crdl --设置凭证'
        ])

    # @instr('get_crdl')
    # @admin
    # async def get_crdl(self):
    #     return [json.dumps(self.credential.get_cookies(), indent=2)]

    # @instr('set_crdl')
    # @admin
    # async def set_crdl(self, *args: str):
    #     j = json.loads(''.join(args))
    #     self.credential = Credential(
    #         sessdata=j['SESSDATA'], 
    #         bili_jct=j['bili_jct'], 
    #         buvid3=j['buvid3'],
    #         dedeuserid=j['DedeUserID'],
    #         ac_time_value=j['ac_time_value']
    #     )
    #     return ['done.']