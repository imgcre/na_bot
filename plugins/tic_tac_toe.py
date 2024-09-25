import asyncio
from enum import Enum, auto
from typing import Final, List, Optional
from mirai import At, GroupMessage
from mirai.models.entities import GroupMember
from plugin import Context, Plugin, autorun, instr, route
import random

class GameResult(Enum):
    PENDING = auto(),
    WIN_O = auto(),
    WIN_X = auto(),
    DRAW = auto()

class GameResolveOptions(Enum):
    FORCE = auto()
    ...

class Game():
    O: Final = 'O'
    X: Final = 'X'
    EMPTY: Final = '_'

    def __init__(self, owner: GroupMember) -> None:
        self.owner = owner
        self.parti = None
        self.stared = False
        self.board = [[self.EMPTY, self.EMPTY, self.EMPTY] for _ in range(3)]
        self.id = ''.join(random.sample('zyxwvutsrqponmlkjihgfedcba0123456789',5))
        self.des_rt = 60 # 销毁时间，没有任何操作则自动销毁

    def start(self):
        if self.parti is None:
            raise RuntimeError(f'{self}参与者不存在, 请先[加入]')
        if self.stared:
            raise RuntimeError(f'{self}已经开始, 请勿重复启动')

        self.refresh_des_rt()
        self.current = random.choice([self.owner, self.parti])
        self.stared = True

    def join(self, parti: GroupMember):
        if self.stared:
            raise RuntimeError(f'无法加入, {self}已经开始')
        if self.parti is not None:
            raise RuntimeError(
                f'加入对局失败, 已存在参与者',
                At(target=self.parti.id)
            )
        if self.owner.id == parti.id:
            raise RuntimeError(f'您已加入{self}, 请勿重复加入')
        self.parti = parti

    def refresh_des_rt(self):
        self.des_rt = 60

    @property
    def curr_shape(self):
        if self.current == self.owner:
            return self.O
        else:
            return self.X

    def fall(self, player: GroupMember, x: int, y: int) -> GameResult:
        if not self.stared:
            raise RuntimeError(f'{self}尚未开始')
        if self.owner.id != player.id and self.parti.id != player.id:
            raise RuntimeError(f'您不是{self}的玩家')
        if self.current.id != player.id:
            raise RuntimeError('当前不是您的回合')
        if x < 1 or x > 3 or y < 1 or y > 3:
            raise RuntimeError('参数错误, 坐标值超出界限')

        if self.board[y - 1][x - 1] != self.EMPTY:
            raise RuntimeError('落子失败, 请勿重复在相同位置落子')

        self.refresh_des_rt()
        self.board[y - 1][x - 1] = self.curr_shape
        if self.current == self.owner:
            self.current = self.parti
        else:
            self.current = self.owner

        winner = self.calc_winner()
        drawed = self.is_draw()
        if winner is not None:
            if winner is self.owner:
                return GameResult.WIN_O
            elif winner is self.parti:
                return GameResult.WIN_X
        if drawed:
            return GameResult.DRAW
        return GameResult.PENDING

    def calc_winner(self) -> GroupMember:
        # 行上连子
        for row in self.board:
            if row[0] == row[1] and row[1] == row[2]:
                if row[0] == self.O:
                    return self.owner
                elif row[0] == self.X:
                    return self.parti

        for i in range(3):
            if self.board[0][i] == self.board[1][i] and self.board[1][i] == self.board[2][i]:
                if self.board[0][i] == self.O:
                    return self.owner
                elif self.board[0][i] == self.X:
                    return self.parti

        if self.board[0][0] == self.board[1][1] and self.board[1][1] == self.board[2][2]:
            if self.board[0][0] == self.O:
                return self.owner
            elif self.board[0][0] == self.X:
                return self.parti

        if self.board[0][2] == self.board[1][1] and self.board[1][1] == self.board[2][0]:
            if self.board[0][2] == self.O:
                return self.owner
            elif self.board[0][2] == self.X:
                return self.parti

        return None

    def is_draw(self):
        for i in range(3):
            for j in range(3):
                if self.board[i][j] == self.EMPTY:
                    return False
        return True
        ...

    def pretty_player(self):
        return [
            '\nO方:',
            At(target=self.owner.id),
            '\nX方:',
            At(target=self.parti.id),
        ]

    def pretty_board(self) -> str:
        return '\n'.join([' '.join(r) for r in self.board])

    def __str__(self) -> str:
        return f'{{对局 {self.id}}}'

