# commands/labyrinth_commands.py
"""
미궁(래버린스) 커맨드 Cog - Balance v2
- /미궁: 무한 미궁 도전
- /미궁기록: 미궁 통계
- 일일 제한, 안티치트, 업적 연동
"""

import discord
from discord import app_commands
from discord.ext import commands
import json
from utils.cooldown_lock import acquire_lock, release_lock, build_locked_embed


from config import (
    COLOR_PRIMARY, COLOR_SUCCESS, COLOR_ERROR, COLOR_WARNING,
    DAILY_LIMITS, BOT_ICON_URL, CATS_FILE,
    SKILL_TREE_COMBAT, SKILL_TREE_TRADE, RARITY_TIERS
)
from models.user import (
    load_user_data, save_user_data,
    add_exp, get_skill_effect,
    check_daily_limit, increment_daily_count,
    is_newbie, check_and_grant_achievements,
    apply_money_reward, advance_tutorial,
    get_active_buff_value, consume_next_use_buff
)
from systems.labyrinth import run_labyrinth_sequence, apply_labyrinth_rewards
from systems.anticheat import run_anticheat_checks
from utils.checks import is_registered, is_not_banned


# 동시 실행 방지
_labyrinth_processing: dict[int, bool] = {}


def load_cats_data() -> list:
    """cats.json 로드"""
    try:
        with open(CATS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data.get("cats", [])
            return data
    except Exception:
        return []


def get_cat_by_id(cats_data: list, cat_id: str) -> dict | None:
    """ID로 냥이 데이터 찾기"""
    for cat in cats_data:
        if str(cat.get("id", cat.get("name", ""))) == cat_id:
            return cat
    return None


# ============================================================
# 임베드 빌더
# ============================================================

def build_labyrinth_record_embed(user_data: dict, member: discord.Member) -> discord.Embed:
    """미궁 기록 임베드"""
    stats = user_data.get("stats", {})
    labyrinth_stats = user_data.get("labyrinth_stats", {})

    total_runs = labyrinth_stats.get("total_runs", stats.get("labyrinth_runs", 0))
    best_floor = labyrinth_stats.get("highest_floor", stats.get("labyrinth_best_floor", 0))
    total_floors = labyrinth_stats.get("total_floors_cleared", stats.get("labyrinth_total_floors", 0))
    total_rewards_money = labyrinth_stats.get("total_money_earned", stats.get("labyrinth_total_money", 0))
    total_rewards_exp = labyrinth_stats.get("total_exp_earned", stats.get("labyrinth_total_exp", 0))

    embed = discord.Embed(
        title=f"🏛️ {member.display_name}의 미궁 기록",
        color=COLOR_PRIMARY
    )

    embed.add_field(
        name="📊 전적",
        value=(
            f"총 도전: **{total_runs}회**\n"
            f"최고 층: **{best_floor}층**\n"
            f"총 돌파 층수: **{total_floors}층**"
        ),
        inline=True
    )

    embed.add_field(
        name="💰 누적 보상",
        value=(
            f"💵 총 획득금: **{total_rewards_money:,}원**\n"
            f"✨ 총 경험치: **{total_rewards_exp:,} EXP**"
        ),
        inline=True
    )

    # 전투/교역 스킬 보너스
    combat_power = get_skill_effect(user_data, "combat", "battle_power_bonus")
    combat_hp = get_skill_effect(user_data, "combat", "battle_hp_bonus")
    trade_bonus = get_skill_effect(user_data, "trade", "sell_price_bonus")

    embed.add_field(
        name="🔧 적용 스킬",
        value=(
            f"⚔️ 전투력 보너스: **+{combat_power}%**\n"
            f"❤️ 체력 보너스: **+{combat_hp}%**\n"
            f"💼 보상 보너스: **+{trade_bonus}%**"
        ),
        inline=False
    )

    # 일일 현황
    daily = user_data.get("daily_counts", {})
    lab_today = daily.get("labyrinth", 0)
    lab_limit = DAILY_LIMITS.get("labyrinth", 5)

    embed.add_field(
        name="📅 오늘 도전",
        value=f"**{lab_today}/{lab_limit}회**",
        inline=False
    )

    embed.set_footer(text="더 깊이 탐험하세요!", icon_url=BOT_ICON_URL)
    return embed


def build_labyrinth_intro_embed(user_data: dict) -> discord.Embed:
    """미궁 도전 시작 임베드"""
    level = user_data.get("level", 1)
    best_floor = user_data.get("labyrinth_stats", {}).get(
        "highest_floor",
        user_data.get("stats", {}).get("labyrinth_best_floor", 0)
    )

    daily = user_data.get("daily_counts", {})
    lab_today = daily.get("labyrinth", 0)
    lab_limit = DAILY_LIMITS.get("labyrinth", 5)

    # ★ 보유 냥이 안전 카운트
    owned_cats = user_data.get("cats", user_data.get("owned_cats", {}))
    total_species = 0
    if isinstance(owned_cats, dict):
        for cat_key, cat_val in owned_cats.items():
            if isinstance(cat_val, dict):
                try:
                    count = int(cat_val.get("count", 0))
                except (ValueError, TypeError):
                    count = 1
            elif isinstance(cat_val, (int, float)):
                count = int(cat_val)
            elif isinstance(cat_val, str):
                try:
                    count = int(cat_val)
                except ValueError:
                    count = 1  # "common" 같은 문자열 → 1마리로 간주
            else:
                count = 1
            if count > 0:
                total_species += 1
    elif isinstance(owned_cats, list):
        total_species = len(owned_cats)

    embed = discord.Embed(
        title="🏛️ 무한 미궁",
        description=(
            "끝없는 미궁에 도전하세요!\n"
            "층을 올라갈수록 적이 강해지지만 보상도 커집니다.\n"
            "패배하면 해당 층까지의 보상만 획득합니다."
        ),
        color=COLOR_PRIMARY
    )

    embed.add_field(
        name="📋 현재 상태",
        value=(
            f"Lv.**{level}** | 보유 냥이: **{total_species}종**\n"
            f"최고 기록: **{best_floor}층**\n"
            f"오늘 도전: **{lab_today}/{lab_limit}회**"
        ),
        inline=False
    )

    if is_newbie(user_data):
        embed.add_field(
            name="🌱 뉴비 보호",
            value="패배 페널티가 면제됩니다!",
            inline=False
        )

    embed.set_footer(text="아래 버튼을 눌러 도전을 시작하세요!", icon_url=BOT_ICON_URL)
    return embed



# ============================================================
# 미궁 시작 뷰
# ============================================================

class LabyrinthStartView(discord.ui.View):
    """미궁 도전 시작 뷰"""

    def __init__(self, user_id: int):
        super().__init__(timeout=60)
        self.user_id = user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ 본인만 사용 가능합니다.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="도전 시작!", emoji="⚔️", style=discord.ButtonStyle.danger)
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 버튼 비활성화
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)

        user_data = load_user_data(str(self.user_id))

        # ★ 보유 냥이 안전 체크
        owned_cats = user_data.get("cats", user_data.get("owned_cats", {}))
        has_cats = False

        if isinstance(owned_cats, dict):
            for cat_key, cat_val in owned_cats.items():
                if isinstance(cat_val, dict):
                    count = cat_val.get("count", 0)
                    try:
                        count = int(count)
                    except (ValueError, TypeError):
                        count = 1
                elif isinstance(cat_val, (int, float)):
                    count = int(cat_val)
                elif isinstance(cat_val, str):
                    try:
                        count = int(cat_val)
                    except ValueError:
                        count = 1  # 문자열이면 1마리로 간주
                else:
                    count = 1

                if count > 0:
                    has_cats = True
                    break
        elif isinstance(owned_cats, list):
            has_cats = len(owned_cats) > 0

        if not has_cats:
            embed = discord.Embed(
                title="❌ 도전 불가",
                description="전투에 참여시킬 냥이가 없습니다!\n`/납치`로 먼저 냥이를 모아주세요.",
                color=COLOR_ERROR
            )
            await interaction.followup.send(embed=embed)
            self.stop()
            return

        # 미궁 시퀀스 실행
        try:
            run_data = await run_labyrinth_sequence(
                interaction=interaction,
                user_data=user_data
            )

            if run_data is None:
                embed = discord.Embed(
                    title="❌ 도전 불가",
                    description="출전할 수 있는 냥이가 없습니다!\n`/납치`로 먼저 냥이를 모아주세요.",
                    color=COLOR_ERROR
                )
                await interaction.followup.send(embed=embed)
                self.stop()
                return

            # 일일 카운트
            increment_daily_count(user_data, "labyrinth")

            # 보상 적용
            reward_summary = apply_labyrinth_rewards(user_data, run_data)

            # 경험치 적용
            exp_reward = reward_summary.get("exp", 0)
            if exp_reward > 0:
                exp_result = add_exp(user_data, exp_reward, apply_catchup=True, apply_buffs=True)
                consume_next_use_buff(user_data, "exp_boost")
                consume_next_use_buff(user_data, "money_boost")
            else:
                exp_result = {"leveled_up": False}

            save_user_data(str(self.user_id), user_data)

            # 결과 임베드
            from systems.labyrinth import build_labyrinth_result_embed
            result_embed = build_labyrinth_result_embed(
                interaction.user.display_name,
                reward_summary,
                run_data
            )

            if exp_reward > 0 and exp_result.get("leveled_up"):
                result_embed.add_field(
                    name="📈 레벨 업!",
                    value=f"Lv.{exp_result['old_level']} → Lv.{exp_result['new_level']}",
                    inline=True
                )

            result_embed.set_footer(
                text=f"잔여 도전: {DAILY_LIMITS.get('labyrinth', 5) - user_data.get('daily_counts', {}).get('labyrinth', 0)}회",
                icon_url=BOT_ICON_URL
            )

            await interaction.followup.send(embed=result_embed)

            # 업적 체크
            new_achievements = check_and_grant_achievements(user_data)
            if new_achievements:
                save_user_data(str(self.user_id), user_data)
                ach_text = "\n".join([
                    f"🏆 **{a.get('name', '?') if isinstance(a, dict) else str(a)}** 달성!"
                    for a in new_achievements
                ])
                ach_embed = discord.Embed(
                    title="🏆 업적 달성!",
                    description=ach_text,
                    color=COLOR_SUCCESS
                )
                await interaction.followup.send(embed=ach_embed)

            # 튜토리얼
            tutorial_step = user_data.get("tutorial_step", "complete")
            if tutorial_step == "first_labyrinth":
                advance_tutorial(user_data, "first_labyrinth")
                save_user_data(str(self.user_id), user_data)
            elif tutorial_step == "level_up" and user_data.get("level", 1) >= 2:
                advance_tutorial(user_data, "level_up")
                save_user_data(str(self.user_id), user_data)

        except Exception as e:
            embed = discord.Embed(
                title="❌ 미궁 오류",
                description=f"미궁 탐험 중 오류가 발생했습니다.\n`{str(e)[:200]}`",
                color=COLOR_ERROR
            )
            try:
                await interaction.followup.send(embed=embed)
            except Exception:
                pass

        self.stop()

    @discord.ui.button(label="취소", emoji="❌", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="↩️ 미궁 취소",
            description="미궁 도전을 취소했습니다.",
            color=COLOR_WARNING
        )
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        self.stop()

