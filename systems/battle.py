import asyncio
import json
import os
import random
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import discord
from discord import app_commands
from discord.ext import commands

import config as _cfg           # ◀◀◀ 이 줄이 반드시 필요

# ── config 값 로딩 ──
DATA_DIR = _cfg.DATA_DIR
USERS_DIR = _cfg.USERS_DIR

COLOR_DEFAULT = _cfg.COLOR_DEFAULT
COLOR_SUCCESS = _cfg.COLOR_SUCCESS
COLOR_ERROR = _cfg.COLOR_ERROR
COLOR_WARNING = _cfg.COLOR_WARNING

RARITY_TIERS = _cfg.RARITY_TIERS
MAX_LEVEL = _cfg.MAX_LEVEL
SKILL_EFFECTS = _cfg.SKILL_EFFECTS
DAILY_LIMITS = _cfg.DAILY_LIMITS
NEWBIE_PROTECTION_DAYS = _cfg.NEWBIE_PROTECTION_DAYS
CATCHUP_EXP_BONUS_MAX = _cfg.CATCHUP_EXP_BONUS_MAX
WEEKLY_BOSS_TEMPLATES = _cfg.WEEKLY_BOSS_TEMPLATES
ACHIEVEMENTS = _cfg.ACHIEVEMENTS
MONEY_SOFT_CAP_PER_LEVEL = _cfg.MONEY_SOFT_CAP_PER_LEVEL

BOT_ICON_URL = _cfg.BOT_ICON_URL
SEPARATOR = getattr(_cfg, "SEPARATOR", _cfg.EMBED_THIN_SEPARATOR)
RARITY_ORDER = getattr(_cfg, "RARITY_ORDER", ["common", "uncommon", "rare", "epic", "legendary", "mythic"])
FOOTER_TEXT = getattr(_cfg, "EMBED_FOOTER_TEXT", "카요코 봇")

BAR_FILLED = _cfg.BAR_FILLED
BAR_EMPTY_CHAR = _cfg.BAR_EMPTY

# ★ 기존 — 삭제
# try:
#     from commands.shop_commands import get_equipment_stats
# except ImportError:
#     def get_equipment_stats(uid):
#         return {}

# ★ 신규 — user_data를 받는 버전
try:
    from models.equipment import get_total_equipment_stats
except ImportError:
    def get_total_equipment_stats(user_data):
        return {"attack": 0, "hp_bonus": 0, "defense": 0}


def get_equipment_stats(uid_or_udata):
    """하위 호환용 래퍼 — uid(int)든 udata(dict)든 처리"""
    if isinstance(uid_or_udata, dict):
        return get_total_equipment_stats(uid_or_udata)
    # uid가 넘어온 경우 → 유저 로드 후 처리
    udata = load_user(uid_or_udata)
    if udata is None:
        return {"attack": 0, "hp_bonus": 0, "defense": 0}
    return get_total_equipment_stats(udata)

# ──────────────────────────────────────────────────────────────────
#  헬퍼
# ──────────────────────────────────────────────────────────────────

def _safe_rarity_str(raw):
    if isinstance(raw, str) and raw.lower() in RARITY_TIERS:
        return raw.lower()
    if isinstance(raw, str):
        return raw.lower()
    if isinstance(raw, (int, float)):
        val = float(raw)
        for key in ["mythic", "legendary", "epic", "rare", "uncommon", "common"]:
            tier = RARITY_TIERS.get(key, {})
            if val <= tier.get("min_rarity", 999):
                return key
        return "common"
    return "common"


def _user_path(uid):
    return os.path.join(USERS_DIR, f"{uid}.json")


