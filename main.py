import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import sqlite3
import asyncio
from collections import deque
from werkzeug.security import generate_password_hash, check_password_hash
from discord.ui import Modal, TextInput
from database import setup_database
from flask import Flask
from threading import Thread
import os # os 모듈 추가

# --- 웹 서버 설정 (24시간 호스팅용) ---
app = Flask('')

@app.route('/', methods=['GET', 'HEAD'])
def home():
    return "The bot is alive!"

def run_web_server():
    app.run(host='0.0.0.0', port=8080)

def start_web_server():
    t = Thread(target=run_web_server)
    t.daemon = True
    t.start()

# --- 설정 로드 (Replit Secrets 우선) ---
TOKEN = os.environ.get('TOKEN')
GAME_CHANNEL_ID = os.environ.get('GAME_CHANNEL_ID')
LOGIN_CHANNEL_ID = os.environ.get('LOGIN_CHANNEL_ID')
NO_PARTICIPANT_ROLE_ID = os.environ.get('NO_PARTICIPANT_ROLE_ID')
PARTICIPANT_ROLE_ID = os.environ.get('PARTICIPANT_ROLE_ID')
WIND_CHANNEL_ID = os.environ.get('WIND_CHANNEL_ID')
ICE_CHANNEL_ID = os.environ.get('ICE_CHANNEL_ID')
CHANNEL_1_ROLE_ID = os.environ.get('CHANNEL_1_ROLE_ID')
CHANNEL_2_ROLE_ID = os.environ.get('CHANNEL_2_ROLE_ID')

# 환경 변수(Secrets)에 토큰이 없으면 config.json에서 로드 (로컬 환경용)
if not TOKEN:
    print("환경 변수를 찾을 수 없어 config.json에서 설정을 로드합니다.")
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
        TOKEN = config.get('TOKEN')
        GAME_CHANNEL_ID = config.get('GAME_CHANNEL_ID')
        LOGIN_CHANNEL_ID = config.get('LOGIN_CHANNEL_ID')
        NO_PARTICIPANT_ROLE_ID = config.get('NO_PARTICIPANT_ROLE_ID')
        PARTICIPANT_ROLE_ID = config.get('PARTICIPANT_ROLE_ID')
        WIND_CHANNEL_ID = config.get('WIND_CHANNEL_ID')
        ICE_CHANNEL_ID = config.get('ICE_CHANNEL_ID')
        CHANNEL_1_ROLE_ID = config.get('CHANNEL_1_ROLE_ID')
        CHANNEL_2_ROLE_ID = config.get('CHANNEL_2_ROLE_ID')
    except (FileNotFoundError, KeyError) as e:
        print(f"치명적 오류: 환경 변수와 config.json 파일 모두에 설정이 없습니다. ({e})")
        exit()

# ID 값들을 정수형으로 변환
try:
    GAME_CHANNEL_ID = int(GAME_CHANNEL_ID)
    LOGIN_CHANNEL_ID = int(LOGIN_CHANNEL_ID)
    NO_PARTICIPANT_ROLE_ID = int(NO_PARTICIPANT_ROLE_ID)
    PARTICIPANT_ROLE_ID = int(PARTICIPANT_ROLE_ID)
    WIND_CHANNEL_ID = int(WIND_CHANNEL_ID)
    ICE_CHANNEL_ID = int(ICE_CHANNEL_ID)
    CHANNEL_1_ROLE_ID = int(CHANNEL_1_ROLE_ID)
    CHANNEL_2_ROLE_ID = int(CHANNEL_2_ROLE_ID)
except (ValueError, TypeError):
    print("치명적 오류: ID 값 중 하나가 올바른 숫자가 아닙니다.")
    exit()


# --- 봇 설정 ---
intents = discord.Intents.default()
intents.members = True
intents.messages = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- 설정값을 bot 객체에 저장 ---
bot.game_channel_id = GAME_CHANNEL_ID
bot.login_channel_id = LOGIN_CHANNEL_ID
bot.wind_channel_id = WIND_CHANNEL_ID
bot.ice_channel_id = ICE_CHANNEL_ID
bot.channel_1_role_id = CHANNEL_1_ROLE_ID
bot.channel_2_role_id = CHANNEL_2_ROLE_ID