# ============================================================
# Cog 정의
# ============================================================

class LabyrinthCog(commands.Cog):
    """미궁 관련 명령어"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---- /미궁 ----
    @app_commands.command(name="미궁", description="무한 미궁에 도전합니다.")
    @is_registered()
    @is_not_banned()
    async def labyrinth_command(self, interaction: discord.Interaction):
        user_id = interaction.user.id

        if not acquire_lock(user_id, "labyrinth"):
            await interaction.response.send_message(
                embed=build_locked_embed(user_id), ephemeral=True
            )
            return

        try:
            # ★ 즉시 defer → 3초 제한 해제
            await interaction.response.defer()

            # 안티치트
            await run_anticheat_checks(
                user_id=interaction.user.id,
                username=interaction.user.display_name,
                interaction=interaction,
                check_type="command",
            )

            user_data = load_user_data(str(user_id))

            # 레벨 체크 (최소 Lv.5)
            if user_data.get("level", 1) < 5:
                embed = discord.Embed(
                    title="🔒 레벨 부족",
                    description=(
                        "미궁은 Lv.**5** 이상부터 도전 가능합니다.\n"
                        f"현재 레벨: Lv.**{user_data.get('level', 1)}**"
                    ),
                    color=COLOR_ERROR,
                )
                await interaction.followup.send(embed=embed)
                return

            # 일일 제한
            limit_ok, current, max_count = check_daily_limit(user_data, "labyrinth")
            if not limit_ok:
                embed = discord.Embed(
                    title="⏳ 일일 미궁 제한",
                    description=(
                        f"오늘의 미궁 도전 횟수를 모두 소진했습니다.\n"
                        f"일일 제한: **{DAILY_LIMITS.get('labyrinth', 5)}회**"
                    ),
                    color=COLOR_WARNING,
                )
                await interaction.followup.send(embed=embed)
                return

            # 보유 냥이 체크
            owned_cats = user_data.get("cats", user_data.get("owned_cats", {}))
            has_cats = False
            if isinstance(owned_cats, dict):
                for v in owned_cats.values():
                    if isinstance(v, dict):
                        try:
                            count = int(v.get("count", 0))
                        except (ValueError, TypeError):
                            count = 1
                    elif isinstance(v, (int, float)):
                        count = int(v)
                    elif isinstance(v, str):
                        try:
                            count = int(v)
                        except ValueError:
                            count = 1
                    else:
                        count = 1
                    if count > 0:
                        has_cats = True
                        break
            elif isinstance(owned_cats, list):
                has_cats = len(owned_cats) > 0
                
            if not has_cats:
                embed = discord.Embed(
                    title="❌ 도전 불가",
                    description=(
                        "냥이가 없어 미궁에 도전할 수 없습니다!\n"
                        "`/납치`로 냥이를 먼저 모아주세요."
                    ),
                    color=COLOR_ERROR,
                )
                await interaction.followup.send(embed=embed)
                return

            # 시작 임베드 + 뷰
            embed = build_labyrinth_intro_embed(user_data)
            view = LabyrinthStartView(user_id)
            await interaction.followup.send(embed=embed, view=view)

            # ★ 뷰 종료 대기 (미궁 진행이 끝날 때까지 잠금 유지)
            await view.wait()

        except Exception as e:
            embed = discord.Embed(
                title="❌ 오류",
                description=f"미궁 시작 중 오류가 발생했습니다.\n`{str(e)[:100]}`",
                color=COLOR_ERROR,
            )
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(embed=embed)
                else:
                    await interaction.response.send_message(embed=embed)
            except Exception:
                pass
        finally:
            release_lock(user_id)

            
    # ---- /미궁기록 ----
    @app_commands.command(name="미궁기록", description="미궁 탐험 기록을 확인합니다.")
    @is_registered()
    @is_not_banned()
    async def labyrinth_record_command(self, interaction: discord.Interaction):
        await interaction.response.defer()
        user_data = load_user_data(str(interaction.user.id))
        embed = build_labyrinth_record_embed(user_data, interaction.user)
        await interaction.followup.send(embed=embed)


# ============================================================
# Cog 등록
# ============================================================

async def setup(bot: commands.Bot):
    await bot.add_cog(LabyrinthCog(bot))
