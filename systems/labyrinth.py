# systems/labyrinth.py
# ─────────────────────────────────────────────────────
#  무한 미궁 시스템
#  - 층(floor) 기반 무한 던전
#  - 5층마다 보스전
#  - 층 클리어 시 보상 누적
#  - 사망(전멸) 시 런 종료, 그때까지 누적 보상은 유지
#  - 최고 기록 랭킹
#  - 이벤트 타일 (휴식, 함정, 상자, 상인)
# ─────────────────────────────────────────────────────

import asyncio
import random
import math
import time
import discord

from config import (
    COLOR_PRIMARY, COLOR_SUCCESS, COLOR_ERROR, COLOR_WARNING,
    COLOR_RARE, COLOR_LEGENDARY, COLOR_MYTHIC,
    BOT_ICON_URL, SKILL_TREE_TRADE, SKILL_TREE_COMBAT
)
from models.user import load_user_data, save_user_data, add_exp, get_skill_effect
from models.cat import get_cat_by_name
from models.element import (
    calc_type_multiplier, effectiveness_symbol, get_cat_types, NONE_TYPE,
)

# ★ 안전 import
try:
    from models.equipment import get_total_equipment_stats
except ImportError:
    def get_total_equipment_stats(user_data):
        return {"attack": 0, "hp_bonus": 0, "defense": 0}

# ★ BOT_ICON → BOT_ICON_URL 통일
BOT_ICON = BOT_ICON_URL


def _apply_type(attacker, target, damage: int) -> tuple[int, float]:
    """공격자→대상 속성 상성 배율을 적용한 (최종 데미지, 배율)을 반환."""
    mult = calc_type_multiplier(
        getattr(attacker, "attack_type", NONE_TYPE),
        getattr(target, "defense_type", NONE_TYPE),
    )
    return max(1, int(damage * mult)), mult


def _tag(mult: float) -> str:
    """상성 배율이 유효/저항일 때만 로그용 꼬리표를 붙인다."""
    sym = effectiveness_symbol(mult)
    return f" ({sym})" if mult != 1.0 else ""



# =====================================================
#  상수
# =====================================================

# 미궁 진입 조건
LABYRINTH_MIN_LEVEL = 10
LABYRINTH_MIN_CATS = 3
LABYRINTH_COOLDOWN_SECONDS = 120  # 미궁 쿨다운 2분

# 층 스케일링
BASE_ENEMY_HP = 120
BASE_ENEMY_ATK = 12
HP_SCALE_PER_FLOOR = 0.12        # 층당 HP +12%
ATK_SCALE_PER_FLOOR = 0.08       # 층당 ATK +8%
BOSS_HP_MULTIPLIER = 2.5
BOSS_ATK_MULTIPLIER = 1.8

# 보상 스케일링
BASE_FLOOR_MONEY = 150
BASE_FLOOR_EXP = 20
MONEY_SCALE_PER_FLOOR = 0.10     # 층당 보상 +10%
EXP_SCALE_PER_FLOOR = 0.08
BOSS_REWARD_MULTIPLIER = 3.0

# 이벤트 확률 (전투 외 이벤트)
EVENT_CHANCE = 0.30               # 30% 확률로 이벤트 타일
EVENT_WEIGHTS = {
    "rest": 30,        # 휴식 (HP 회복)
    "trap": 25,        # 함정 (HP 피해)
    "treasure": 25,    # 보물 상자 (추가 보상)
    "merchant": 10,    # 상인 (돈으로 HP 구매)
    "mystery": 10,     # 미스터리 (랜덤 효과)
}

# 최대 턴 (한 층당)
MAX_FLOOR_TURNS = 15

# 동시 실행 방지
_labyrinth_active: set[int] = set()
_labyrinth_cooldowns: dict[int, float] = {}


# =====================================================
#  미궁 유닛 클래스
# =====================================================

