"""
commands/vote_commands.py
디스호스트 투표 보상 및 랭킹 시스템
"""

import discord
from discord import app_commands
from discord.ext import commands
import os
import json
from datetime import datetime, timedelta

from config import (
    COLOR_SUCCESS, COLOR_ERROR, COLOR_WARNING, COLOR_INFO,
    BOT_ICON_URL, KST, USERS_DIR,
    VOTE_REWARD_BASE, VOTE_STREAK_BONUS, VOTE_STREAK_MAX_BONUS,
    VOTE_MILESTONE_REWARDS,
)
from models.user import load_user_data, save_user_data
from utils.dishost_api import check_user_vote


class VoteCog(commands.Cog):
    """투표 보상 및 랭킹"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── 투표 데이터 헬퍼 ──
    @staticmethod
    def _get_vote_data(udata: dict) -> dict:
        if "vote" not in udata:
            udata["vote"] = {
                "total_count": 0,
                "streak": 0,
                "last_vote_date": None,
                "last_reward_date": None,
                "total_reward": 0,
                "milestones_claimed": [],
            }
        return udata["vote"]

    @staticmethod
    def _check_streak(vote_data: dict) -> int:
        """연속 투표 일수 계산. 어제 투표했으면 streak 유지, 아니면 1로 리셋"""
        last = vote_data.get("last_vote_date")
        if not last:
            return 1

        today = datetime.now(KST).date()
        try:
            last_date = datetime.fromisoformat(last).date()
        except (ValueError, TypeError):
            return 1

        diff = (today - last_date).days
        if diff == 1:
            return vote_data.get("streak", 0) + 1
        elif diff == 0:
            return vote_data.get("streak", 1)
        else:
            return 1

    # ── /투표보상 ──
    @app_commands.command(name="투표보상", description="디스호스트에서 투표 후 보상을 수령합니다.")
    async def vote_reward(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)

        uid = str(interaction.user.id)
        udata = load_user_data(uid)

        if not udata:
            return await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ 미등록",
                    description="`/가입`으로 먼저 계정을 생성해주세요.",
                    color=COLOR_ERROR,
                ),
            )

        # 디스호스트 투표 확인
        vote_result = await check_user_vote(interaction.user.id)

        if vote_result is None:
            return await interaction.followup.send(
                embed=discord.Embed(
                    title="⚠️ 확인 실패",
                    description="투표 상태를 확인할 수 없습니다. 잠시 후 다시 시도해주세요.",
                    color=COLOR_WARNING,
                ),
            )

        if not vote_result.get("voted", False):
            embed = discord.Embed(
                title="🗳️ 투표가 필요합니다",
                description=(
                    "아직 오늘 투표하지 않았습니다!\n\n"
                    "**[여기를 클릭하여 투표하기](https://list.dishost.kr/bots/1371722334213509250)**\n\n"
                    "투표 후 이 명령어를 다시 실행해주세요."
                ),
                color=COLOR_INFO,
            )
            embed.set_footer(text="투표는 하루에 한 번 가능합니다", icon_url=BOT_ICON_URL)
            return await interaction.followup.send(embed=embed)

        # 이미 오늘 보상을 받았는지 확인
        vote_data = self._get_vote_data(udata)
        today_str = datetime.now(KST).strftime("%Y-%m-%d")

        if vote_data.get("last_reward_date") == today_str:
            return await interaction.followup.send(
                embed=discord.Embed(
                    title="✅ 이미 수령 완료",
                    description=f"오늘의 투표 보상은 이미 받았습니다.\n연속 투표: **{vote_data.get('streak', 0)}일** | 누적: **{vote_data.get('total_count', 0)}회**",
                    color=COLOR_WARNING,
                ),
            )

        # 보상 계산
        streak = self._check_streak(vote_data)
        streak_bonus = min(streak * VOTE_STREAK_BONUS, VOTE_STREAK_MAX_BONUS)
        total_reward = VOTE_REWARD_BASE + streak_bonus

        # 마일스톤 체크
        new_total = vote_data.get("total_count", 0) + 1
        milestone_reward = 0
        milestone_label = None
        claimed = vote_data.get("milestones_claimed", [])

        for threshold, info in sorted(VOTE_MILESTONE_REWARDS.items()):
            if new_total >= threshold and threshold not in claimed:
                milestone_reward = info["gold"]
                milestone_label = info["label"]
                claimed.append(threshold)

        total_gold = total_reward + milestone_reward

        # 데이터 업데이트
        udata["gold"] = udata.get("gold", 0) + total_gold
        vote_data["total_count"] = new_total
        vote_data["streak"] = streak
        vote_data["last_vote_date"] = today_str
        vote_data["last_reward_date"] = today_str
        vote_data["total_reward"] = vote_data.get("total_reward", 0) + total_gold
        vote_data["milestones_claimed"] = claimed
        udata["vote"] = vote_data
        save_user_data(uid, udata)

        # 결과 임베드
        embed = discord.Embed(
            title="🎁 투표 보상 수령!",
            color=COLOR_SUCCESS,
            timestamp=datetime.now(KST),
        )
        embed.add_field(name="기본 보상", value=f"`{VOTE_REWARD_BASE:,}G`", inline=True)
        embed.add_field(name="연속 보너스", value=f"`+{streak_bonus:,}G` ({streak}일 연속)", inline=True)
        embed.add_field(name="합계", value=f"**`{total_reward:,}G`**", inline=True)

        if milestone_reward > 0:
            embed.add_field(
                name=f"🏆 마일스톤 달성! — {milestone_label}",
                value=f"추가 보상: **`+{milestone_reward:,}G`**",
                inline=False,
            )

        embed.add_field(name="현재 잔액", value=f"`{udata['gold']:,}G`", inline=True)
        embed.add_field(name="누적 투표", value=f"`{new_total}회`", inline=True)

        # 다음 마일스톤 안내
        next_milestone = None
        for threshold in sorted(VOTE_MILESTONE_REWARDS.keys()):
            if threshold > new_total:
                next_milestone = threshold
                break
        if next_milestone:
            remaining = next_milestone - new_total
            next_info = VOTE_MILESTONE_REWARDS[next_milestone]
            embed.set_footer(
                text=f"다음 마일스톤: {next_info['label']} ({remaining}회 남음)",
                icon_url=BOT_ICON_URL,
            )
        else:
            embed.set_footer(text="모든 마일스톤을 달성했습니다! 🎉", icon_url=BOT_ICON_URL)

        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        await interaction.followup.send(embed=embed)

    # ── /투표정보 ──
    @app_commands.command(name="투표정보", description="내 투표 현황을 확인합니다.")
    async def vote_info(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)

        uid = str(interaction.user.id)
        udata = load_user_data(uid)

        if not udata:
            return await interaction.followup.send(
                embed=discord.Embed(title="❌ 미등록", description="`/가입`으로 먼저 계정을 생성해주세요.", color=COLOR_ERROR),
            )

        vote_data = self._get_vote_data(udata)
        total = vote_data.get("total_count", 0)
        streak = vote_data.get("streak", 0)
        total_reward = vote_data.get("total_reward", 0)
        last_date = vote_data.get("last_reward_date", "없음")
        claimed = vote_data.get("milestones_claimed", [])

        # 마일스톤 진행도
        milestone_lines = []
        for threshold, info in sorted(VOTE_MILESTONE_REWARDS.items()):
            if threshold in claimed:
                milestone_lines.append(f"~~{info['label']} — {threshold}회~~  ✅")
            elif total < threshold:
                milestone_lines.append(f"{info['label']} — {threshold}회  (`{threshold - total}회 남음`)")
            else:
                milestone_lines.append(f"{info['label']} — {threshold}회  🔓 `/투표보상`으로 수령")

        embed = discord.Embed(
            title="🗳️ 투표 현황",
            color=COLOR_INFO,
            timestamp=datetime.now(KST),
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.add_field(name="누적 투표", value=f"`{total}회`", inline=True)
        embed.add_field(name="연속 투표", value=f"`{streak}일`", inline=True)
        embed.add_field(name="누적 보상", value=f"`{total_reward:,}G`", inline=True)
        embed.add_field(name="마지막 수령", value=f"`{last_date}`", inline=True)
        embed.add_field(
            name="📊 마일스톤",
            value="\n".join(milestone_lines) if milestone_lines else "없음",
            inline=False,
        )
        embed.set_footer(text="매일 투표하여 연속 보너스를 받으세요!", icon_url=BOT_ICON_URL)

        await interaction.followup.send(embed=embed)

    # ── /랭킹 ──
    @app_commands.command(name="랭킹", description="서버 랭킹을 확인합니다.")
    @app_commands.describe(종류="랭킹 종류를 선택하세요")
    @app_commands.choices(종류=[
        app_commands.Choice(name="💰 골드", value="gold"),
        app_commands.Choice(name="⚔️ 레벨", value="level"),
        app_commands.Choice(name="🐱 냥이 수", value="cats"),
        app_commands.Choice(name="🗳️ 투표", value="vote"),
    ])
    async def ranking(self, interaction: discord.Interaction, 종류: app_commands.Choice[str]):
        await interaction.response.defer(ephemeral=False)

        if not os.path.isdir(USERS_DIR):
            return await interaction.followup.send(
                embed=discord.Embed(title="❌ 데이터 없음", color=COLOR_ERROR),
            )

        # 전체 유저 데이터 로드
        users = []
        for filename in os.listdir(USERS_DIR):
            if not filename.endswith(".json"):
                continue
            uid = filename.replace(".json", "")
            try:
                filepath = os.path.join(USERS_DIR, filename)
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                users.append((uid, data))
            except Exception:
                continue

        if not users:
            return await interaction.followup.send(
                embed=discord.Embed(title="❌ 등록된 유저가 없습니다.", color=COLOR_ERROR),
            )

        # 정렬 기준
        category = 종류.value
        if category == "gold":
            users.sort(key=lambda x: x[1].get("gold", 0), reverse=True)
            title = "💰 골드 랭킹"
            value_fn = lambda d: f"`{d.get('gold', 0):,}G`"
        elif category == "level":
            users.sort(key=lambda x: (x[1].get("level", 1), x[1].get("exp", 0)), reverse=True)
            title = "⚔️ 레벨 랭킹"
            value_fn = lambda d: f"Lv.`{d.get('level', 1)}` (EXP: `{d.get('exp', 0):,}`)"
        elif category == "cats":
            users.sort(key=lambda x: len(x[1].get("cats", [])), reverse=True)
            title = "🐱 냥이 수 랭킹"
            value_fn = lambda d: f"`{len(d.get('cats', []))}` 마리"
        elif category == "vote":
            users.sort(key=lambda x: x[1].get("vote", {}).get("total_count", 0), reverse=True)
            title = "🗳️ 투표 랭킹"
            value_fn = lambda d: f"`{d.get('vote', {}).get('total_count', 0)}` 회 (연속 {d.get('vote', {}).get('streak', 0)}일)"
        else:
            return

        # 상위 15명
        top = users[:15]
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}
        lines = []
        my_rank = None

        for i, (uid, data) in enumerate(users, 1):
            if uid == str(interaction.user.id):
                my_rank = i
                break

        for i, (uid, data) in enumerate(top, 1):
            rank_icon = medal.get(i, f"`{i}.`")
            name = data.get("nickname") or data.get("username") or uid

            # 현재 유저 하이라이트
            if uid == str(interaction.user.id):
                lines.append(f"{rank_icon} **▸ {name}** — {value_fn(data)}")
            else:
                lines.append(f"{rank_icon} {name} — {value_fn(data)}")

        desc = "\n".join(lines)

        # 내 순위가 15위 밖이면 하단에 표시
        if my_rank and my_rank > 15:
            my_data = next((d for u, d in users if u == str(interaction.user.id)), None)
            if my_data:
                my_name = my_data.get("nickname") or my_data.get("username") or str(interaction.user.id)
                desc += f"\n\n─────────────\n`{my_rank}.` **▸ {my_name}** — {value_fn(my_data)}"

        embed = discord.Embed(
            title=title,
            description=desc,
            color=COLOR_SUCCESS,
            timestamp=datetime.now(KST),
        )
        embed.set_footer(
            text=f"전체 {len(users)}명 중 내 순위: {my_rank or '?'}위",
            icon_url=BOT_ICON_URL,
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url if self.bot.user else None)

        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(VoteCog(bot))