@route('井字棋')
class TicTacToe(Plugin):
    games: List[Game] = []

    @autorun
    async def manage_game(self):
        while True:
            await asyncio.sleep(1)
            next = []
            for game in self.games:
                game.des_rt -= 1
                if game.des_rt == 30:
                    bb = [f'{game}将在30s后自动结束']
                    if game.stared:
                        bb.extend([
                            ', 请',
                            At(target=game.current.id),
                            '落子'
                        ])
                    await self.bot.send_group_message(game.owner.group.id, bb)
                if game.des_rt <= 0:
                    bb = [f'{game}由于长时间未操作自动结束']
                    if game.stared:
                        opposite = game.owner if game.current is not game.owner else game.parti
                        bb.extend([
                            ',',
                            At(target=opposite.id),
                            '获胜!'
                        ])
                    await self.bot.send_group_message(game.owner.group.id, bb)
                    continue
                next.append(game)
            self.games = next

    def get_resolvers(self):
        def resolve_game(ctx: Context, event: GroupMessage, id: Optional[str]):
            game: Game = None
            while True:
                if id is None: 
                    if GameResolveOptions.FORCE in ctx.instr_attrs:
                        raise RuntimeError('此命令必须指定对局id')
                    joined_games = list(filter(lambda game: game.owner.id == event.sender.id or game.parti.id == event.sender.id, self.games))
                    if len(joined_games) > 1:
                        raise RuntimeError('您曾加入了多个对局, 请指定目标对局id')
                    if len(joined_games) == 0:
                        raise RuntimeError('您尚未加入任何对局, 请先创建或加入对局')
                    game = joined_games[0]
                    break
                try:
                    game = [game for game in self.games if game.id == id][0]
                    break
                except:
                    raise RuntimeError(f'对局{id}不存在')
            if event.sender.group.id != game.owner.group.id:
                raise RuntimeError(f'{game}不属于本群')
            return game
        return {
            Game: resolve_game
        }

    @instr('创建')
    async def create(self, event: GroupMessage):
        game = Game(event.sender)
        self.games.append(game)
        return [
            f'您已创建{game}, 参与者可使用[加入]命令加入对局'
        ]
    
    @instr('加入', GameResolveOptions.FORCE)
    async def join(self, event: GroupMessage, game: Game):
        game.join(event.sender)
        return [
            f'您已成功加入{game}, 请创建者使用[开始]命令开始对局'
        ]

    @instr('开始')
    async def start(self, _: GroupMessage, game: Game):
        game.start()
        return [
            f'{game}已经开始',
            *game.pretty_player(),
            '\n请',
            At(target=game.current.id),
            ' 先[落子]'
        ]

    @instr('落子')
    async def fall(self, event: GroupMessage, x: int, y: int, game: Game):
        res = game.fall(event.sender, x, y)
        if res == GameResult.PENDING:
            return [
                f'落子成功, 请',
                At(target=game.current.id),
                '继续落子',
                f'\n\n{game}',
                *game.pretty_player(),
                '\n\n' + game.pretty_board(),
            ]
        if res == GameResult.DRAW:
            resp = [
                f'结果: 双方平局!',
                f'\n\n{game}',
                *game.pretty_player(),
                '\n\n' + game.pretty_board(),
            ]
        else:
            winner = game.owner if res == GameResult.WIN_X else game.parti
            resp = [
                '恭喜',
                At(target=winner.id),
                f' 取得胜利!',
                f'\n\n{game}',
                *game.pretty_player(),
                '\n\n' + game.pretty_board(),
            ]
        self.games.remove(game)
        return resp