def load_user(uid):
    p = _user_path(uid)
    if not os.path.exists(p):
        return _default_user(uid)
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def save_user(uid, data):
    with open(_user_path(uid), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _default_user(uid):
    return {
        "user_id": uid,
        "level": 1, "exp": 0, "money": 0,
        "skills": {"tracking": 0, "combat": 0, "trade": 0},
        "cats": {}, "catdex": {},
        "equipped": {"weapon": None, "tool": None, "accessory": None},
        "inventory": {"weapons": [], "tools": [], "accessories": []},
        "daily_actions": {"date": ""},
        "achievements": [], "tutorial_step": "welcome",
        "created_at": datetime.utcnow().isoformat(),
        "stats": {},
    }


def exp_required(level):
    return _cfg.get_exp_for_level(level)


def grant_exp(udata, amount):
    created = udata.get("created_at")
    if created:
        try:
            age = (datetime.utcnow() - datetime.fromisoformat(created)).days
        except (ValueError, TypeError):
            age = 999
        if age <= NEWBIE_PROTECTION_DAYS:
            ratio = 1.0 - (age / NEWBIE_PROTECTION_DAYS)
            bonus = ratio * CATCHUP_EXP_BONUS_MAX
            amount = int(amount * (1.0 + bonus))

    udata["exp"] = udata.get("exp", 0) + amount
    leveled = False
    old_level = udata.get("level", 1)

    while udata.get("level", 1) < MAX_LEVEL:
        needed = exp_required(udata["level"])
        if udata["exp"] >= needed:
            udata["exp"] -= needed
            udata["level"] += 1
            leveled = True
        else:
            break

    # ★ 레벨업 시 스킬포인트 지급
    new_level = udata.get("level", 1)
    if new_level > old_level:
        levels_gained = new_level - old_level
        sp_gained = levels_gained * _cfg.SKILL_POINTS_PER_LEVEL
        udata["skill_points"] = udata.get("skill_points", 0) + sp_gained

    return amount, leveled

def _check_daily(udata, action):
    today = time.strftime("%Y-%m-%d")
    daily = udata.setdefault("daily_actions", {})
    if daily.get("date") != today:
        udata["daily_actions"] = {"date": today}
        daily = udata["daily_actions"]
    count = daily.get(action, 0)
    limit = DAILY_LIMITS.get(action, 999)
    return count < limit, count, limit


def _increment_daily(udata, action):
    daily = udata.setdefault("daily_actions", {})
    daily[action] = daily.get(action, 0) + 1


def check_achievements(udata):
    earned = udata.get("achievements", [])

    # ★ dict로 저장된 경우 리스트로 변환
    if isinstance(earned, dict):
        earned = list(earned.keys())
        udata["achievements"] = earned

    new_achievements = []
    stats = udata.get("stats", {})
    level = udata.get("level", 1)
    money = udata.get("money", 0)

    checks = {
        "battle_10": stats.get("battle_wins", 0) >= 10,
        "battle_100": stats.get("battle_wins", 0) >= 100,
        "level_10": level >= 10,
        "level_25": level >= 25,
        "level_50": level >= 50,
        "level_70": level >= 70,
        "weekly_boss_first": stats.get("weekly_boss_first_kill", False),
        "rich_100k": money >= 100000,
        "rich_1m": money >= 1000000,
    }

    for ach_id, met in checks.items():
        if met and ach_id not in earned and ach_id in ACHIEVEMENTS:
            earned.append(ach_id)
            new_achievements.append({"id": ach_id, **ACHIEVEMENTS[ach_id]})

    return new_achievements



# ──────────────────────────────────────────────────────────────────
#  플레이어 스탯
# ──────────────────────────────────────────────────────────────────

def _owns_cat_by_name(udata: dict, name: str) -> bool:
    """일반 cats(dict/list) + enhanced_cats에서 이름으로 보유 여부 확인."""
    cats = udata.get("cats") or {}
    if isinstance(cats, dict):
        # 키 자체가 이름인 경우 or value dict의 name이 일치하는 경우
        if name in cats:
            return True
        for cid, info in cats.items():
            if isinstance(info, dict) and info.get("name") == name:
                return True
    elif isinstance(cats, list):
        for x in cats:
            if isinstance(x, dict) and x.get("name") == name:
                return True
            if isinstance(x, str) and x == name:
                return True
    for inst in udata.get("enhanced_cats") or []:
        if isinstance(inst, dict) and inst.get("name") == name:
            return True
    return False


def _get_lead_cat_types(udata):
    """
    선봉 냥이(battle_team[0])의 (attack_type, defense_type)를 반환.
    미편성/미보유/속성없음이면 (none, none) → 배율 1.0.
    battle_team 포맷: 냥이 이름 리스트, [0]이 선봉.
    강화 냥이(enhanced_cats)도 보유로 인정.
    """
    from models.element import get_cat_types, NONE_TYPE
    team = udata.get("battle_team") or []
    if not isinstance(team, list) or not team:
        return NONE_TYPE, NONE_TYPE
    lead_name = team[0]
    if not _owns_cat_by_name(udata, lead_name):
        return NONE_TYPE, NONE_TYPE
    try:
        from models.cat import get_cat_by_name
        cat_def = get_cat_by_name(lead_name)
    except Exception:
        cat_def = None
    return get_cat_types(cat_def)


def get_player_stats(udata):
    level = udata.get("level", 1)

    base_hp = 100 + (level - 1) * 15
    base_attack = 10 + (level - 1) * 3
    base_defense = 5 + (level - 1) * 2

    combat_lv = udata.get("skills", {}).get("combat", 0)
    combat_effects = SKILL_EFFECTS.get("combat", {})
    combat_atk = combat_lv * combat_effects.get("battle_power_bonus", 2.5)
    combat_hp = combat_lv * combat_effects.get("battle_hp_bonus", 8)

    # ★ udata를 직접 전달
    eq_stats = get_total_equipment_stats(udata)
    eq_attack = eq_stats.get("attack", 0)
    eq_hp = eq_stats.get("hp_bonus", 0)

    lead_atk_type, lead_def_type = _get_lead_cat_types(udata)

    return {
        "max_hp": int(base_hp + combat_hp + eq_hp),
        "attack": int(base_attack + combat_atk + eq_attack),
        "defense": int(base_defense),
        "attack_type": lead_atk_type,
        "defense_type": lead_def_type,
        "lead_cat": (udata.get("battle_team") or [None])[0],
    }
# ──────────────────────────────────────────────────────────────────
#  적 생성
# ──────────────────────────────────────────────────────────────────

ENEMY_TEMPLATES = [
    {"name": "들고양이",      "emoji": "🐱", "level_range": (1, 10),  "hp_mult": 0.8, "atk_mult": 0.7, "money": (30, 80),   "exp": (8, 15)},
    {"name": "야생 너구리",   "emoji": "🦝", "level_range": (1, 15),  "hp_mult": 1.0, "atk_mult": 0.8, "money": (40, 100),  "exp": (10, 20)},
    {"name": "성난 까마귀",   "emoji": "🐦", "level_range": (5, 25),  "hp_mult": 0.7, "atk_mult": 1.2, "money": (50, 120),  "exp": (12, 25)},
    {"name": "떠돌이 사냥꾼", "emoji": "🏹", "level_range": (10, 35), "hp_mult": 1.2, "atk_mult": 1.0, "money": (70, 180),  "exp": (18, 35)},
    {"name": "그림자 늑대",   "emoji": "🐺", "level_range": (15, 45), "hp_mult": 1.3, "atk_mult": 1.3, "money": (100, 250), "exp": (25, 50)},
    {"name": "철갑 골렘",     "emoji": "🗿", "level_range": (25, 55), "hp_mult": 2.0, "atk_mult": 0.9, "money": (150, 350), "exp": (35, 65)},
    {"name": "심연의 그림자", "emoji": "👁",  "level_range": (35, 65), "hp_mult": 1.5, "atk_mult": 1.5, "money": (200, 500), "exp": (45, 80)},
    {"name": "혼돈의 기사",   "emoji": "⚔",  "level_range": (45, 70), "hp_mult": 1.8, "atk_mult": 1.6, "money": (300, 700), "exp": (60, 100)},
]


def _select_enemy(player_level):
    valid = [e for e in ENEMY_TEMPLATES if e["level_range"][0] <= player_level <= e["level_range"][1]]
    if not valid:
        valid = ENEMY_TEMPLATES[-2:]
    template = random.choice(valid)
    enemy_level = max(1, min(player_level + random.randint(-3, 3), MAX_LEVEL))
    base_hp = 80 + (enemy_level - 1) * 12
    base_atk = 8 + (enemy_level - 1) * 2.5
    e_atk_type = random.choice(["explosive", "piercing", "mystic"])
    e_def_type = random.choice(["light", "heavy", "special"])
    return {
        "name": template["name"], "emoji": template["emoji"],
        "level": enemy_level,
        "max_hp": int(base_hp * template["hp_mult"]),
        "hp": int(base_hp * template["hp_mult"]),
        "attack": int(base_atk * template["atk_mult"]),
        "defense": 0,
        "attack_type": e_atk_type,
        "defense_type": e_def_type,
        "money_range": template["money"],
        "exp_range": template["exp"],
    }


# 주간 보스 속성 (config.py를 건드리지 않기 위해 여기서 정의)
#  · 보스마다 카운터 속성이 다르도록 배치 → 주간 편성 메타 발생
#  · 템플릿에 attack_type/defense_type가 있으면 그 값을 우선 사용
_WEEKLY_BOSS_TYPES = {
    "shadow_lord":      {"attack_type": "mystic",   "defense_type": "heavy"},    # 관통으로 카운터
    "crystal_guardian": {"attack_type": "explosive","defense_type": "special"},  # 신비로 카운터
    "chaos_emperor":    {"attack_type": "sonic",    "defense_type": "elastic"},  # 진동으로 카운터(엔드게임)
}


def _create_weekly_boss(boss_key):
    template = WEEKLY_BOSS_TEMPLATES.get(boss_key)
    if not template:
        return None
    rewards = template.get("rewards", {})
    # config에서 money/exp는 tuple
    money_range = rewards.get("money", (15000, 30000))
    exp_range = rewards.get("exp", (500, 1000))
    types = _WEEKLY_BOSS_TYPES.get(boss_key, {})
    return {
        "name": template["name"], "emoji": "💀",
        "level": 70,
        "max_hp": template["hp"], "hp": template["hp"],
        "attack": template["attack"], "defense": 0,
        "attack_type": template.get("attack_type", types.get("attack_type", "none")),
        "defense_type": template.get("defense_type", types.get("defense_type", "none")),
        "money_range": money_range,
        "exp_range": exp_range,
        "is_boss": True, "boss_key": boss_key,
        "special_drop": rewards.get("title"),
        "tuna_can_range": rewards.get("tuna_can", (0, 0)),
    }


def _get_current_weekly_boss_key():
    keys = list(WEEKLY_BOSS_TEMPLATES.keys())
    if not keys:
        return ""
    week_num = datetime.utcnow().isocalendar()[1]
    return keys[week_num % len(keys)]


# ──────────────────────────────────────────────────────────────────
#  전투 시뮬레이션
# ──────────────────────────────────────────────────────────────────

def _build_hp_bar(current, maximum, length=10):
    ratio = max(0.0, min(1.0, current / maximum)) if maximum > 0 else 0.0
    filled = round(ratio * length)
    return BAR_FILLED * filled + BAR_EMPTY_CHAR * (length - filled)


def simulate_battle(player, enemy):
    from models.element import calc_type_multiplier, effectiveness_symbol

    p_hp = player["max_hp"]
    p_atk = player["attack"]
    p_def = player["defense"]
    e_hp = enemy["hp"]
    e_atk = enemy["attack"]
    e_def = enemy.get("defense", 0)

    # ── 속성 상성 배율 (선봉 냥이 ↔ 적) ──
    p_mult = calc_type_multiplier(player.get("attack_type"), enemy.get("defense_type"))
    e_mult = calc_type_multiplier(enemy.get("attack_type"), player.get("defense_type"))
    p_tag = f" ({effectiveness_symbol(p_mult)})" if p_mult != 1.0 else ""
    e_tag = f" ({effectiveness_symbol(e_mult)})" if e_mult != 1.0 else ""

    log = []
    turn = 0

    while p_hp > 0 and e_hp > 0 and turn < 50:
        turn += 1
        crit = random.random() < 0.15
        p_damage = max(1, p_atk - e_def + random.randint(-3, 5))
        if crit:
            p_damage = int(p_damage * 1.5)
        p_damage = max(1, int(p_damage * p_mult))
        e_hp = max(0, e_hp - p_damage)
        crit_text = " **크리티컬!**" if crit else ""
        log.append({"turn": turn, "attacker": "player", "damage": p_damage, "p_hp": p_hp, "e_hp": e_hp,
                     "desc": f"⚔️ 당신의 공격! **{p_damage}** 데미지{crit_text}{p_tag}"})
        if e_hp <= 0:
            break

        e_crit = random.random() < 0.10
        e_damage = max(1, e_atk - p_def + random.randint(-3, 5))
        if e_crit:
            e_damage = int(e_damage * 1.5)
        e_damage = max(1, int(e_damage * e_mult))
        p_hp = max(0, p_hp - e_damage)
        e_crit_text = " **크리티컬!**" if e_crit else ""
        log.append({"turn": turn, "attacker": "enemy", "damage": e_damage, "p_hp": p_hp, "e_hp": e_hp,
                     "desc": f"💥 {enemy['name']}의 공격! **{e_damage}** 데미지{e_crit_text}{e_tag}"})

    return log, (p_hp > 0 and e_hp <= 0)


# ──────────────────────────────────────────────────────────────────
#  임베드
# ──────────────────────────────────────────────────────────────────

def _build_battle_start_embed(user, player, enemy):
    is_boss = enemy.get("is_boss", False)
    embed = discord.Embed(
        title="💀 주간 보스 출현!" if is_boss else "⚔️ 전투 시작!",
        description=f"{enemy.get('emoji', '👾')} **{enemy['name']}** (Lv.{enemy['level']}) 과 조우했습니다!",
        color=COLOR_WARNING if is_boss else COLOR_DEFAULT,
    )
    from models.element import (
        attack_label, defense_label, calc_type_multiplier, effectiveness_symbol,
    )

    lead = player.get("lead_cat")
    p_type_line = f"\n{attack_label(player.get('attack_type'))} / {defense_label(player.get('defense_type'))}"
    if lead:
        p_type_line += f"\n선봉: **{lead}**"
    else:
        p_type_line += "\n선봉: *미편성* (`/편성`으로 지정)"

    p_bar = _build_hp_bar(player["max_hp"], player["max_hp"])
    embed.add_field(name=f"👤 {user.display_name} (Lv.{player.get('level', '?')})",
                    value=f"HP: {p_bar} {player['max_hp']}/{player['max_hp']}\nATK: **{player['attack']}** | DEF: **{player['defense']}**{p_type_line}", inline=True)

    e_type_line = f"\n{attack_label(enemy.get('attack_type'))} / {defense_label(enemy.get('defense_type'))}"
    p_mult = calc_type_multiplier(player.get("attack_type"), enemy.get("defense_type"))
    if p_mult != 1.0:
        e_type_line += f"\n내 공격: {effectiveness_symbol(p_mult)}"

    e_bar = _build_hp_bar(enemy["hp"], enemy["max_hp"])
    embed.add_field(name=f"{enemy.get('emoji', '👾')} {enemy['name']} (Lv.{enemy['level']})",
                    value=f"HP: {e_bar} {enemy['hp']}/{enemy['max_hp']}\nATK: **{enemy['attack']}**{e_type_line}", inline=True)
    embed.set_footer(text=FOOTER_TEXT, icon_url=BOT_ICON_URL)
    return embed


def _build_battle_log_embed(user, enemy, log, player_stats, player_won):
    embed = discord.Embed(title="✅ 전투 승리!" if player_won else "❌ 전투 패배...",
                          color=COLOR_SUCCESS if player_won else COLOR_ERROR)
    display_log = log[-8:] if len(log) > 8 else log
    log_text = ""
    if len(log) > 8:
        log_text = f"*... {len(log) - 8}턴 생략 ...*\n\n"
    for entry in display_log:
        p_bar = _build_hp_bar(entry["p_hp"], player_stats["max_hp"], 8)
        e_bar = _build_hp_bar(entry["e_hp"], enemy["max_hp"], 8)
        log_text += f"**턴 {entry['turn']}** {entry['desc']}\n> 👤 {p_bar} {entry['p_hp']}hp | {enemy.get('emoji', '👾')} {e_bar} {entry['e_hp']}hp\n"
    embed.description = log_text
    embed.add_field(name="📊 전투 요약",
                    value=f"총 턴: **{log[-1]['turn'] if log else 0}턴** | 결과: **{'승리' if player_won else '패배'}**", inline=False)
    embed.set_footer(text=f"{user.display_name} | {FOOTER_TEXT}", icon_url=user.display_avatar.url)
    return embed


def _build_reward_embed(user, money, exp, leveled, new_level, new_achs, enemy, special_drop=None):
    embed = discord.Embed(title="🎁 전투 보상", description=f"{enemy.get('emoji', '👾')} **{enemy['name']}** 처치 보상!", color=COLOR_SUCCESS)
    embed.add_field(name="💰 획득 금액", value=f"**+{money:,}원**", inline=True)
    embed.add_field(name="✨ 획득 경험치", value=f"**+{exp}**", inline=True)
    if leveled:
        embed.add_field(name="🎉 레벨 업!", value=f"**Lv.{new_level}** 달성!", inline=False)
    if special_drop:
        embed.add_field(name="🌟 칭호 획득!", value=f"**{special_drop}**", inline=False)
    if new_achs:
        ach_lines = [f"🏆 **{a.get('name', '?')}** — {a.get('desc', '')}" for a in new_achs]
        embed.add_field(name="🏆 업적 달성!", value="\n".join(ach_lines), inline=False)
    embed.set_footer(text=f"{user.display_name} | {FOOTER_TEXT}", icon_url=user.display_avatar.url)
    return embed


def _build_defeat_embed(user, enemy, newbie_protected):
    embed = discord.Embed(title="💀 패배...", description=f"{enemy.get('emoji', '👾')} **{enemy['name']}**에게 패배했습니다.", color=COLOR_ERROR)
    if newbie_protected:
        embed.add_field(name="🛡️ 뉴비 보호", value="뉴비 보호 기간이므로 패널티가 적용되지 않습니다!", inline=False)
    else:
        embed.add_field(name="📉 패널티", value="전투에 패배하면 소량의 돈을 잃습니다.", inline=False)
    embed.set_footer(text=f"{user.display_name} | {FOOTER_TEXT}", icon_url=user.display_avatar.url)
    return embed


# ──────────────────────────────────────────────────────────────────
#  전투 뷰
# ──────────────────────────────────────────────────────────────────

class BattleStartView(discord.ui.View):
    def __init__(self, owner_id, enemy, is_boss=False, timeout=30.0):
        super().__init__(timeout=timeout)
        self.owner_id = owner_id
        self.enemy = enemy
        self.is_boss = is_boss
        self.started = False
        # ★ 전투 완료 대기용 이벤트
        self._battle_done = asyncio.Event()

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "다른 사람의 전투에 참여할 수 없습니다!", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="전투 시작!", style=discord.ButtonStyle.danger, emoji="⚔️")
    async def start_battle(self, interaction, button):
        if self.started:
            return
        self.started = True

        for item in self.children:
            item.disabled = True

        try:
            await _execute_battle(interaction, self.enemy, self.is_boss)
        except Exception as e:
            print(f"[전투] _execute_battle 에러: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            # 유저에게도 알림
            try:
                await interaction.followup.send(
                    embed=discord.Embed(
                        title="❌ 전투 오류",
                        description=f"전투 처리 중 오류가 발생했습니다.\n`{str(e)[:200]}`",
                        color=COLOR_ERROR,
                    ),
                )
            except Exception:
                pass
        finally:
            self._battle_done.set()
            self.stop()

    @discord.ui.button(label="도망치기", style=discord.ButtonStyle.secondary, emoji="🏃")
    async def flee(self, interaction, button):
        if self.started:
            return
        self.started = True
        self._battle_done.set()
        self.stop()
        embed = discord.Embed(
            title="🏃 도주 성공!",
            description="전투에서 도망쳤습니다.",
            color=COLOR_WARNING,
        )
        await interaction.response.edit_message(embed=embed, view=None)

    async def on_timeout(self):
        if not self.started:
            self.started = True
            self._battle_done.set()

# ──────────────────────────────────────────────────────────────────
#  전투 실행
# ──────────────────────────────────────────────────────────────────

async def _execute_battle(interaction, enemy, is_boss=False):
    uid = interaction.user.id
    udata = load_user(uid)
    player_stats = get_player_stats(udata)
    player_stats["level"] = udata.get("level", 1)

    # ★ 버튼 응답: 진행 중 표시
    await interaction.response.edit_message(
        embed=discord.Embed(
            title="⚔️ 전투 진행 중...",
            description="잠시 기다려주세요...",
            color=COLOR_DEFAULT,
        ),
        view=None,
    )
    await asyncio.sleep(1.5)

    log, player_won = simulate_battle(player_stats, enemy)
    log_embed = _build_battle_log_embed(interaction.user, enemy, log, player_stats, player_won)

    # ★ 결과 편집을 위한 메시지 객체 확보
    try:
        msg = interaction.message
    except Exception:
        msg = None

    if player_won:
        money = random.randint(*enemy["money_range"])
        exp_amount = random.randint(*enemy["exp_range"])

        current_money = udata.get("money", 0)
        soft_cap = _cfg.MONEY_SOFT_CAP_BASE + udata.get("level", 1) * MONEY_SOFT_CAP_PER_LEVEL
        if current_money > soft_cap:
            money = int(money * 0.5)

        udata["money"] = udata.get("money", 0) + money
        actual_exp, leveled = grant_exp(udata, exp_amount)

        stats = udata.setdefault("stats", {})
        stats["battle_wins"] = stats.get("battle_wins", 0) + 1

        special_drop = None
        if is_boss:
            stats["weekly_boss_kills"] = stats.get("weekly_boss_kills", 0) + 1
            if not stats.get("weekly_boss_first_kill"):
                stats["weekly_boss_first_kill"] = True
            if enemy.get("special_drop") and random.random() < 0.3:
                special_drop = enemy["special_drop"]

        _increment_daily(udata, "battle")
        new_achs = check_achievements(udata)

        for ach in new_achs:
            if ach.get("reward_money"):
                udata["money"] += ach["reward_money"]
            if ach.get("reward_exp"):
                grant_exp(udata, ach["reward_exp"])

        save_user(uid, udata)

        reward_embed = _build_reward_embed(
            interaction.user, money, actual_exp, leveled,
            udata["level"], new_achs, enemy, special_drop,
        )

        if leveled:
            levels_gained = udata["level"] - player_stats["level"]
            sp_gained = levels_gained * _cfg.SKILL_POINTS_PER_LEVEL
            if sp_gained > 0:
                reward_embed.add_field(
                    name="⭐ 스킬 포인트 획득!",
                    value=f"**+{sp_gained}P** (잔여: {udata.get('skill_points', 0)}P)\n`/스킬투자`로 투자하세요!",
                    inline=False,
                )

        result_embeds = [log_embed, reward_embed]

    else:
        newbie_protected = False
        created = udata.get("created_at")
        if created:
            try:
                age = (datetime.utcnow() - datetime.fromisoformat(created)).days
                if age <= NEWBIE_PROTECTION_DAYS:
                    newbie_protected = True
            except (ValueError, TypeError):
                pass

        if not newbie_protected:
            loss = int(udata.get("money", 0) * random.uniform(0.03, 0.05))
            udata["money"] = max(0, udata.get("money", 0) - loss)

        stats = udata.setdefault("stats", {})
        stats["battle_losses"] = stats.get("battle_losses", 0) + 1
        _increment_daily(udata, "battle")
        save_user(uid, udata)

        defeat_embed = _build_defeat_embed(interaction.user, enemy, newbie_protected)
        result_embeds = [log_embed, defeat_embed]

    # ★ 핵심: 3가지 방법을 순서대로 시도
    edited = False

    # 방법 1: message 객체로 직접 편집
    if msg and not edited:
        try:
            await msg.edit(embeds=result_embeds, view=None)
            edited = True
        except Exception as e:
            print(f"[전투] msg.edit 실패: {e}")

    # 방법 2: edit_original_response
    if not edited:
        try:
            await interaction.edit_original_response(embeds=result_embeds, view=None)
            edited = True
        except Exception as e:
            print(f"[전투] edit_original_response 실패: {e}")

    # 방법 3: followup으로 새 메시지 전송
    if not edited:
        try:
            await interaction.followup.send(embeds=result_embeds)
        except Exception as e:
            print(f"[전투] followup 전송도 실패: {e}")

# ──────────────────────────────────────────────────────────────────
#  진입점
# ──────────────────────────────────────────────────────────────────

async def run_battle_sequence(interaction):
    uid = interaction.user.id
    udata = load_user(uid)

    if udata.get("level", 1) < _cfg.BATTLE_MIN_LEVEL:
        embed = discord.Embed(
            title="🔒 레벨 부족",
            description=f"전투는 **Lv.{_cfg.BATTLE_MIN_LEVEL}** 이상부터 가능합니다.",
            color=COLOR_ERROR,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    allowed, count, limit = _check_daily(udata, "battle")
    if not allowed:
        embed = discord.Embed(
            title="⏰ 일일 전투 한도 초과",
            description=(
                f"오늘의 전투 한도(**{limit}회**)를 모두 사용했습니다.\n"
                f"현재: {count}/{limit}"
            ),
            color=COLOR_ERROR,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    player_stats = get_player_stats(udata)
    player_stats["level"] = udata.get("level", 1)
    enemy = _select_enemy(udata.get("level", 1))

    start_embed = _build_battle_start_embed(interaction.user, player_stats, enemy)
    view = BattleStartView(uid, enemy, is_boss=False)

    # ★ defer 없이 직접 응답 — 버튼이 포함된 메시지가 interaction의 원본 응답이 됨
    await interaction.response.send_message(embed=start_embed, view=view)

    await view.wait()

async def run_weekly_boss_sequence(interaction):
    uid = interaction.user.id
    udata = load_user(uid)

    if udata.get("level", 1) < _cfg.WEEKLY_BOSS_MIN_LEVEL:
        embed = discord.Embed(
            title="🔒 레벨 부족",
            description=f"주간 보스는 **Lv.{_cfg.WEEKLY_BOSS_MIN_LEVEL}** 이상부터 도전할 수 있습니다.",
            color=COLOR_ERROR,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    allowed, count, limit = _check_daily(udata, "battle")
    if not allowed:
        embed = discord.Embed(
            title="⏰ 일일 전투 한도 초과",
            description="오늘의 전투 한도를 모두 사용했습니다.",
            color=COLOR_ERROR,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    boss_key = _get_current_weekly_boss_key()
    if not boss_key:
        await interaction.response.send_message(
            embed=discord.Embed(title="❌ 보스 없음", color=COLOR_ERROR),
            ephemeral=True,
        )
        return

    boss = _create_weekly_boss(boss_key)
    if not boss:
        await interaction.response.send_message(
            embed=discord.Embed(title="❌ 보스 생성 실패", color=COLOR_ERROR),
            ephemeral=True,
        )
        return

    player_stats = get_player_stats(udata)
    player_stats["level"] = udata.get("level", 1)

    template = WEEKLY_BOSS_TEMPLATES.get(boss_key, {})
    embed = discord.Embed(
        title=f"💀 주간 보스: {boss['name']}",
        description=(
            f"**{boss['name']}** (Lv.{boss['level']})\n\n"
            f"{template.get('description', '')}\n{SEPARATOR}"
        ),
        color=0xFF0000,
    )
    p_bar = _build_hp_bar(player_stats["max_hp"], player_stats["max_hp"])
    embed.add_field(
        name=f"👤 {interaction.user.display_name}",
        value=(
            f"HP: {p_bar} {player_stats['max_hp']}\n"
            f"ATK: **{player_stats['attack']}** | DEF: **{player_stats['defense']}**"
        ),
        inline=True,
    )
    e_bar = _build_hp_bar(boss["hp"], boss["max_hp"])
    embed.add_field(
        name=f"💀 {boss['name']}",
        value=f"HP: {e_bar} {boss['hp']}\nATK: **{boss['attack']}**",
        inline=True,
    )
    embed.set_footer(
        text=f"{FOOTER_TEXT} | 주간 보스는 매주 월요일 변경",
        icon_url=BOT_ICON_URL,
    )

    view = BattleStartView(uid, boss, is_boss=True)

    # ★ defer 없이 직접 응답
    await interaction.response.send_message(embed=embed, view=view)

    await view.wait()