# --- 상태 변수 ---
bot.chat_log_message = None
bot.game_status_message = None
bot.chat_history = deque(maxlen=10)
bot.chat_lock = asyncio.Lock()

# --- DB 헬퍼 ---
def get_db_connection():
    # timeout을 15초로 늘려 DB 잠금 오류를 줄입니다.
    conn = sqlite3.connect('game.db', timeout=15)
    # WAL 모드를 활성화하여 동시성(concurrency)을 높입니다.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn

# --- UI (Modals, Views) ---
class RegistrationModal(Modal, title="회원가입"):
    login_id = TextInput(label="사용할 아이디", placeholder="로그인 시 사용할 ID")
    password = TextInput(label="비밀번호")

    async def on_submit(self, interaction: discord.Interaction):
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM players WHERE login_id = ?", (self.login_id.value,))
        if c.fetchone():
            await interaction.response.send_message("이미 사용 중인 아이디입니다.", ephemeral=True)
        else:
            hashed_password = generate_password_hash(self.password.value)
            c.execute("INSERT INTO players (user_id, login_id, password_hash) VALUES (?, ?, ?)",
                      (interaction.user.id, self.login_id.value, hashed_password))
            conn.commit()
            await interaction.response.send_message("회원가입 완료! `/로그인`으로 접속해주세요.", ephemeral=True)
        conn.close()