class LabyrinthUnit:
    """미궁 전용 전투 유닛"""

    def __init__(self, name: str, hp: int, attack: int, speed: int, is_ally: bool = True,
                 attack_type: str = NONE_TYPE, defense_type: str = NONE_TYPE):
        self.name = name
        self.max_hp = hp
        self.current_hp = hp
        self.attack = attack
        self.speed = speed
        self.is_ally = is_ally
        self.attack_type = attack_type
        self.defense_type = defense_type
        self.defend_buff = False
        self.is_defending = False

    def take_damage(self, damage: int) -> int:
        """데미지 적용, 실제 받은 데미지 반환"""
        if self.is_defending:
            damage = max(1, damage // 2)
        actual = min(self.current_hp, max(1, damage))
        self.current_hp = max(0, self.current_hp - actual)
        return actual

    def heal(self, amount: int) -> int:
        """회복, 실제 회복량 반환"""
        before = self.current_hp
        self.current_hp = min(self.max_hp, self.current_hp + amount)
        return self.current_hp - before

    def is_alive(self) -> bool:
        return self.current_hp > 0

    def hp_bar(self, length: int = 10) -> str:
        if self.max_hp <= 0:
            return "⬛" * length
        ratio = self.current_hp / self.max_hp
        filled = max(0, min(length, int(ratio * length)))
        empty = length - filled
        if ratio > 0.5:
            return "🟩" * filled + "⬛" * empty
        elif ratio > 0.25:
            return "🟨" * filled + "⬛" * empty
        else:
            return "🟥" * filled + "⬛" * empty

    def reset_turn_state(self):
        self.is_defending = False


# =====================================================
#  미궁 적 생성
# =====================================================

LABYRINTH_ENEMY_NAMES = {
    "normal": [
        "미궁 방랑냥", "그림자 고양이", "돌벽 수호냥", "독안개 냥",
        "미로 순찰냥", "어둠 잠복냥", "미궁 도적냥", "뼈다귀 냥",
        "이끼 냥", "결정체 냥", "부유 냥", "마력 냥",
        "폭주 냥", "강철 냥", "번개 냥", "화염 냥",
    ],
    "boss": [
        "미궁의 문지기",
        "그림자 군주",
        "결정의 수호자",
        "심연의 포식자",
        "혼돈의 지배자",
        "시간의 감시자",
        "차원의 균열자",
        "미궁 핵심체",
        "종말의 냥",
        "영원의 심판자",
    ],
}


# 층 기반 적 속성 배정
#  · 방어속성: 5층 구간마다 순환(경→중→특). 30층↑ 보스는 탄력장갑 등장(진동 요구)
#  · 공격속성: 3속성 순환 → 아군 방어속성/편성이 의미를 갖게 함
_ENEMY_DEF_CYCLE = ["light", "heavy", "special"]
_ENEMY_ATK_CYCLE = ["explosive", "piercing", "mystic"]


def _enemy_types_for_floor(floor: int, is_boss: bool) -> tuple[str, str]:
    defense = _ENEMY_DEF_CYCLE[(floor // 5) % len(_ENEMY_DEF_CYCLE)]
    if is_boss and floor >= 30 and (floor // 5) % 2 == 0:
        defense = "elastic"  # 고층 보스: 진동 딜러 요구
    attack = _ENEMY_ATK_CYCLE[floor % len(_ENEMY_ATK_CYCLE)]
    return attack, defense


def generate_labyrinth_enemy(floor: int, is_boss: bool = False) -> LabyrinthUnit:
    """층 수에 따라 스케일링된 적 생성"""
    if is_boss:
        boss_index = (floor // 5 - 1) % len(LABYRINTH_ENEMY_NAMES["boss"])
        name = f"🔥 {LABYRINTH_ENEMY_NAMES['boss'][boss_index]}"
        hp = int(BASE_ENEMY_HP * (1 + HP_SCALE_PER_FLOOR * floor) * BOSS_HP_MULTIPLIER)
        atk = int(BASE_ENEMY_ATK * (1 + ATK_SCALE_PER_FLOOR * floor) * BOSS_ATK_MULTIPLIER)
    else:
        name = random.choice(LABYRINTH_ENEMY_NAMES["normal"])
        hp = int(BASE_ENEMY_HP * (1 + HP_SCALE_PER_FLOOR * floor))
        atk = int(BASE_ENEMY_ATK * (1 + ATK_SCALE_PER_FLOOR * floor))

    speed = random.randint(3, 10) + floor // 10
    e_atk_type, e_def_type = _enemy_types_for_floor(floor, is_boss)
    return LabyrinthUnit(name=name, hp=hp, attack=atk, speed=speed, is_ally=False,
                         attack_type=e_atk_type, defense_type=e_def_type)


def generate_floor_enemies(floor: int) -> list[LabyrinthUnit]:
    """층에 맞는 적 구성 생성"""
    is_boss_floor = (floor % 5 == 0)

    if is_boss_floor:
        return [generate_labyrinth_enemy(floor, is_boss=True)]
    else:
        if floor <= 5:
            count = random.choice([1, 1, 2])
        elif floor <= 15:
            count = random.choice([1, 2, 2])
        elif floor <= 30:
            count = random.choice([2, 2, 3])
        else:
            count = random.choice([2, 3, 3])
        return [generate_labyrinth_enemy(floor) for _ in range(count)]


# =====================================================
#  층 보상 계산
# =====================================================

def calculate_floor_rewards(floor: int, is_boss: bool, user_data: dict) -> dict:
    """층 클리어 보상 계산"""
    money = int(BASE_FLOOR_MONEY * (1 + MONEY_SCALE_PER_FLOOR * floor))
    exp = int(BASE_FLOOR_EXP * (1 + EXP_SCALE_PER_FLOOR * floor))

    if is_boss:
        money = int(money * BOSS_REWARD_MULTIPLIER)
        exp = int(exp * BOSS_REWARD_MULTIPLIER)

    # 거래 스킬 보너스 — sell_price_bonus (% 단위)
    trade_bonus_pct = get_skill_effect(user_data, SKILL_TREE_TRADE, "sell_price_bonus")
    trade_multiplier = 1.0 + (trade_bonus_pct / 100.0)
    money = int(money * trade_multiplier)

    items = []

    # 참치캔 드롭
    tuna_chance = 0.15 + (floor * 0.005)
    if random.random() < min(tuna_chance, 0.6):
        tuna_count = 1 + floor // 10
        items.append(("참치캔", tuna_count))

    # 보스층 추가 보상
    if is_boss:
        items.append(("장비 강화석", 1))
        if floor >= 20 and random.random() < 0.3:
            items.append(("희귀 강화석", 1))
        if floor >= 40 and random.random() < 0.2:
            items.append(("전설 강화석", 1))

    # 10층 단위 마일스톤 보너스
    if floor % 10 == 0:
        milestone_money = floor * 100
        money += milestone_money
        items.append(("마일스톤 보너스", milestone_money))

    return {
        "money": money,
        "exp": exp,
        "items": items,
    }


# =====================================================
#  이벤트 타일
# =====================================================

def pick_event() -> str | None:
    """이벤트 타일 발생 여부 판정 및 종류 반환"""
    if random.random() > EVENT_CHANCE:
        return None

    events = list(EVENT_WEIGHTS.keys())
    weights = list(EVENT_WEIGHTS.values())
    return random.choices(events, weights=weights, k=1)[0]


def apply_event(
    event_type: str,
    allies: list[LabyrinthUnit],
    floor: int,
    run_data: dict
) -> tuple[discord.Embed, bool]:
    """
    이벤트 적용
    Returns: (이벤트 임베드, 계속 진행 가능 여부)
    """
    can_continue = True

    if event_type == "rest":
        heal_percent = random.uniform(0.20, 0.35)
        heal_lines = []
        for unit in allies:
            if unit.is_alive():
                heal_amount = int(unit.max_hp * heal_percent)
                actual_heal = unit.heal(heal_amount)
                if actual_heal > 0:
                    heal_lines.append(f"😺 **{unit.name}** +{actual_heal} HP ({unit.current_hp}/{unit.max_hp})")

        embed = discord.Embed(
            title="🏕️ 휴식처 발견!",
            description=(
                f"미궁 속 안전한 공간을 발견했습니다.\n"
                f"잠시 쉬어가며 체력을 회복합니다.\n\n"
                + ("\n".join(heal_lines) if heal_lines else "회복할 대상이 없습니다.")
            ),
            color=COLOR_SUCCESS
        )

    elif event_type == "trap":
        dmg_percent = random.uniform(0.10, 0.20)
        dmg_lines = []
        for unit in allies:
            if unit.is_alive():
                damage = max(1, int(unit.max_hp * dmg_percent))
                actual_dmg = unit.take_damage(damage)
                status = "💀" if not unit.is_alive() else "😿"
                dmg_lines.append(f"{status} **{unit.name}** -{actual_dmg} HP ({unit.current_hp}/{unit.max_hp})")

        alive = [u for u in allies if u.is_alive()]
        if not alive:
            can_continue = False

        embed = discord.Embed(
            title="⚠️ 함정 발동!",
            description=(
                f"바닥에서 가시가 솟아올랐습니다!\n\n"
                + "\n".join(dmg_lines)
                + ("\n\n💀 **전멸! 미궁 탐색이 종료됩니다...**" if not can_continue else "")
            ),
            color=COLOR_ERROR
        )

    elif event_type == "treasure":
        bonus_money = int(BASE_FLOOR_MONEY * (1 + floor * 0.15) * random.uniform(1.5, 3.0))
        run_data["accumulated_money"] = run_data.get("accumulated_money", 0) + bonus_money

        item_text = f"💰 **{bonus_money:,}원** 획득!"
        extra_items = []

        roll = random.random()
        if roll < 0.1:
            extra_items.append("희귀 강화석")
            run_data.setdefault("accumulated_items", []).append(("희귀 강화석", 1))
        elif roll < 0.3:
            tuna = random.randint(1, 3)
            extra_items.append(f"참치캔 x{tuna}")
            run_data.setdefault("accumulated_items", []).append(("참치캔", tuna))

        if extra_items:
            item_text += "\n" + "\n".join([f"📦 {item}" for item in extra_items])

        embed = discord.Embed(
            title="🎁 보물 상자 발견!",
            description=f"미궁 깊은 곳에 숨겨진 보물을 발견했습니다!\n\n{item_text}",
            color=COLOR_RARE
        )

    elif event_type == "merchant":
        current_money = run_data.get("accumulated_money", 0)
        cost = max(100, int(current_money * 0.15))

        if current_money >= cost:
            run_data["accumulated_money"] = current_money - cost
            heal_lines = []
            for unit in allies:
                if unit.is_alive():
                    heal_amount = int(unit.max_hp * 0.40)
                    actual_heal = unit.heal(heal_amount)
                    if actual_heal > 0:
                        heal_lines.append(f"😺 **{unit.name}** +{actual_heal} HP")

            embed = discord.Embed(
                title="🏪 떠돌이 상인!",
                description=(
                    f"미궁을 떠도는 상인을 만났습니다.\n"
                    f"💰 **{cost:,}원**을 지불하고 회복 물약을 구매했습니다.\n\n"
                    + ("\n".join(heal_lines) if heal_lines else "회복할 대상이 없습니다.")
                ),
                color=COLOR_PRIMARY
            )
        else:
            embed = discord.Embed(
                title="🏪 떠돌이 상인!",
                description=(
                    f"미궁을 떠도는 상인을 만났지만...\n"
                    f"돈이 부족합니다! (필요: {cost:,}원 / 보유: {current_money:,}원)\n"
                    f"상인이 아쉬운 듯 떠나갑니다."
                ),
                color=COLOR_WARNING
            )

    elif event_type == "mystery":
        mystery_roll = random.random()
        if mystery_roll < 0.3:
            buff_amount = random.randint(3, 8) + floor // 5
            for unit in allies:
                if unit.is_alive():
                    unit.attack += buff_amount
            embed = discord.Embed(
                title="✨ 신비로운 기운!",
                description=(
                    f"미궁의 신비로운 기운이 냥이들을 감쌉니다.\n"
                    f"⚔️ 아군 전원 공격력 **+{buff_amount}** 증가! (이번 층 한정)"
                ),
                color=COLOR_LEGENDARY
            )
        elif mystery_roll < 0.55:
            heal_pct = random.uniform(0.10, 0.20)
            for unit in allies:
                if unit.is_alive():
                    unit.heal(int(unit.max_hp * heal_pct))
            embed = discord.Embed(
                title="💫 치유의 빛!",
                description=f"미궁에서 빛이 쏟아져 내립니다.\n❤️ 아군 전원 HP **{int(heal_pct*100)}%** 회복!",
                color=COLOR_SUCCESS
            )
        elif mystery_roll < 0.75:
            dmg_pct = random.uniform(0.05, 0.12)
            for unit in allies:
                if unit.is_alive():
                    unit.take_damage(max(1, int(unit.max_hp * dmg_pct)))
            alive = [u for u in allies if u.is_alive()]
            if not alive:
                can_continue = False
            embed = discord.Embed(
                title="🌫️ 독안개!",
                description=(
                    f"미궁에 독안개가 피어오릅니다.\n"
                    f"☠️ 아군 전원 HP **{int(dmg_pct*100)}%** 감소!"
                    + ("\n\n💀 **전멸!**" if not can_continue else "")
                ),
                color=COLOR_ERROR
            )
        else:
            embed = discord.Embed(
                title="❓ 이상한 기운...",
                description="미궁에서 이상한 기운이 느껴졌지만... 아무 일도 일어나지 않았습니다.",
                color=COLOR_WARNING
            )

    else:
        embed = discord.Embed(
            title="❓ 알 수 없는 이벤트",
            description="무언가 일어날 뻔했지만, 그냥 지나갔습니다.",
            color=COLOR_WARNING
        )

    return embed, can_continue


# =====================================================
#  미궁 전투 (한 층)
# =====================================================

class LabyrinthActionView(discord.ui.View):
    """미궁 전투 행동 선택 UI"""

    def __init__(self, user_id: int, can_use_skill: bool = True, timeout: float = 25.0):
        super().__init__(timeout=timeout)
        self.user_id = user_id
        self.chosen_action: str | None = None

        if not can_use_skill:
            self.skill_button.disabled = True
            self.skill_button.style = discord.ButtonStyle.secondary

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("이 미궁의 탐색자가 아닙니다.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="⚔️ 공격", style=discord.ButtonStyle.danger, custom_id="lab_attack")
    async def attack_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.chosen_action = "attack"
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="🛡️ 방어", style=discord.ButtonStyle.primary, custom_id="lab_defend")
    async def defend_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.chosen_action = "defend"
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="💥 전력 공격", style=discord.ButtonStyle.success, custom_id="lab_skill")
    async def skill_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.chosen_action = "skill"
        await interaction.response.defer()
        self.stop()

    async def on_timeout(self):
        self.chosen_action = "attack"
        self.stop()


class LabyrinthTargetView(discord.ui.View):
    """미궁 전투 타겟 선택"""

    def __init__(self, enemies: list[LabyrinthUnit], user_id: int, timeout: float = 15.0):
        super().__init__(timeout=timeout)
        self.user_id = user_id
        self.selected_index: int | None = None

        for i, enemy in enumerate(enemies):
            if enemy.is_alive():
                btn = discord.ui.Button(
                    label=f"👹 {enemy.name} (HP {enemy.current_hp})",
                    style=discord.ButtonStyle.secondary,
                    custom_id=f"lab_target_{i}"
                )
                btn.callback = self._make_callback(i)
                self.add_item(btn)

    def _make_callback(self, index: int):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("이 미궁의 탐색자가 아닙니다.", ephemeral=True)
                return
            self.selected_index = index
            await interaction.response.defer()
            self.stop()
        return callback

    async def on_timeout(self):
        self.selected_index = 0
        self.stop()


class FloorContinueView(discord.ui.View):
    """층 클리어 후 계속/퇴장 선택"""

    def __init__(self, user_id: int, timeout: float = 30.0):
        super().__init__(timeout=timeout)
        self.user_id = user_id
        self.continue_choice: bool | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("이 미궁의 탐색자가 아닙니다.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="⬆️ 다음 층으로", style=discord.ButtonStyle.success, custom_id="lab_continue")
    async def continue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.continue_choice = True
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="🚪 미궁 퇴장 (보상 확보)", style=discord.ButtonStyle.danger, custom_id="lab_exit")
    async def exit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.continue_choice = False
        await interaction.response.defer()
        self.stop()

    async def on_timeout(self):
        self.continue_choice = False
        self.stop()


# =====================================================
#  미궁 전투 임베드 빌더
# =====================================================

def build_floor_status_embed(
    floor: int,
    allies: list[LabyrinthUnit],
    enemies: list[LabyrinthUnit],
    turn: int,
    sp: int,
    run_data: dict,
    log_lines: list[str] | None = None
) -> discord.Embed:
    """미궁 전투 상태 임베드"""
    is_boss = (floor % 5 == 0)
    title_prefix = "💀 보스층" if is_boss else "🏛️ 미궁"

    embed = discord.Embed(
        title=f"{title_prefix} — {floor}층",
        description=(
            f"**턴 {turn}** / 최대 {MAX_FLOOR_TURNS}턴\n"
            f"누적 보상: 💰 {run_data.get('accumulated_money', 0):,}원 | "
            f"✨ {run_data.get('accumulated_exp', 0)} EXP"
        ),
        color=COLOR_LEGENDARY if is_boss else COLOR_PRIMARY
    )

    from models.element import attack_label, defense_label

    ally_lines = []
    for unit in allies:
        status = "💀" if not unit.is_alive() else "😺"
        ally_lines.append(
            f"{status} **{unit.name}** {attack_label(unit.attack_type)} {unit.hp_bar()} "
            f"HP {unit.current_hp}/{unit.max_hp} | ATK {unit.attack}"
        )
    embed.add_field(name="🐱 아군", value="\n".join(ally_lines), inline=False)

    enemy_lines = []
    for unit in enemies:
        status = "💀" if not unit.is_alive() else ("🔥" if is_boss else "👹")
        enemy_lines.append(
            f"{status} **{unit.name}** {defense_label(unit.defense_type)} {unit.hp_bar()} "
            f"HP {unit.current_hp}/{unit.max_hp} | ATK {unit.attack}"
        )
    embed.add_field(name="👹 적", value="\n".join(enemy_lines), inline=False)

    sp_capped = min(sp, 6)
    sp_bar = "🔵" * sp_capped + "⚫" * (6 - sp_capped)
    embed.add_field(name="💎 SP", value=f"{sp_bar} ({sp}/6)", inline=False)

    if log_lines:
        recent = log_lines[-5:]
        embed.add_field(name="📜 로그", value="\n".join(recent), inline=False)

    return embed


# =====================================================
#  한 층 전투 실행
# =====================================================

async def run_floor_battle(
    msg: discord.Message,
    user_id: int,
    floor: int,
    allies: list[LabyrinthUnit],
    run_data: dict
) -> bool:
    """
    한 층의 전투를 실행
    Returns: True if victory, False if defeat
    """
    enemies = generate_floor_enemies(floor)
    is_boss = (floor % 5 == 0)
    sp = run_data.get("sp", 3)
    turn = 0
    log_lines: list[str] = []

    if is_boss:
        log_lines.append(f"🔥 **보스 출현!** {enemies[0].name}이(가) 나타났다!")
    else:
        enemy_names = ", ".join([e.name for e in enemies])
        log_lines.append(f"👹 {enemy_names}이(가) 나타났다!")

    status_embed = build_floor_status_embed(floor, allies, enemies, turn, sp, run_data, log_lines)
    try:
        await msg.edit(embed=status_embed, view=None)
    except Exception:
        pass
    await asyncio.sleep(1.5)

    while turn < MAX_FLOOR_TURNS:
        turn += 1

        sp = min(6, sp + 1)

        living_allies = [u for u in allies if u.is_alive()]
        living_enemies = [u for u in enemies if u.is_alive()]

        if not living_allies:
            break
        if not living_enemies:
            break

        ally_actions: list[tuple[LabyrinthUnit, str, int]] = []

        for ally in allies:
            ally.reset_turn_state()
        for enemy in enemies:
            enemy.reset_turn_state()

        for ally in living_allies:
            can_skill = sp >= 2
            action_view = LabyrinthActionView(user_id, can_use_skill=can_skill)
            status_embed = build_floor_status_embed(floor, allies, enemies, turn, sp, run_data, log_lines)
            status_embed.set_footer(text=f"🐱 {ally.name}의 행동을 선택하세요!")

            try:
                await msg.edit(embed=status_embed, view=action_view)
            except Exception:
                pass

            await action_view.wait()
            action = action_view.chosen_action or "attack"

            target_idx = 0
            if action in ("attack", "skill"):
                current_living = [e for e in enemies if e.is_alive()]
                if len(current_living) > 1:
                    target_view = LabyrinthTargetView(enemies, user_id)
                    status_embed.set_footer(text=f"🎯 {ally.name}의 공격 대상을 선택하세요!")
                    try:
                        await msg.edit(embed=status_embed, view=target_view)
                    except Exception:
                        pass
                    await target_view.wait()
                    target_idx = target_view.selected_index if target_view.selected_index is not None else 0
                    if target_idx >= len(enemies) or not enemies[target_idx].is_alive():
                        for ei, e in enumerate(enemies):
                            if e.is_alive():
                                target_idx = ei
                                break
                elif current_living:
                    target_idx = enemies.index(current_living[0])

            ally_actions.append((ally, action, target_idx))

        # ── 아군 행동 실행 ──
        for ally, action, target_idx in ally_actions:
            if not ally.is_alive():
                continue

            if action == "attack":
                if target_idx < len(enemies) and enemies[target_idx].is_alive():
                    target = enemies[target_idx]
                    damage = max(1, ally.attack + random.randint(-2, 4))
                    if ally.defend_buff:
                        damage = int(damage * 1.3)
                        ally.defend_buff = False
                    damage, mult = _apply_type(ally, target, damage)
                    actual = target.take_damage(damage)
                    run_data["total_damage_dealt"] = run_data.get("total_damage_dealt", 0) + actual
                    log_lines.append(f"⚔️ {ally.name} → {target.name} | {actual} 데미지{_tag(mult)}")
                    if not target.is_alive():
                        log_lines.append(f"💀 {target.name} 처치!")

            elif action == "defend":
                ally.is_defending = True
                ally.defend_buff = True
                log_lines.append(f"🛡️ {ally.name} 방어 태세! (피해 50% 감소, 다음 공격 +30%)")

            elif action == "skill":
                if sp >= 2:
                    sp -= 2
                    if target_idx < len(enemies) and enemies[target_idx].is_alive():
                        target = enemies[target_idx]
                        damage = max(1, int(ally.attack * 1.8) + random.randint(0, 6))
                        damage, mult = _apply_type(ally, target, damage)
                        actual = target.take_damage(damage)
                        run_data["total_damage_dealt"] = run_data.get("total_damage_dealt", 0) + actual
                        log_lines.append(f"💥 {ally.name} 전력 공격! → {target.name} | {actual} 데미지!{_tag(mult)}")
                        if not target.is_alive():
                            log_lines.append(f"💀 {target.name} 처치!")
                else:
                    if target_idx < len(enemies) and enemies[target_idx].is_alive():
                        target = enemies[target_idx]
                        damage = max(1, ally.attack + random.randint(-2, 4))
                        damage, mult = _apply_type(ally, target, damage)
                        actual = target.take_damage(damage)
                        run_data["total_damage_dealt"] = run_data.get("total_damage_dealt", 0) + actual
                        log_lines.append(f"⚔️ {ally.name} → {target.name} | {actual} 데미지 (SP 부족){_tag(mult)}")

        if not [e for e in enemies if e.is_alive()]:
            break

        # ── 적 행동 ──
        for enemy in enemies:
            if not enemy.is_alive():
                continue

            roll = random.random()
            if roll < 0.70:
                targets = [a for a in allies if a.is_alive()]
                if targets:
                    if random.random() < 0.5:
                        targets.sort(key=lambda u: u.current_hp)
                    target = targets[0] if random.random() < 0.5 else random.choice(targets)
                    damage = max(1, enemy.attack + random.randint(-3, 3))
                    damage, mult = _apply_type(enemy, target, damage)
                    actual = target.take_damage(damage)
                    run_data["total_damage_taken"] = run_data.get("total_damage_taken", 0) + actual
                    log_lines.append(f"👹 {enemy.name} → {target.name} | {actual} 데미지{_tag(mult)}")
                    if not target.is_alive():
                        log_lines.append(f"💀 {target.name} 전사...")
            elif roll < 0.90:
                enemy.is_defending = True
                log_lines.append(f"🛡️ {enemy.name} 방어!")
            else:
                targets = [a for a in allies if a.is_alive()]
                if targets:
                    target = random.choice(targets)
                    damage = max(1, int(enemy.attack * 1.5) + random.randint(0, 5))
                    damage, mult = _apply_type(enemy, target, damage)
                    actual = target.take_damage(damage)
                    run_data["total_damage_taken"] = run_data.get("total_damage_taken", 0) + actual
                    log_lines.append(f"💥 {enemy.name} 강공격! → {target.name} | {actual} 데미지!{_tag(mult)}")
                    if not target.is_alive():
                        log_lines.append(f"💀 {target.name} 전사...")

        if not [a for a in allies if a.is_alive()]:
            break

        status_embed = build_floor_status_embed(floor, allies, enemies, turn, sp, run_data, log_lines)
        try:
            await msg.edit(embed=status_embed, view=None)
        except Exception:
            pass
        await asyncio.sleep(1.5)

    # ── 전투 결과 ──
    run_data["sp"] = sp

    ally_alive = bool([a for a in allies if a.is_alive()])

    if ally_alive and not [e for e in enemies if e.is_alive()]:
        return True
    else:
        return False


# =====================================================
#  메인 미궁 시퀀스
# =====================================================

async def run_labyrinth_sequence(
    interaction: discord.Interaction,
    user_data: dict
) -> dict:
    """
    미궁 메인 시퀀스
    Returns: 런 결과 dict
    """
    user_id = interaction.user.id

    # ── 아군 유닛 구성 ──
    owned_cats = user_data.get("cats", {})
    cat_list = []

    for cat_name, cat_data in owned_cats.items():
        # ★ 모든 타입 안전 처리
        if isinstance(cat_data, dict):
            count = cat_data.get("count", 0)
            rarity = cat_data.get("rarity", "common")
            try:
                count = int(count)
            except (ValueError, TypeError):
                count = 1
        elif isinstance(cat_data, (int, float)):
            count = int(cat_data)
            rarity = "common"
        elif isinstance(cat_data, str):
            # ★ 이 부분이 핵심 — cat_data가 "common" 같은 문자열일 때
            try:
                count = int(cat_data)
                rarity = "common"
            except ValueError:
                # 숫자가 아닌 문자열 → rarity 이름일 수 있음
                count = 1
                rarity = cat_data if cat_data in ("common", "uncommon", "rare", "epic", "legendary", "mythic") else "common"
        else:
            count = 1
            rarity = "common"

        if count <= 0:
            continue

        cat_info = get_cat_by_name(cat_name)
        if cat_info is None:
            rarity_power = {
                "common": 10, "uncommon": 15, "rare": 22,
                "epic": 30, "legendary": 42, "mythic": 55
            }
            rarity_hp = {
                "common": 100, "uncommon": 130, "rare": 170,
                "epic": 220, "legendary": 300, "mythic": 400
            }
            cat_info = {
                "name": cat_name,
                "rarity": rarity,
                "base_power": rarity_power.get(rarity, 10),
                "hp": rarity_hp.get(rarity, 100),
            }

        cat_list.append(cat_info)

    # ── 강화(성작/초월) 냥이 편입 — 강화 스탯 반영 ──
    # 일반 cats와 분리 저장된 enhanced_cats를 전투 풀에 합류시킨다.
    # 강화 냥이는 스탯이 높아 자연스럽게 상위 3인 팀에 선발됨 → 수집·강화의 쓰임새.
    try:
        from systems.enhancement import get_enhanced_stats, star_label
        for inst in user_data.get("enhanced_cats", []):
            if not isinstance(inst, dict):
                continue
            s = get_enhanced_stats(inst)
            cat_list.append({
                "name": f"{s['name']} {star_label(inst)}",
                "rarity": "epic",
                "base_power": s["base_power"],
                "hp": s["hp"],
                "attack_type": s["attack_type"],
                "defense_type": s["defense_type"],
            })
    except Exception:
        pass

    if not cat_list:
        return None

    cat_list.sort(key=lambda c: c.get("base_power", 10), reverse=True)
    team = cat_list[:3]

    equip_stats = get_total_equipment_stats(user_data)
    user_level = user_data.get("level", 1)
    level_mult = 1.0 + (user_level * 0.02)

    # 전투 스킬 보너스 — 가산 방식
    combat_power_bonus = get_skill_effect(user_data, SKILL_TREE_COMBAT, "battle_power_bonus")
    combat_hp_bonus = get_skill_effect(user_data, SKILL_TREE_COMBAT, "battle_hp_bonus")

    allies: list[LabyrinthUnit] = []
    for cat_data in team:
        base_atk = cat_data.get("base_power", 10)
        base_hp = cat_data.get("hp", 100)

        final_atk = int(base_atk * level_mult) + equip_stats.get("attack", 0) + int(combat_power_bonus)
        final_hp = int(base_hp * level_mult) + equip_stats.get("hp_bonus", 0) + int(combat_hp_bonus)

        c_atk_type, c_def_type = get_cat_types(cat_data)
        unit = LabyrinthUnit(
            name=cat_data["name"],
            hp=final_hp,
            attack=final_atk,
            speed=random.randint(5, 15),
            is_ally=True,
            attack_type=c_atk_type,
            defense_type=c_def_type,
        )
        allies.append(unit)

    # ── 런 데이터 초기화 ──
    run_data = {
        "accumulated_money": 0,
        "accumulated_exp": 0,
        "accumulated_items": [],
        "highest_floor": 0,
        "sp": 3,
        "total_damage_dealt": 0,
        "total_damage_taken": 0,
        "floors_cleared": 0,
    }

    # 팀 소개 임베드
    team_embed = discord.Embed(
        title="🏛️ 무한 미궁 진입",
        description=(
            f"**최강 냥이 팀**으로 미궁에 진입합니다!\n"
            f"5층마다 보스가 등장합니다. 전멸 시 탐색이 종료되지만,\n"
            f"그때까지의 보상은 모두 유지됩니다.\n\n"
            f"🚪 언제든 **퇴장**하여 보상을 확보할 수 있습니다."
        ),
        color=COLOR_PRIMARY
    )
    from models.element import attack_label
    team_text = "\n".join([
        f"**{i+1}.** {a.name} {attack_label(a.attack_type)} | ATK {a.attack} | HP {a.max_hp}"
        for i, a in enumerate(allies)
    ])
    team_embed.add_field(name="🐱 출전 팀", value=team_text, inline=False)
    team_embed.set_footer(text="미궁 탐색을 시작합니다...", icon_url=BOT_ICON)

    msg = await interaction.followup.send(embed=team_embed, wait=True)

    await asyncio.sleep(2.0)

    # ── 층 루프 ──
    floor = 0
    while True:
        floor += 1
        is_boss = (floor % 5 == 0)

        if floor >= 2 and not is_boss:
            event_type = pick_event()
            if event_type:
                event_embed, can_continue = apply_event(event_type, allies, floor, run_data)
                event_embed.set_footer(text=f"🏛️ {floor}층 이벤트")
                try:
                    await msg.edit(embed=event_embed, view=None)
                except Exception:
                    pass
                await asyncio.sleep(2.5)

                if not can_continue:
                    run_data["highest_floor"] = floor - 1
                    break

        if is_boss:
            floor_announce = discord.Embed(
                title=f"💀 {floor}층 — 보스 출현!",
                description="강력한 적이 기다리고 있습니다...\n각오를 단단히 하세요!",
                color=COLOR_MYTHIC
            )
        else:
            floor_announce = discord.Embed(
                title=f"🏛️ {floor}층 진입",
                description=f"미궁 {floor}층에 진입합니다...",
                color=COLOR_PRIMARY
            )

        ally_status = "\n".join([
            f"{'😺' if a.is_alive() else '💀'} {a.name} {a.hp_bar()} HP {a.current_hp}/{a.max_hp}"
            for a in allies
        ])
        floor_announce.add_field(name="🐱 아군 상태", value=ally_status, inline=False)
        floor_announce.add_field(
            name="💰 누적 보상",
            value=f"💰 {run_data['accumulated_money']:,}원 | ✨ {run_data['accumulated_exp']} EXP",
            inline=False
        )

        try:
            await msg.edit(embed=floor_announce, view=None)
        except Exception:
            pass
        await asyncio.sleep(1.5)

        victory = await run_floor_battle(msg, user_id, floor, allies, run_data)

        if not victory:
            run_data["highest_floor"] = max(run_data.get("highest_floor", 0), floor - 1)
            run_data["defeat_floor"] = floor

            defeat_embed = discord.Embed(
                title=f"💀 {floor}층에서 전멸!",
                description=(
                    f"미궁 {floor}층에서 아군이 전멸했습니다...\n"
                    f"최고 도달 층: **{floor}층**"
                ),
                color=COLOR_ERROR
            )
            try:
                await msg.edit(embed=defeat_embed, view=None)
            except Exception:
                pass
            await asyncio.sleep(2.0)
            break

        run_data["floors_cleared"] = floor
        run_data["highest_floor"] = floor
        floor_rewards = calculate_floor_rewards(floor, is_boss, user_data)

        run_data["accumulated_money"] = run_data.get("accumulated_money", 0) + floor_rewards["money"]
        run_data["accumulated_exp"] = run_data.get("accumulated_exp", 0) + floor_rewards["exp"]
        for item_name, qty in floor_rewards.get("items", []):
            run_data.setdefault("accumulated_items", []).append((item_name, qty))

        clear_emoji = "🔥" if is_boss else "✅"
        clear_embed = discord.Embed(
            title=f"{clear_emoji} {floor}층 클리어!",
            description=f"{'보스를 처치했습니다!' if is_boss else '적을 모두 쓰러뜨렸습니다!'}",
            color=COLOR_LEGENDARY if is_boss else COLOR_SUCCESS
        )

        reward_lines = [
            f"💰 +{floor_rewards['money']:,}원",
            f"✨ +{floor_rewards['exp']} EXP",
        ]
        for item_name, qty in floor_rewards.get("items", []):
            reward_lines.append(f"📦 {item_name} x{qty}")

        clear_embed.add_field(
            name="🎁 층 보상",
            value="\n".join(reward_lines),
            inline=True
        )
        clear_embed.add_field(
            name="💰 누적 합계",
            value=(
                f"💰 {run_data['accumulated_money']:,}원\n"
                f"✨ {run_data['accumulated_exp']} EXP"
            ),
            inline=True
        )

        continue_view = FloorContinueView(user_id)
        clear_embed.set_footer(text="다음 층으로 진행하거나, 퇴장하여 보상을 확보하세요!")

        try:
            await msg.edit(embed=clear_embed, view=continue_view)
        except Exception:
            pass

        await continue_view.wait()

        if not continue_view.continue_choice:
            exit_embed = discord.Embed(
                title="🚪 미궁 퇴장",
                description=f"**{floor}층**까지 클리어하고 미궁을 빠져나왔습니다!",
                color=COLOR_SUCCESS
            )
            try:
                await msg.edit(embed=exit_embed, view=None)
            except Exception:
                pass
            await asyncio.sleep(1.0)
            break

    return run_data


# =====================================================
#  보상 적용
# =====================================================

def apply_labyrinth_rewards(user_data: dict, run_data: dict) -> dict:
    """
    미궁 런 결과를 유저 데이터에 적용
    Returns: 적용된 보상 요약 dict
    """
    money = run_data.get("accumulated_money", 0)
    exp = run_data.get("accumulated_exp", 0)
    items = run_data.get("accumulated_items", [])

    user_data["money"] = user_data.get("money", 0) + money

    tuna_total = 0
    other_items = {}
    for item_name, qty in items:
        if item_name == "참치캔":
            tuna_total += qty
        elif item_name == "마일스톤 보너스":
            pass
        else:
            other_items[item_name] = other_items.get(item_name, 0) + qty

    if tuna_total > 0:
        user_data["tuna_can"] = user_data.get("tuna_can", 0) + tuna_total

    inv = user_data.setdefault("item_inventory", {})
    for item_name, qty in other_items.items():
        inv[item_name] = inv.get(item_name, 0) + qty

    labyrinth_stats = user_data.setdefault("labyrinth_stats", {
        "total_runs": 0,
        "highest_floor": 0,
        "total_floors_cleared": 0,
        "total_money_earned": 0,
        "total_exp_earned": 0,
    })

    labyrinth_stats["total_runs"] = labyrinth_stats.get("total_runs", 0) + 1
    labyrinth_stats["total_floors_cleared"] = (
        labyrinth_stats.get("total_floors_cleared", 0) + run_data.get("floors_cleared", 0)
    )
    labyrinth_stats["total_money_earned"] = labyrinth_stats.get("total_money_earned", 0) + money
    labyrinth_stats["total_exp_earned"] = labyrinth_stats.get("total_exp_earned", 0) + exp

    new_record = False
    current_highest = labyrinth_stats.get("highest_floor", 0)
    run_highest = run_data.get("highest_floor", 0)
    if run_highest > current_highest:
        labyrinth_stats["highest_floor"] = run_highest
        new_record = True

    return {
        "money": money,
        "exp": exp,
        "tuna": tuna_total,
        "other_items": other_items,
        "highest_floor": run_highest,
        "new_record": new_record,
        "previous_record": current_highest,
    }


# =====================================================
#  미궁 결과 임베드
# =====================================================

def build_labyrinth_result_embed(
    user_name: str,
    reward_summary: dict,
    run_data: dict
) -> discord.Embed:
    """미궁 최종 결과 임베드"""
    highest = run_data.get("highest_floor", 0)
    new_record = reward_summary.get("new_record", False)

    if new_record:
        title = f"🏆 미궁 탐색 완료 — 신기록!"
        color = COLOR_MYTHIC
        desc = (
            f"**{user_name}**님이 미궁 **{highest}층**에 도달했습니다!\n"
            f"🎉 **신기록 달성!** (이전: {reward_summary.get('previous_record', 0)}층)"
        )
    elif run_data.get("defeat_floor"):
        title = f"💀 미궁 탐색 종료"
        color = COLOR_ERROR
        desc = f"**{user_name}**님이 미궁 **{run_data['defeat_floor']}층**에서 전멸했습니다."
    else:
        title = f"🚪 미궁 탐색 완료"
        color = COLOR_SUCCESS
        desc = f"**{user_name}**님이 미궁 **{highest}층**까지 클리어하고 퇴장했습니다."

    embed = discord.Embed(title=title, description=desc, color=color)

    reward_lines = [
        f"💰 **{reward_summary.get('money', 0):,}원**",
        f"✨ **{reward_summary.get('exp', 0)} EXP**",
    ]
    if reward_summary.get("tuna", 0) > 0:
        reward_lines.append(f"🐟 참치캔 x{reward_summary['tuna']}")
    for item_name, qty in reward_summary.get("other_items", {}).items():
        reward_lines.append(f"📦 {item_name} x{qty}")

    embed.add_field(name="🎁 획득 보상", value="\n".join(reward_lines), inline=False)

    stats_lines = [
        f"🏛️ 클리어 층 수: **{run_data.get('floors_cleared', 0)}층**",
        f"💥 총 딜량: **{run_data.get('total_damage_dealt', 0):,}**",
        f"🩸 총 피해량: **{run_data.get('total_damage_taken', 0):,}**",
    ]
    embed.add_field(name="📊 탐색 통계", value="\n".join(stats_lines), inline=False)

    if highest >= 50:
        rank = "🌟 미궁의 정복자"
    elif highest >= 30:
        rank = "👑 심연 탐험가"
    elif highest >= 20:
        rank = "⭐ 숙련 탐색자"
    elif highest >= 10:
        rank = "⚔️ 미궁 도전자"
    elif highest >= 5:
        rank = "🗡️ 초보 탐색자"
    else:
        rank = "🌱 미궁 입문자"

    embed.add_field(name="🏅 탐색 등급", value=rank, inline=False)

    embed.set_footer(text="💡 /미궁기록 으로 누적 통계를 확인하세요!", icon_url=BOT_ICON)

    return embed
