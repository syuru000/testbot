import discord
from discord.ext import commands
from discord import app_commands

# main.py에서 필요한 함수나 변수를 가져오기 위한 import
# 순환 참조를 피하기 위해 타입 체킹 중에만 사용하거나 함수 내에서 import합니다.
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from main import get_db_connection, update_chat_log, update_game_status

class AdminCog(commands.Cog):
    # 그룹을 Cog 클래스의 속성으로 정의합니다.
    admin_group = app_commands.Group(name="관리자", description="관리자용 명령어입니다.", default_permissions=discord.Permissions(administrator=True))

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # __init__에서 수동으로 그룹을 추가할 필요가 없습니다. Cog가 로드될 때 자동으로 처리됩니다.

    @admin_group.command(name="게임시작", description="게임 시스템을 설정합니다.")
    async def start_game(self, interaction: discord.Interaction):
        from main import get_db_connection, update_chat_log, update_game_status

        if interaction.channel_id != self.bot.game_channel_id:
            await interaction.response.send_message("게임 채널에서만 사용 가능합니다.", ephemeral=True)
            return
        await interaction.response.send_message("게임 시스템을 초기화합니다...", ephemeral=True)
        self.bot.chat_history.clear()
        temp_chat_msg = await interaction.channel.send("채팅창 초기화 중...")
        temp_status_msg = await interaction.channel.send("상태창 초기화 중...")
        
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("UPDATE game_state SET chat_message_id = ?, status_message_id = ? WHERE id = 1", (temp_chat_msg.id, temp_status_msg.id))
        c.execute("DELETE FROM chat_logs")
        conn.commit()
        conn.close()
        
        self.bot.chat_log_message = temp_chat_msg
        self.bot.game_status_message = temp_status_msg
        await update_chat_log(self.bot) # bot 객체를 전달하도록 수정
        await update_game_status(self.bot) # bot 객체를 전달하도록 수정
        print(f"게임 시스템이 채널 ID {interaction.channel.id} 에서 시작되었습니다.")

    @admin_group.command(name="공지", description="지정된 채널에 공지를 보냅니다.")
    @app_commands.describe(
        option="옵션 (-a: 전체 채널, -c: 현재 채널)",
        content="공지 내용"
    )
    @app_commands.choices(option=[
        app_commands.Choice(name="전체", value="-a"),
        app_commands.Choice(name="현재", value="-c"),
    ])
    async def notice(self, interaction: discord.Interaction, option: str, content: str):
        if interaction.channel_id not in [self.bot.login_channel_id, self.bot.game_channel_id]:
            await interaction.response.send_message("공지사항은 로그인 또는 게임 채널에서만 사용할 수 있습니다.", ephemeral=True)
            return

        embed = discord.Embed(title="📢 공지사항", description=content, color=discord.Color.orange())
        embed.set_footer(text=f"발신자: {interaction.user.display_name}")

        if option == '-a':
            try:
                login_channel = self.bot.get_channel(self.bot.login_channel_id) or await self.bot.fetch_channel(self.bot.login_channel_id)
                game_channel = self.bot.get_channel(self.bot.game_channel_id) or await self.bot.fetch_channel(self.bot.game_channel_id)
                
                await login_channel.send(embed=embed)
                if login_channel.id != game_channel.id:
                    await game_channel.send(embed=embed)
                    
                await interaction.response.send_message("로그인 및 게임 채널에 공지를 보냈습니다.", ephemeral=True)
            except discord.NotFound:
                await interaction.response.send_message("오류: 설정된 채널 중 일부를 찾을 수 없습니다.", ephemeral=True)
            except discord.Forbidden:
                await interaction.response.send_message("오류: 채널에 메시지를 보낼 권한이 없습니다.", ephemeral=True)

        elif option == '-c':
            try:
                await interaction.channel.send(embed=embed)
                await interaction.response.send_message("현재 채널에 공지를 보냈습니다.", ephemeral=True)
            except discord.Forbidden:
                await interaction.response.send_message("오류: 이 채널에 메시지를 보낼 권한이 없습니다.", ephemeral=True)

    @admin_group.command(name="명령어새로고침", description="봇의 슬래시 명령어를 다시 동기화합니다.")
    async def reload_commands(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            synced = await self.bot.tree.sync(guild=interaction.guild)
            await interaction.followup.send(f"{len(synced)}개의 명령어를 성공적으로 새로고침했습니다.")
            print(f"{interaction.guild.name}(ID: {interaction.guild.id}) 서버의 명령어를 새로고침했습니다.")
        except Exception as e:
            await interaction.followup.send(f"명령어 새로고침 중 오류가 발생했습니다: {e}")
            print(f"명령어 동기화 오류: {e}")

async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