class NicknameButtonView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=180)
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("이 버튼은 당신을 위한 것이 아닙니다.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="닉네임 설정", style=discord.ButtonStyle.primary)
    async def set_nickname(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(NicknameModal(user_id=self.author_id, original_message=interaction.message))

class LoginModal(Modal, title="로그인"):
    login_id = TextInput(label="아이디")
    password = TextInput(label="비밀번호")

    async def on_submit(self, interaction: discord.Interaction):
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM players WHERE login_id = ?", (self.login_id.value,))
        player = c.fetchone()
        conn.close()

        if player and check_password_hash(player['password_hash'], self.password.value):
            if player['nickname']:
                await handle_login_success(interaction, player, interaction.guild)
            else:
                view = NicknameButtonView(author_id=interaction.user.id)
                await interaction.response.send_message(
                    f"{interaction.user.mention}, 로그인 성공! 게임을 시작하려면 닉네임을 설정해야 합니다.",
                    view=view, ephemeral=True
                )
        else:
            await interaction.response.send_message("아이디 또는 비밀번호가 일치하지 않습니다.", ephemeral=True)

class NicknameModal(Modal, title="닉네임 설정"):
    def __init__(self, user_id: int, original_message: discord.Message):
        super().__init__()
        self.user_id = user_id
        self.original_message = original_message

    nickname = TextInput(label="게임에서 사용할 닉네임", min_length=2, max_length=15)

    async def on_submit(self, interaction: discord.Interaction):
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM players WHERE nickname = ?", (self.nickname.value,))
        if c.fetchone():
            await interaction.response.send_message("이미 사용 중인 닉네임입니다.", ephemeral=True)
            conn.close()
            return
        
        c.execute("UPDATE players SET nickname = ? WHERE user_id = ?", (self.nickname.value, self.user_id))
        conn.commit()
        c.execute("SELECT * FROM players WHERE user_id = ?", (self.user_id,))
        player = c.fetchone()
        conn.close()
        await handle_login_success(interaction, player, interaction.guild, self.original_message)

# --- 로그인 성공 처리 ---
async def handle_login_success(interaction: discord.Interaction, player_data, guild: discord.Guild, message_to_edit: discord.Message = None):
    try:
        member = await guild.fetch_member(interaction.user.id)
        no_participant_role = guild.get_role(NO_PARTICIPANT_ROLE_ID)
        participant_role = guild.get_role(PARTICIPANT_ROLE_ID)

        if no_participant_role: await member.remove_roles(no_participant_role, reason="게임 참가")
        if participant_role: await member.add_roles(participant_role, reason="게임 참가")
        
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("UPDATE players SET current_location_id = 1 WHERE user_id = ?", (interaction.user.id,))
        conn.commit()
        conn.close()

        response_message = f"{player_data['nickname']}님, 환영합니다!"
        if message_to_edit and not interaction.response.is_done(): # 이미 응답된 상호작용이 아닌 경우에만 메시지 수정 시도
            try:
                await message_to_edit.edit(content=f"{member.mention}님의 닉네임 설정이 완료되었습니다.", view=None)
            except discord.NotFound:
                print("원래 메시지를 찾을 수 없습니다. 이미 삭제되었거나 만료되었을 수 있습니다.")
            except Exception as e:
                print(f"메시지 수정 중 오류 발생: {e}")
        
        if not interaction.response.is_done(): # 아직 응답하지 않은 경우에만 응답
            await interaction.response.send_message(response_message, ephemeral=True)
        else:
            await interaction.followup.send(response_message, ephemeral=True)

    except Exception as e:
        print(f"역할 변경 또는 메시지 수정 오류: {e}")
        if not interaction.response.is_done():
            await interaction.response.send_message("처리 중 오류가 발생했습니다.", ephemeral=True)

# --- 헬퍼 함수: 임베드 업데이트 ---
async def update_chat_log(bot_instance):
    if not bot_instance.chat_log_message: return
    embed = discord.Embed(title="채팅창", description='\n'.join(bot_instance.chat_history) or "대화가 없습니다.", color=discord.Color.blue())
    try: await bot_instance.chat_log_message.edit(embed=embed)
    except discord.NotFound: print("채팅 로그 메시지를 찾을 수 없습니다.")

async def update_game_status(bot_instance, content="게임 상태 정보", title="게임 정보"):
    if not bot_instance.game_status_message: return
    embed = discord.Embed(title=title, description=content, color=discord.Color.gold())
    try: await bot_instance.game_status_message.edit(embed=embed)
    except discord.NotFound: print("게임 상태 메시지를 찾을 수 없습니다.")

# --- 백그라운드 작업 ---
@tasks.loop(seconds=60)
async def update_server_status():
    await bot.wait_until_ready()
    wind_channel = bot.get_channel(WIND_CHANNEL_ID)
    ice_channel = bot.get_channel(ICE_CHANNEL_ID)

    if not wind_channel or not ice_channel:
        # 봇이 준비되는 동안 채널을 못찾을 수 있으므로, 오류 대신 로그만 남김
        # print("Wind 또는 Ice 채널을 찾을 수 없습니다. config.json을 확인하세요.")
        return

    wind_members = len(wind_channel.members)
    ice_members = len(ice_channel.members)

    status_content = f"**Wind 채널:** {wind_members}명 접속 중\n"
    status_content += f"**Ice 채널:** {ice_members}명 접속 중"
    
    await update_game_status(bot, content=status_content, title="서버 현황")

# --- 이벤트 핸들러 ---
@bot.event
async def on_ready():
    print(f'{bot.user}에 로그인하였습니다!')
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT chat_message_id, status_message_id FROM game_state WHERE id = 1")
    state = c.fetchone()
    if state and state['chat_message_id']:
        try:
            game_channel = bot.get_channel(GAME_CHANNEL_ID) or await bot.fetch_channel(GAME_CHANNEL_ID)
            bot.chat_log_message = await game_channel.fetch_message(state['chat_message_id'])
            bot.game_status_message = await game_channel.fetch_message(state['status_message_id'])
            c.execute("SELECT message FROM chat_logs ORDER BY timestamp DESC LIMIT 10")
            logs = c.fetchall()
            bot.chat_history.extendleft([log['message'] for log in logs])
            await update_chat_log(bot)
            print("게임 상태가 복구되었습니다.")
        except Exception as e:
            print(f"메시지 복구 실패: {e}")
    conn.close()

    print("Cog 로드를 시작합니다...")
    for cog_name in ["admin_cog", "game_cog"]:
        try:
            await bot.load_extension(cog_name)
            print(f"{cog_name}가 성공적으로 로드되었습니다.")
        except Exception as e:
            print(f"Cog '{cog_name}' 로드 중 오류 발생: {e}")

    print("명령어 동기화를 시작합니다...")
    try:
        synced = await bot.tree.sync()
        print(f"{len(synced)}개의 명령어가 동기화되었습니다.")
    except Exception as e:
        print(f"명령어 동기화 중 오류 발생: {e}")
        
    if not update_server_status.is_running():
        update_server_status.start()

    print("봇이 준비되었습니다.")

@bot.event
async def on_message(message):
    if message.author == bot.user: return
    if message.channel.id in [LOGIN_CHANNEL_ID, GAME_CHANNEL_ID] and not message.content.startswith('/'):
        try: await message.delete()
        except (discord.Forbidden, discord.NotFound): pass

# --- 일반 명령어들 ---
@bot.tree.command(name="회원가입", description="계정을 생성합니다.")
async def register_command(interaction: discord.Interaction):
    if interaction.channel_id != LOGIN_CHANNEL_ID:
        return await interaction.response.send_message("이 명령어는 로그인 채널에서만 사용할 수 있습니다.", ephemeral=True)
    await interaction.response.send_modal(RegistrationModal())

@bot.tree.command(name="로그인", description="게임에 접속합니다.")
async def login_command(interaction: discord.Interaction):
    if interaction.channel_id != LOGIN_CHANNEL_ID:
        return await interaction.response.send_message("이 명령어는 로그인 채널에서만 사용할 수 있습니다.", ephemeral=True)
    await interaction.response.send_modal(LoginModal())

@bot.tree.command(name="내정보", description="자신의 캐릭터 정보를 표시합니다.")
async def profile(interaction: discord.Interaction):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT p.*, l.name as location_name FROM players p JOIN locations l ON p.current_location_id = l.id WHERE p.user_id = ?", (interaction.user.id,))
    player = c.fetchone()
    conn.close()

    if player:
        info_text = (
            f"**닉네임:** {player['nickname']}\n"
            f"**직업:** {player['job']}\n"
            f"**레벨:** {player['level']} (EXP: {player['exp']})\n"
            f"**HP:** {player['hp']} / **MP:** {player['mp']}\n"
            f"**골드:** {player['gold']}\n"
            f"**현재 위치:** {player['location_name']}"
        )
        await interaction.response.send_message(info_text, ephemeral=True)
    else:
        await interaction.response.send_message("플레이어 정보가 없습니다. 먼저 `/회원가입`과 `/로그인`을 진행해주세요.", ephemeral=True)


@bot.tree.command(name="말하기", description="채팅창에 메시지를 보냅니다.")
@app_commands.describe(message="보낼 메시지")
async def say(interaction: discord.Interaction, message: str):
    if interaction.channel_id != GAME_CHANNEL_ID:
        return await interaction.response.send_message("이 명령어는 게임 채널에서만 사용할 수 있습니다.", ephemeral=True)
    
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT nickname FROM players WHERE user_id = ?", (interaction.user.id,))
    player = c.fetchone()
    
    if not player or not player['nickname']:
        conn.close()
        return await interaction.response.send_message("채팅을 하기 전에 먼저 로그인하여 닉네임을 설정해야 합니다.", ephemeral=True)

    game_nickname = player['nickname']
    await interaction.response.send_message("메시지를 보내는 중...", ephemeral=True, delete_after=1)
    
    async with bot.chat_lock:
        formatted_message = f"**{game_nickname}**: {message}"
        bot.chat_history.append(formatted_message)
        c.execute("INSERT INTO chat_logs (message) VALUES (?)", (formatted_message,))
        c.execute("DELETE FROM chat_logs WHERE id NOT IN (SELECT id FROM chat_logs ORDER BY timestamp DESC LIMIT 10)")
        conn.commit()
        await update_chat_log(bot)
        
    conn.close()

# --- 봇 실행 ---
if __name__ == '__main__':
    if any(val == 0 for val in [GAME_CHANNEL_ID, LOGIN_CHANNEL_ID, NO_PARTICIPANT_ROLE_ID, PARTICIPANT_ROLE_ID]):
        print("!!! config.json 파일의 ID 값들이 올바르게 설정되었는지 확인해주세요 !!!")
    else:
        setup_database()
        start_web_server()  # 웹 서버 시작
        bot.run(TOKEN)