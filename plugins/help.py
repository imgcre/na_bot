from typing import Optional
from plugin import Plugin, route, top_instr
from utilities import AchvInfo

@route('帮助系统')
class Help(Plugin):
    
    @top_instr('帮助')
    async def help(self, sub_cmd: Optional[str]):
        from plugins.admin import AdminAchv
        admin_info: AchvInfo = AdminAchv.ADMIN.value
        
        if sub_cmd is None:
            return [
                '\n'.join([
                    '===帮助页面施工中===',
                    '【子命令】',
                    f'管理: 管理员介绍及指令列表',
                ])
            ]
        
        if sub_cmd == '管理':
            return [
                '\n\n'.join([
                    f'通过【#佩戴 {admin_info.aka}】佩戴管理{admin_info.opts.display}称号后, 即可解锁管理系列指令',
                    f'#撤回: 引用一条群友的消息, 然后回复"#撤回"即可撤回指定消息',
                    f'#公告: 引用一条群友的消息, 然后回复"#公告", 将会导致bot发布一则内容与被引用消息一致的公告',
                    f'#全体: @全体成员',
                    f'代理执行: 引用一条群友的消息, 如果回复的消息中包含被中括号指定的文本, 则将代指定群友执行中括号中的指令。'
                    '如回复的消息内容是"【#来只灯泡】", 则视作该群友自助领取了一颗灯泡'
                ])
            ]
        ...
    
    ...