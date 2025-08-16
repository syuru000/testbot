import discord
from discord.ext import commands
from discord import app_commands
import random
import asyncio
import sqlite3
import json
from typing import List
from item_manager import ItemManager # ItemManager 임포트
import time # time 모듈 임포트

# 순환 참조 방지를 위한 타입 힌트
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from main import get_db_connection, update_game_status

# --- 몬스터 데이터 ---
MONSTERS = {
    "슬라임": {"hp": 20, "attack": 5, "gold": 2, "exp": 3, "drops": {"기초 회복 물약": 0.3, "생고기": 0.5}},
    "고블린": {"hp": 35, "attack": 8, "gold": 5, "exp": 7, "drops": {"기초 회복 물약": 0.2, "독 물약": 0.1}},
    "오크": {"hp": 50, "attack": 12, "gold": 10, "exp": 12, "drops": {"공격력 강화 물약": 0.1, "생고기": 0.7}},
    "늑대": {"hp": 25, "attack": 7, "gold": 3, "exp": 5, "drops": {"생고기": 0.8}},
    "거미": {"hp": 15, "attack": 4, "gold": 1, "exp": 2, "drops": {"독 물약": 0.05}}
}

# --- 전투 UI ---
class BattleView(discord.ui.View):
    def __init__(self, bot, player_id, monster_name, game_cog_instance):
        super().__init__(timeout=60)
        self.bot = bot
        self.player_id = player_id
        self.monster_name = monster_name
        self.monster = MONSTERS[monster_name].copy()
        self.game_cog = game_cog_instance
        self.battle_message: discord.Message = None # 나중에 설정될 메시지 객체
        

    async def on_timeout(self):
        self.game_cog.active_users.discard(self.player_id)
        # 타임아웃 시 버튼 비활성화
        for item in self.children:
            item.disabled = True
        await self.battle_message.edit(view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.player_id:
            await interaction.response.send_message("당신의 전투가 아닙니다!", ephemeral=True)
            return False
        return True

    async def handle_battle_end(self):
        self.game_cog.active_users.discard(self.player_id)
        # 전투 종료 시 버튼 비활성화
        for item in self.children:
            item.disabled = True
        await self.battle_message.edit(view=self)
        self.stop()

    @discord.ui.button(label="공격", style=discord.ButtonStyle.danger)
    async def attack(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        from main import get_db_connection
        conn = get_db_connection()
        c = conn.cursor()

        c.execute("SELECT * FROM players WHERE user_id = ?", (self.player_id,))
        player_data = c.fetchone()

        if not player_data:
            await self.battle_message.edit(content="오류: 플레이어 정보를 찾을 수 없습니다.", view=None)
            await self.handle_battle_end()
            conn.close()
            return

        player_hp = player_data['hp']
        attack_buff_until = player_data['attack_buff_until']

        # --- 플레이어 공격 ---
        player_attack = random.randint(5, 15)
        weapon_name = "돌 칼" # 지금은 돌 칼만 사용
        durability_message = ""
        if attack_buff_until and time.time() < attack_buff_until:
            player_attack += 10 # 예시: 버프 시 공격력 10 증가

        if await self.game_cog._has_item(self.player_id, weapon_name):
            weapon_info = self.game_cog.item_manager.get_item_by_name(weapon_name)
            if weapon_info and weapon_info.effect_type == 'attack_boost':
                player_attack += weapon_info.effect_value

            success, durability_message = await self.game_cog._use_tool(self.player_id, weapon_name)
            if not success:
                durability_message = f"\n({weapon_name} 내구도 처리 중 오류 발생)"

        battle_log = f"⚔️ {player_data['nickname']}이(가) {self.monster_name}에게 {player_attack}의 데미지를 입혔습니다.\n   (몬스터 남은 HP: {self.monster['hp'] - player_attack})\n"
        if durability_message:
            battle_log += durability_message + "\n"

        self.monster['hp'] -= player_attack

        # 플레이어 상태 이상 적용 (독)
        if player_data['status_effect'] == 'poison' and time.time() < player_data['status_effect_end_time']:
            poison_damage = 5 # 예시: 독 데미지
            new_hp = player_hp - poison_damage
            c.execute("UPDATE players SET hp = ? WHERE user_id = ?", (new_hp, self.player_id))
            battle_log += f"💀 {player_data['nickname']}이(가) 독으로 인해 {poison_damage}의 데미지를 입었습니다. (남은 HP: {new_hp})\n"
            player_hp = new_hp # 업데이트된 HP 반영

        # 상태 이상 종료 확인 및 제거
        if player_data['status_effect'] and time.time() >= player_data['status_effect_end_time']:
            c.execute("UPDATE players SET status_effect = NULL, status_effect_end_time = 0, status_effect_value = 0 WHERE user_id = ?", (self.player_id,))
            battle_log += f"✨ {player_data['nickname']}의 {player_data['status_effect']} 상태 이상이 해제되었습니다.\n"

        # --- 몬스터 사망 처리 ---
        if self.monster['hp'] <= 0:
            gold_reward = self.monster['gold']
            exp_reward = self.monster['exp']
            c.execute("UPDATE players SET gold = gold + ?, exp = exp + ? WHERE user_id = ?", (gold_reward, exp_reward, self.player_id))
            battle_log += f"\n🎉 {self.monster_name}을(를) 물리쳤습니다!\n   골드 +{gold_reward}, 경험치 +{exp_reward}을 획득했습니다."

            if "drops" in MONSTERS[self.monster_name]:
                for item_name, drop_rate in MONSTERS[self.monster_name]["drops"].items():
                    if random.random() < drop_rate:
                        await self.game_cog.add_item_to_inventory(self.player_id, item_name)
                        battle_log += f"\n   ✨ {item_name}을(를) 획득했습니다!"

            await self.battle_message.edit(content=battle_log, view=None)
            await self.handle_battle_end()
            conn.commit()
            conn.close()
            return

        # --- 몬스터 반격 ---
        monster_attack = self.monster['attack']
        c.execute("UPDATE players SET hp = hp - ? WHERE user_id = ?", (monster_attack, self.player_id))
        c.execute("SELECT hp FROM players WHERE user_id = ?", (self.player_id,))
        new_hp = c.fetchone()['hp']

        battle_log += f"\n🩸 {self.monster_name}이(가) {player_data['nickname']}에게 {monster_attack}의 데미지를 입혔습니다.\n   (남은 HP: {new_hp})"

        # --- 플레이어 사망 처리 ---
        if new_hp <= 0:
            c.execute("UPDATE players SET hp = 1 WHERE user_id = ?", (self.player_id,))
            battle_log += f"\n\n☠️ 전투에서 패배했습니다..."
            await self.battle_message.edit(content=battle_log, view=None)
            await self.handle_battle_end()
        else:
            await self.battle_message.edit(content=battle_log)

        conn.commit()
        conn.close()

    @discord.ui.button(label="도망", style=discord.ButtonStyle.secondary)
    async def flee(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer() # 상호작용 응답
        await self.battle_message.edit(content="무사히 도망쳤습니다.", view=None) # 메시지 업데이트 및 버튼 제거
        await self.handle_battle_end()

# --- 게임 명령어 Cog ---
class GameCog(commands.Cog):
    game_group = app_commands.Group(name="게임", description="게임 관련 명령어입니다.")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_users = set()
        self.item_manager = ItemManager() # ItemManager 인스턴스 생성
        self.item_manager.load_items_from_db() # 아이템 데이터 로드
        self.recipes = {
            "낡은 낚싯대": {"나뭇가지": 5, "질긴 나뭇잎": 2},
            "튼튼한 낚싯대": {"나뭇가지": 10, "질긴 나뭇잎": 5},
            "돌 칼": {"나뭇가지": 2, "돌멩이": 5}
        }

    async def _check_game_channel_and_role(self, interaction: discord.Interaction) -> bool:
        """게임 채널 및 역할 권한을 확인하는 내부 헬퍼 함수"""
        if interaction.channel_id == self.bot.wind_channel_id:
            required_role_id = self.bot.channel_1_role_id
        elif interaction.channel_id == self.bot.ice_channel_id:
            required_role_id = self.bot.channel_2_role_id
        else:
            # defer()가 호출되기 전이므로 response 사용 가능
            await interaction.response.send_message("이 명령어는 게임 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return False

        required_role = interaction.guild.get_role(required_role_id)
        if not required_role or required_role not in interaction.user.roles:
            # defer()가 호출되기 전이므로 response 사용 가능
            await interaction.response.send_message("이 채널에 입장할 수 있는 역할이 없습니다.", ephemeral=True)
            return False
        return True

    async def _has_item(self, user_id: int, item_name: str) -> bool:
        """플레이어의 인벤토리에 특정 아이템이 있는지 확인하는 헬퍼 함수"""
        from main import get_db_connection
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("""
            SELECT 1 FROM player_inventory pi
            JOIN items i ON pi.item_id = i.id
            WHERE pi.user_id = ? AND i.name = ? AND pi.quantity > 0
        """, (user_id, item_name))
        result = c.fetchone()
        conn.close()
        return result is not None

    async def add_item_to_inventory(self, user_id: int, item_name: str, quantity: int = 1):
        from main import get_db_connection
        conn = get_db_connection()
        c = conn.cursor()

        item = self.item_manager.get_item_by_name(item_name)
        if not item:
            conn.close()
            return False # 아이템을 찾을 수 없음

        c.execute("SELECT quantity FROM player_inventory WHERE user_id = ? AND item_id = ?", (user_id, item.id))
        existing_item = c.fetchone()

        if existing_item and item.stackable:
            new_quantity = existing_item['quantity'] + quantity
            if new_quantity > item.max_stack:
                new_quantity = item.max_stack
            c.execute("UPDATE player_inventory SET quantity = ? WHERE user_id = ? AND item_id = ?", (new_quantity, user_id, item.id))
        elif not existing_item:
            durability = item.max_durability if item.max_durability is not None else None
            c.execute("INSERT INTO player_inventory (user_id, item_id, quantity, durability) VALUES (?, ?, ?, ?)", (user_id, item.id, quantity, durability))
        else: # 아이템이 존재하지만, 스택 불가능한 아이템일 경우
            pass

        conn.commit()
        conn.close()
        return True

    async def _use_tool(self, user_id: int, tool_name: str):
        conn = None
        try:
            from main import get_db_connection
            conn = get_db_connection()
            c = conn.cursor()

            c.execute("""
                SELECT i.id, pi.durability, i.max_durability 
                FROM player_inventory pi 
                JOIN items i ON pi.item_id = i.id 
                WHERE pi.user_id = ? AND i.name = ?
            """, (user_id, tool_name))
            item_info = c.fetchone()

            if not item_info:
                return False, f"오류: 인벤토리에서 {tool_name}을(를) 찾을 수 없습니다."

            item_id = item_info['id']
            current_durability = item_info['durability']
            max_durability = item_info['max_durability']

            if max_durability is None:
                return True, ""

            if current_durability is None:
                current_durability = max_durability

            new_durability = current_durability - 1
            
            message = ""
            if new_durability > 0:
                c.execute("UPDATE player_inventory SET durability = ? WHERE user_id = ? AND item_id = ?", 
                          (new_durability, user_id, item_id))
                message = f"({tool_name}의 내구도가 1 감소했습니다.)"
            else:
                c.execute("DELETE FROM player_inventory WHERE user_id = ? AND item_id = ?", 
                          (user_id, item_id))
                message = f"**{tool_name}이(가) 모두 사용되어 부서졌습니다!**"
            
            conn.commit()
            return True, message

        except sqlite3.Error as e:
            if conn: conn.rollback()
            print(f"DB Error in _use_tool (User: {user_id}, Tool: {tool_name}): {e}")
            return False, "데이터베이스 오류로 도구를 사용할 수 없습니다."
        finally:
            if conn: conn.close()

    # --- Autocompletes ---
    async def move_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        from main import get_db_connection
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT l.name FROM map_connections mc JOIN locations l ON mc.to_location_id = l.id WHERE mc.from_location_id = (SELECT current_location_id FROM players WHERE user_id = ?)", (interaction.user.id,))
        destinations = [row['name'] for row in c.fetchall()]
        conn.close()
        return [app_commands.Choice(name=dest, value=dest) for dest in destinations if current.lower() in dest.lower()]

    async def action_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        from main import get_db_connection
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT l.actions FROM players p JOIN locations l ON p.current_location_id = l.id WHERE p.user_id = ?", (interaction.user.id,))
        actions_json = c.fetchone()['actions']
        conn.close()
        
        if actions_json:
            actions = json.loads(actions_json)
            return [app_commands.Choice(name=action, value=action) for action in actions if current.lower() in action.lower()]
        return []

    async def item_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        from main import get_db_connection
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT i.name FROM player_inventory pi JOIN items i ON pi.item_id = i.id WHERE pi.user_id = ?", (interaction.user.id,))
        player_items = [row['name'] for row in c.fetchall()]
        conn.close()
        return [app_commands.Choice(name=item_name, value=item_name) for item_name in player_items if current.lower() in item_name.lower()]

    async def craft_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        return [app_commands.Choice(name=recipe, value=recipe) for recipe in self.recipes if current.lower() in recipe.lower()]

    # --- Commands ---
    @game_group.command(name="제작", description="재료를 사용하여 아이템을 제작합니다.")
    @app_commands.autocomplete(item_name=craft_autocomplete)
    async def craft(self, interaction: discord.Interaction, item_name: str):
        if not await self._check_game_channel_and_role(interaction): return
        if interaction.user.id in self.active_users:
            return await interaction.response.send_message("이미 다른 행동을 하고 있습니다.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        if item_name not in self.recipes:
            return await interaction.followup.send("제작할 수 없는 아이템입니다.")

        recipe = self.recipes[item_name]
        
        from main import get_db_connection
        conn = None
        try:
            conn = get_db_connection()
            c = conn.cursor()

            for material, required_amount in recipe.items():
                c.execute("SELECT pi.quantity FROM player_inventory pi JOIN items i ON pi.item_id = i.id WHERE pi.user_id = ? AND i.name = ?", (interaction.user.id, material))
                result = c.fetchone()
                if not result or result['quantity'] < required_amount:
                    await interaction.followup.send(f"재료가 부족합니다: {material} {required_amount}개 필요")
                    return
            
            for material, required_amount in recipe.items():
                c.execute("UPDATE player_inventory SET quantity = quantity - ? WHERE user_id = ? AND item_id = (SELECT id FROM items WHERE name = ?)", (required_amount, interaction.user.id, material))

            item_to_add = self.item_manager.get_item_by_name(item_name)
            if not item_to_add:
                await interaction.followup.send("제작하려는 아이템 정보를 찾을 수 없습니다.")
                conn.rollback()
                return

            c.execute("SELECT quantity FROM player_inventory WHERE user_id = ? AND item_id = ?", (interaction.user.id, item_to_add.id))
            existing_item = c.fetchone()
            if existing_item:
                c.execute("UPDATE player_inventory SET quantity = quantity + 1 WHERE user_id = ? AND item_id = ?", (interaction.user.id, item_to_add.id))
            else:
                c.execute("INSERT INTO player_inventory (user_id, item_id, quantity) VALUES (?, ?, 1)", (interaction.user.id, item_to_add.id))

            conn.commit()
            await interaction.followup.send(f"축하합니다! {item_name}을(를) 제작했습니다.", ephemeral=False)

        except sqlite3.Error as e:
            print(f"/제작 명령어 처리 중 데이터베이스 오류 발생: {e}")
            if conn:
                conn.rollback()
            await interaction.followup.send("제작 중 오류가 발생했습니다. 다시 시도해주세요.")
        finally:
            if conn:
                conn.close()

    @game_group.command(name="인벤토리", description="현재 가지고 있는 아이템을 확인합니다.")
    async def inventory(self, interaction: discord.Interaction):
        if not await self._check_game_channel_and_role(interaction): return
        await interaction.response.defer(ephemeral=True)
        
        from main import get_db_connection
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("""
            SELECT i.name, pi.quantity, pi.durability, i.max_durability 
            FROM player_inventory pi 
            JOIN items i ON pi.item_id = i.id 
            WHERE pi.user_id = ?
        """, (interaction.user.id,))
        items = c.fetchall()
        conn.close()

        if not items:
            return await interaction.followup.send("인벤토리가 비어있습니다.")

        embed = discord.Embed(title="🎒 인벤토리", color=discord.Color.blue())
        for item in items:
            item_name = item['name']
            quantity = item['quantity']
            durability = item['durability']
            max_durability = item['max_durability']

            value = f"수량: {quantity}"
            if durability is not None and max_durability is not None:
                value += f" | 내구도: {durability}/{max_durability}"

            embed.add_field(name=item_name, value=value, inline=True)
        
        await interaction.followup.send(embed=embed)

    @game_group.command(name="직업선택", description="직업을 선택합니다. 한 번 선택하면 변경할 수 없습니다.")
    @app_commands.describe(job_name="선택할 직업의 이름 (검사, 마법사)")
    @app_commands.choices(job_name=[
        app_commands.Choice(name="검사", value="검사"),
        app_commands.Choice(name="마법사", value="마법사"),
    ])
    async def choose_job(self, interaction: discord.Interaction, job_name: str):
        if not await self._check_game_channel_and_role(interaction): return
        await interaction.response.defer(ephemeral=True)

        from main import get_db_connection
        conn = get_db_connection()
        c = conn.cursor()

        c.execute("SELECT job FROM players WHERE user_id = ?", (interaction.user.id,))
        current_job = c.fetchone()['job']

        if current_job != '초보자':
            conn.close()
            return await interaction.followup.send(f"이미 직업을 선택했습니다: {current_job}")

        if job_name not in ["검사", "마법사"]:
            conn.close()
            return await interaction.followup.send("유효하지 않은 직업 이름입니다. '검사' 또는 '마법사' 중에서 선택해주세요.")

        c.execute("UPDATE players SET job = ?, skp = 1 WHERE user_id = ?", (job_name, interaction.user.id))
        conn.commit()
        conn.close()

        await interaction.followup.send(f"축하합니다! 당신은 이제 {job_name}이(가) 되었습니다. 스킬 포인트 1을 획득했습니다.", ephemeral=False)

    @game_group.command(name="아이템사용", description="인벤토리의 아이템을 사용합니다.")
    @app_commands.autocomplete(item_name=item_autocomplete)
    async def use_item(self, interaction: discord.Interaction, item_name: str):
        if not await self._check_game_channel_and_role(interaction): return
        await interaction.response.defer(ephemeral=False)

        from main import get_db_connection
        conn = get_db_connection()
        c = conn.cursor()

        c.execute("SELECT pi.quantity, i.id, i.item_type, i.effect_type, i.effect_value FROM player_inventory pi JOIN items i ON pi.item_id = i.id WHERE pi.user_id = ? AND i.name = ?", (interaction.user.id, item_name))
        item_info = c.fetchone()

        if not item_info:
            conn.close()
            return await interaction.followup.send(f"인벤토리에 '{item_name}'이(가) 없습니다.", ephemeral=True)

        quantity, item_id, item_type, effect_type, effect_value = item_info

        item = self.item_manager.get_item(item_id)
        if not item:
            conn.close()
            return await interaction.followup.send("아이템 정보를 찾을 수 없습니다.", ephemeral=True)

        if item_type != 'consumable':
            conn.close()
            return await interaction.followup.send(f"'{item_name}'은(는) 사용할 수 있는 아이템이 아닙니다.", ephemeral=True)

        response_message = ""
        if effect_type == 'hp_recovery':
            c.execute("SELECT hp, level FROM players WHERE user_id = ?", (interaction.user.id,))
            player_hp, player_level = c.fetchone()
            max_hp = 100 + (player_level - 1) * 10
            
            recovered_hp = min(max_hp - player_hp, effect_value)
            if recovered_hp <= 0:
                response_message = f"이미 체력이 가득 찼습니다. '{item_name}'을(를) 사용할 필요가 없습니다."
            else:
                c.execute("UPDATE players SET hp = hp + ? WHERE user_id = ?", (recovered_hp, interaction.user.id))
                response_message = f"'{item_name}'을(를) 사용하여 체력 {recovered_hp}을(를) 회복했습니다. (현재 HP: {player_hp + recovered_hp})"
        elif effect_type == 'attack_boost':
            buff_duration = effect_value
            buff_end_time = time.time() + buff_duration
            c.execute("UPDATE players SET attack_buff_until = ? WHERE user_id = ?", (buff_end_time, interaction.user.id))
            response_message = f"'{item_name}'을(를) 사용하여 공격력이 {buff_duration}초 동안 증가했습니다!"
        elif effect_type == 'status_effect_apply':
            status_duration = effect_value
            status_end_time = time.time() + status_duration
            c.execute("UPDATE players SET status_effect = ?, status_effect_end_time = ? WHERE user_id = ?", (item.effect_name, status_end_time, interaction.user.id))
            response_message = f"'{item_name}'을(를) 사용하여 {item.effect_name} 상태 이상을 {status_duration}초 동안 부여했습니다!"
        elif effect_type == 'status_effect_cure':
            response_message = f"'{item_name}'을(를) 사용하여 상태 이상을 치료했습니다! (구현 예정)"
        else:
            response_message = f"'{item_name}'은(는) 현재 사용해도 아무런 효과가 없습니다."

        if quantity > 1:
            c.execute("UPDATE player_inventory SET quantity = quantity - 1 WHERE user_id = ? AND item_id = ?", (interaction.user.id, item_id))
        else:
            c.execute("DELETE FROM player_inventory WHERE user_id = ? AND item_id = ?", (interaction.user.id, item_id))
        
        conn.commit()
        conn.close()
        await interaction.followup.send(response_message)

    @game_group.command(name="입장", description="특정 채널에 입장하기 위한 역할을 받습니다.")
    @app_commands.describe(channel="입장할 채널을 선택하세요.")
    @app_commands.choices(channel=[
        app_commands.Choice(name="Wind", value="wind"),
        app_commands.Choice(name="Ice", value="ice"),
    ])
    async def join_channel(self, interaction: discord.Interaction, channel: str):
        if interaction.channel_id == self.bot.wind_channel_id or interaction.channel_id == self.bot.ice_channel_id:
            return await interaction.response.send_message("이 명령어는 Wind/Ice 채널에서 사용할 수 없습니다.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        role_id_to_add = self.bot.channel_1_role_id if channel == "wind" else self.bot.channel_2_role_id
        role_id_to_remove = self.bot.channel_2_role_id if channel == "wind" else self.bot.channel_1_role_id
        
        role_to_add = interaction.guild.get_role(role_id_to_add)
        role_to_remove = interaction.guild.get_role(role_id_to_remove)

        if not role_to_add:
            return await interaction.followup.send(f"'{channel}' 채널 역할을 찾을 수 없습니다. 관리자에게 문의하세요.")

        try:
            await interaction.user.add_roles(role_to_add)
            if role_to_remove and role_to_remove in interaction.user.roles:
                await interaction.user.remove_roles(role_to_remove)
            await interaction.followup.send(f"'{role_to_add.name}' 역할을 부여받았습니다! 이제 해당 채널에 입장할 수 있습니다.", ephemeral=False)
        except discord.Forbidden:
            await interaction.followup.send("역할을 부여할 권한이 없습니다.")

    @game_group.command(name="채널나가기", description="현재 입장해 있는 채널에서 나갑니다.")
    async def leave_channel(self, interaction: discord.Interaction):
        if interaction.channel_id != self.bot.wind_channel_id and interaction.channel_id != self.bot.ice_channel_id:
            return await interaction.response.send_message("이 명령어는 Wind 또는 Ice 채널에서만 사용할 수 없습니다.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        
        role_to_remove = None
        channel_name = ""

        if interaction.channel_id == self.bot.wind_channel_id:
            role_to_remove = interaction.guild.get_role(self.bot.channel_1_role_id)
            channel_name = "Wind"
        elif interaction.channel_id == self.bot.ice_channel_id:
            role_to_remove = interaction.guild.get_role(self.bot.channel_2_role_id)
            channel_name = "Ice"
        
        if not role_to_remove:
            return await interaction.followup.send(f"'{channel_name}' 채널 역할을 찾을 수 없습니다. 관리자에게 문의하세요.")

        if role_to_remove not in interaction.user.roles:
            return await interaction.followup.send(f"'{channel_name}' 채널에 입장해 있지 않습니다.")

        try:
            await interaction.user.remove_roles(role_to_remove)
            await interaction.followup.send(f"'{role_to_remove.name}' 이제 해당 채널에서 나갔습니다.", ephemeral=False)
        except discord.Forbidden:
            await interaction.followup.send("역할을 제거할 권한이 없습니다.")

    @game_group.command(name="주변", description="현재 위치의 정보와 이동 가능한 장소를 봅니다.")
    async def look_around(self, interaction: discord.Interaction):
        if not await self._check_game_channel_and_role(interaction): return
        await interaction.response.defer(ephemeral=False)

        from main import get_db_connection
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT l.name, l.description, l.id, l.actions FROM players p JOIN locations l ON p.current_location_id = l.id WHERE p.user_id = ?", (interaction.user.id,))
        current_location = c.fetchone()

        if not current_location:
            conn.close()
            return await interaction.followup.send("오류: 현재 위치를 찾을 수 없습니다.")

        c.execute("SELECT l.name FROM map_connections mc JOIN locations l ON mc.to_location_id = l.id WHERE mc.from_location_id = ?", (current_location['id'],))
        possible_moves = [row['name'] for row in c.fetchall()]
        conn.close()

        embed = discord.Embed(title=f"📍 현재 위치: {current_location['name']}", description=current_location['description'], color=discord.Color.green())
        if possible_moves:
            embed.add_field(name="이동 가능 장소", value=" / ".join(possible_moves), inline=False)
        else:
            embed.add_field(name="이동 가능 장소", value="이곳에서는 더 이상 이동할 곳이 없는 것 같습니다.", inline=False)
        
        if current_location['actions']:
            actions = json.loads(current_location['actions'])
            embed.add_field(name="가능한 행동", value=" / ".join(actions), inline=False)

        await interaction.followup.send(embed=embed)

    @game_group.command(name="이동", description="다른 장소로 이동합니다.")
    @app_commands.autocomplete(destination=move_autocomplete)
    async def move(self, interaction: discord.Interaction, destination: str):
        if not await self._check_game_channel_and_role(interaction): return
        if interaction.user.id in self.active_users:
            return await interaction.response.send_message("이미 다른 행동을 하고 있습니다.", ephemeral=True)

        self.active_users.add(interaction.user.id)
        await interaction.response.defer(ephemeral=False)

        from main import get_db_connection
        conn = get_db_connection()
        c = conn.cursor()
        
        c.execute("SELECT id FROM locations WHERE name = ?", (destination,))
        dest_location = c.fetchone()
        
        if not dest_location:
            self.active_users.discard(interaction.user.id)
            conn.close()
            return await interaction.followup.send("존재하지 않는 목적지입니다.")

        c.execute("SELECT to_location_id FROM map_connections WHERE from_location_id = (SELECT current_location_id FROM players WHERE user_id = ?) AND to_location_id = ?", (interaction.user.id, dest_location['id']))
        if not c.fetchone():
            self.active_users.discard(interaction.user.id)
            conn.close()
            return await interaction.followup.send("그곳으로는 이동할 수 없습니다.")

        c.execute("UPDATE players SET current_location_id = ? WHERE user_id = ?", (dest_location['id'], interaction.user.id))
        conn.commit()
        conn.close()

        await interaction.followup.send(f"당신은 {destination}(으)로 이동했습니다.")
        self.active_users.discard(interaction.user.id)

    @game_group.command(name="탐험", description="현재 지역을 탐험하여 새로운 사건을 마주합니다.")
    async def explore(self, interaction: discord.Interaction):
        if not await self._check_game_channel_and_role(interaction): return
        if interaction.user.id in self.active_users:
            return await interaction.response.send_message("이미 다른 행동을 하고 있습니다.", ephemeral=True)

        await interaction.response.defer(ephemeral=False)
        self.active_users.add(interaction.user.id)

        from main import get_db_connection
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT current_location_id FROM players WHERE user_id = ?", (interaction.user.id,))
        player_location_id = c.fetchone()['current_location_id']
        
        c.execute("SELECT monster_name FROM location_monsters WHERE location_id = ?", (player_location_id,))
        possible_monsters = [row['monster_name'] for row in c.fetchall()]
        conn.close()
        
        try:
            if possible_monsters and random.random() < 0.7:
                monster_name = random.choice(possible_monsters)
                # 1. View 객체를 먼저 생성합니다.
                view = BattleView(self.bot, interaction.user.id, monster_name, self)
                # 2. 메시지를 보낼 때 View를 함께 첨부합니다.
                message = await interaction.followup.send(f"야생의 {monster_name}이(가) 나타났다! 어떻게 하시겠습니까?", view=view, wait=True)
                # 3. 생성된 View에 방금 보낸 메시지 객체를 설정해줍니다.
                view.battle_message = message
            else:
                if random.random() < 0.2:
                    await self.add_item_to_inventory(interaction.user.id, "기초 회복 물약")
                    await interaction.followup.send("반짝이는 기초 회복 물약을 발견하여 획득했습니다!")
                else:
                    await interaction.followup.send("아무 일도 일어나지 않았습니다.")
                self.active_users.discard(interaction.user.id)
        except Exception as e:
            print(f"탐험 중 오류: {e}")
            if interaction.user.id in self.active_users:
                self.active_users.discard(interaction.user.id)

    @game_group.command(name="행동", description="현재 위치에서 특정 행동을 합니다.")
    @app_commands.autocomplete(action_name=action_autocomplete)
    async def do_action(self, interaction: discord.Interaction, action_name: str):
        if not await self._check_game_channel_and_role(interaction): return
        if interaction.user.id in self.active_users:
            await interaction.response.send_message("이미 다른 행동을 하고 있습니다.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=False)

        from main import get_db_connection
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT l.name, l.actions FROM players p JOIN locations l ON p.current_location_id = l.id WHERE p.user_id = ?", (interaction.user.id,))
        location_info = c.fetchone()
        conn.close()

        location_name = location_info['name']
        actions_json = location_info['actions']

        if not actions_json:
            await interaction.followup.send("이곳에서는 할 수 있는 행동이 없습니다.")
            return

        available_actions = json.loads(actions_json)

        if action_name not in available_actions:
            await interaction.followup.send(f"'{action_name}'은(는) 이곳에서 할 수 없는 행동입니다.")
            return

        self.active_users.add(interaction.user.id)
        response_message = f"당신은 {action_name}을(를) 시도합니다...\n\n"
        try:
            if action_name == "덤불 살피기":
                if random.random() < 0.5:
                    await self.add_item_to_inventory(interaction.user.id, "나뭇가지")
                    response_message += "덤불 속에서 쓸만한 나뭇가지를 발견했습니다!"
                else:
                    response_message += "아무것도 찾지 못했습니다."

            elif action_name == "나무 올라가기":
                if random.random() < 0.3:
                    response_message += "높은 곳에서 주변을 둘러보지만, 특별한 것은 보이지 않습니다."
                else:
                    await self.add_item_to_inventory(interaction.user.id, "질긴 나뭇잎")
                    response_message += "미끄러져 내려왔습니다. 다행히 다치진 않았고, 손에 질긴 나뭇잎이 걸렸습니다."
            elif action_name == "수풀 헤치기":
                if random.random() < 0.6:
                    response_message += "길을 찾았습니다! 하지만 아직 가기에는 험해보이는 길이네요.."
                else:
                    response_message += "수풀이 너무 우거져 더 이상 나아갈 수 없습니다."
            elif action_name == "버섯 채집":
                if random.random() < 0.7:
                    response_message += "독버섯을 채집했습니다! (아직 사용 불가)"
                else:
                    response_message += "아무 버섯도 찾지 못했습니다."
            elif action_name == "문 두드리기":
                response_message += "문이 굳게 닫혀있습니다. 안에서는 아무런 소리도 들리지 않습니다."
            elif action_name == "잔해 뒤지기":
                if random.random() < 0.4:
                    await self.add_item_to_inventory(interaction.user.id, "낡은 곡괭이")
                    response_message += "부서진 잔해 속에서 낡은 곡괭이를 발견했습니다!"
                else:
                    response_message += "부서진 잔해들 뿐입니다."            
            elif action_name == "낚시하기":
                if location_name != "강가":
                    response_message = "이곳에서는 낚시를 할 수 없습니다."
                else:
                    rod_name = None
                    if await self._has_item(interaction.user.id, "튼튼한 낚싯대"):
                        rod_name = "튼튼한 낚싯대"
                    elif await self._has_item(interaction.user.id, "낡은 낚싯대"):
                        rod_name = "낡은 낚싯대"

                    if not rod_name:
                        response_message = "낚싯대가 없습니다."
                    else:
                        await asyncio.sleep(2)
                        success, durability_message = await self._use_tool(interaction.user.id, rod_name)
                        if not success:
                            response_message = durability_message
                        else:
                            fish_roll = random.random()
                            if fish_roll < 0.5:
                                await self.add_item_to_inventory(interaction.user.id, "송사리")
                                response_message += "작고 귀여운 송사리를 낚았습니다."
                            elif fish_roll < 0.8:
                                await self.add_item_to_inventory(interaction.user.id, "잉어")
                                response_message += "제법 살이 오른 잉어를 낚았습니다!"
                            else:
                                response_message += "아무것도 낚지 못했습니다."
                            
                            if durability_message:
                                response_message += f"\n{durability_message}"

            elif action_name == "광물 채집":
                if location_name != "어두운 동굴":
                    response_message = "이곳에서는 광물을 채집할 수 없습니다."
                elif not await self._has_item(interaction.user.id, "낡은 곡괭이"):
                    response_message = "곡괭이가 없습니다."
                else:
                    await asyncio.sleep(3)
                    success, durability_message = await self._use_tool(interaction.user.id, "낡은 곡괭이")
                    if not success:
                        response_message = durability_message
                    else:
                        ore_roll = random.random()
                        if ore_roll < 0.6:
                            await self.add_item_to_inventory(interaction.user.id, "철광석")
                            response_message += "반짝이는 철광석을 발견하여 채집했습니다!"
                        else:
                            response_message += "돌멩이만 잔뜩 나왔습니다."

                        if durability_message:
                            response_message += f"\n{durability_message}"
            
            await interaction.followup.send(response_message)

        except Exception as e:
            print(f"/행동 명령어 처리 중 오류 발생 (Action: {action_name}, User: {interaction.user.id}): {e}")
            await interaction.followup.send("행동 처리 중 오류가 발생했습니다. 다시 시도해주세요.")
        finally:
            self.active_users.discard(interaction.user.id)

    @game_group.command(name="스탯", description="자신의 스탯 정보를 확인합니다.")
    async def stats(self, interaction: discord.Interaction):
        if not await self._check_game_channel_and_role(interaction): return
        await interaction.response.defer(ephemeral=True)
        
        from main import get_db_connection
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM players WHERE user_id = ?", (interaction.user.id,))
        player = c.fetchone()
        conn.close()

        if player:
            calculated_attack = player['strength'] + player['swordsmanship']
            calculated_defense = player['strength']

            embed = discord.Embed(title=f"⚔️ {player['nickname']}님의 스탯 정보", color=discord.Color.purple())
            embed.add_field(name="HP", value=f"{player['hp']}", inline=True)
            embed.add_field(name="MP", value=f"{player['mp']}", inline=True)
            embed.add_field(name="공격력", value=f"{calculated_attack}", inline=True)
            embed.add_field(name="방어력", value=f"{calculated_defense}", inline=True)
            embed.add_field(name="힘", value=f"{player['strength']}", inline=True)
            embed.add_field(name="검술", value=f"{player['swordsmanship']}", inline=True)
            embed.add_field(name="회복", value=f"{player['recovery']}", inline=True)
            embed.add_field(name="관찰", value=f"{player['observation']}", inline=True)
            embed.add_field(name="수마법", value=f"{player['water_magic']}", inline=True)
            embed.add_field(name="시야", value=f"{player['sight']}", inline=True)
            await interaction.followup.send(embed=embed)
        else:
            await interaction.followup.send("플레이어 정보를 찾을 수 없습니다.")

    @game_group.command(name="스킬포인트", description="보유한 스킬 포인트를 확인합니다.")
    async def skill_points(self, interaction: discord.Interaction):
        if not await self._check_game_channel_and_role(interaction): return
        await interaction.response.defer(ephemeral=True)

        from main import get_db_connection
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT skp FROM players WHERE user_id = ?", (interaction.user.id,))
        player = c.fetchone()
        conn.close()

        if player:
            skp = player['skp']
            await interaction.followup.send(f"현재 보유한 스킬 포인트는 {skp}점입니다.")
        else:
            await interaction.followup.send("플레이어 정보를 찾을 수 없습니다.")

async def setup(bot: commands.Bot):
    await bot.add_cog(GameCog(bot))